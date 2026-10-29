#!/usr/bin/env python3
"""Run every verification step for a project and record real results.

Usage:
  python verify.py <project-dir> [--only kind,kind] [--skip kind,kind]
                   [--project <subdir> ...] [--timeout SECONDS] [--out DIR]
                   [--env KEY=VALUE ...] [--env-file FILE] [--ignore-scripts]

Steps come from detect_checks.py (install, typecheck, lint, build, test) and
run in each project directory of a monorepo. Writes <out>/results.json and
<out>/VERIFICATION.md (default out: <project>/.verify) so a claim like
"tests pass" is backed by exit codes and captured output.
Exit code is 0 only if every step that ran passed.

Builds often need variables just to compile. Pass placeholders with
--env KEY=VALUE or --env-file .env.example. Variables that change how code is
loaded (PATH, NODE_OPTIONS, LD_PRELOAD, ...) are refused, and values are never
printed or written to the report.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from detect_checks import detect, find_projects, is_workspace_root, MAX_PROJECTS  # noqa: E402
import envutil  # noqa: E402
from changed_files import diff as snapshot_diff, iter_files, take_snapshot  # noqa: E402

TAIL_LINES = 40
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
MAX_RESTORE_FILE = 512 * 1024
MAX_RESTORE_TOTAL = 50 * 1024 * 1024


def failure_excerpt(output: str, limit: int = TAIL_LINES) -> str:
    """Last lines of output, but with TAP `not ok` blocks (the real assertion) moved to the top.

    Node's test runner prints the failing assertion in the middle of a long log;
    the plain tail would show only the summary. Other runners keep the plain tail.
    """
    lines = ANSI_RE.sub("", output).strip().splitlines()
    blocks: list[str] = []
    i = 0
    while i < len(lines):
        if re.match(r"^\s*not ok\b", lines[i]):
            j = i + 1
            while j < len(lines) and not re.match(r"^\s*(not ok|ok)\b|^#", lines[j]):
                j += 1
            blocks.append("\n".join(lines[i:j][:25]))
            i = j
        else:
            i += 1
    tail = "\n".join(lines[-limit:])
    if not blocks:
        return tail
    head = "\n".join(blocks)
    head_lines = head.splitlines()
    if len(head_lines) > 2 * limit:
        head = "\n".join(head_lines[: 2 * limit]) + "\n... (more failing tests, see full output)"
    return f"[failing tests]\n{head}\n\n[end of output]\n{tail}"


def run_step(step: dict, root: Path, timeout: int, extra_env: dict[str, str] | None = None) -> dict:
    env = dict(os.environ)
    env.update({"CI": "1", "NEXT_TELEMETRY_DISABLED": "1", "FORCE_COLOR": "0"})
    env.update(extra_env or {})
    cwd = root / step.get("cwd", ".")
    start = time.time()
    try:
        proc = subprocess.run(
            step["cmd"], shell=True, cwd=cwd, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, errors="replace", timeout=timeout,
        )
        code, output, status = proc.returncode, proc.stdout, ("passed" if proc.returncode == 0 else "failed")
    except subprocess.TimeoutExpired as e:
        raw = e.stdout or ""
        output = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        code, status = None, "timeout"
    return {
        **step,
        "status": status,
        "exit_code": code,
        "seconds": round(time.time() - start, 1),
        "tail": failure_excerpt(output) if status != "passed" else "\n".join(ANSI_RE.sub("", output).strip().splitlines()[-TAIL_LINES:]),
    }


def read_originals(root: Path, snapshot: dict[str, str]) -> dict[str, bytes] | None:
    """Keep the pre-run bytes of small files so tool side effects can be undone."""
    originals: dict[str, bytes] = {}
    total = 0
    for path, rel in iter_files(root):
        size = path.stat().st_size
        if size > MAX_RESTORE_FILE:
            continue
        total += size
        if total > MAX_RESTORE_TOTAL:
            return None
        originals[rel] = path.read_bytes()
    return originals


def label(step: dict) -> str:
    where = step.get("cwd", ".")
    return step["cmd"] if where == "." else f"{step['cmd']}  (in {where})"


def write_reports(results: list[dict], root: Path, out: Path, side_effects: dict | None = None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    side_effects = side_effects or {}
    (out / "side_effects.json").write_text(json.dumps(side_effects, indent=2), encoding="utf-8")

    icon = {"passed": "PASS", "failed": "FAIL", "timeout": "TIMEOUT", "skipped": "SKIPPED"}
    lines = [
        "# Verification report",
        "",
        f"Project: `{root}`",
        "",
        "| Step | Directory | Command | Result | Time |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(f"| {r['kind']} | `{r.get('cwd', '.')}` | `{r['cmd']}` | {icon[r['status']]} | {r['seconds']}s |")
    failures = [r for r in results if r["status"] in ("failed", "timeout")]
    if failures:
        lines += ["", "## Failure output (last lines)"]
        for r in failures:
            lines += ["", f"### {r['kind']}: `{label(r)}`", "```", r["tail"] or "(no output)", "```"]
    touched = side_effects.get("modified", []) + side_effects.get("new", [])
    if touched:
        lines += ["", "## Files changed by the checks themselves (not by your edits)", ""]
        lines += [f"- {f}" + (" (restored)" if f in side_effects.get("restored", []) else "") for f in touched]
    (out / "VERIFICATION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("project")
    p.add_argument("--only", default="", help="comma-separated kinds to run")
    p.add_argument("--skip", default="", help="comma-separated kinds to skip")
    p.add_argument("--project", dest="subdirs", action="append", default=[],
                   help="only this subdirectory of a monorepo (repeatable)")
    p.add_argument("--timeout", type=int, default=600, help="per-step timeout in seconds")
    p.add_argument("--out", default="", help="report directory (default <project>/.verify)")
    p.add_argument("--env", action="append", default=[], metavar="KEY=VALUE",
                   help="environment variable for the steps (repeatable)")
    p.add_argument("--env-file", default="", help="KEY=VALUE file, for example .env.example")
    p.add_argument("--restore-side-effects", action="store_true",
                   help="undo edits that the checks themselves made to existing files "
                        "(for example next build rewriting tsconfig.json)")
    p.add_argument("--ignore-scripts", action="store_true",
                   help="install with --ignore-scripts so dependency install hooks do not run "
                        "(safer for code you do not fully trust; breaks packages that need a postinstall)")
    args = p.parse_args()

    root = Path(args.project).resolve()
    if not root.is_dir():
        sys.exit(f"Not a directory: {root}")
    try:
        extra_env = envutil.collect(args.env_file or None, args.env)
    except envutil.EnvError as e:
        sys.exit(f"ERROR  {e}")

    only = {k for k in args.only.split(",") if k}
    skip = {k for k in args.skip.split(",") if k}

    if len(find_projects(root)) > MAX_PROJECTS:
        print(f"NOTE  more than {MAX_PROJECTS} projects found; only the first {MAX_PROJECTS} are checked. "
              f"Use --project <subdir> to choose.")
    steps = detect(root, args.subdirs)
    if only:
        steps = [s for s in steps if s["kind"] in only]
    steps = [s for s in steps if s["kind"] not in skip]
    if args.ignore_scripts:
        for s in steps:
            if s["kind"] == "install" and s["stack"].startswith("node/"):
                s["cmd"] += " --ignore-scripts"
    if not steps:
        sys.exit("No verification steps detected. Run the code directly with a realistic input.")
    if extra_env:
        print(f"ENV   passing {len(extra_env)} variable(s): {', '.join(sorted(extra_env))}")

    before = take_snapshot(root)
    originals = read_originals(root, before) if args.restore_side_effects else None
    if args.restore_side_effects and originals is None:
        print("NOTE  project too large to keep originals; --restore-side-effects is disabled.")

    workspace = is_workspace_root(root)
    failed_installs: set[str] = set()
    results: list[dict] = []
    for step in steps:
        cwd = step.get("cwd", ".")
        if cwd in failed_installs or (workspace and "." in failed_installs):
            results.append({**step, "status": "skipped", "exit_code": None, "seconds": 0.0, "tail": ""})
            print(f"SKIP  {step['kind']:<10} {label(step)}  (install failed)")
            continue
        print(f"RUN   {step['kind']:<10} {label(step)}", flush=True)
        r = run_step(step, root, args.timeout, extra_env)
        results.append(r)
        print(f"{r['status'].upper():<5} {r['kind']:<10} {label(r)}  ({r['seconds']}s)")
        if r["status"] != "passed" and step["kind"] == "install":
            failed_installs.add(cwd)

    changes = snapshot_diff(root, before)
    side_effects = {"modified": changes["modified"], "new": changes["new"],
                    "deleted": changes["deleted"], "restored": []}
    if originals is not None:
        for rel in changes["modified"] + changes["deleted"]:
            if rel in originals:
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(originals[rel])
                side_effects["restored"].append(rel)

    out = Path(args.out).resolve() if args.out else root / ".verify"
    write_reports(results, root, out, side_effects)

    for key, text in (("modified", "MODIFIED"), ("new", "NEW"), ("deleted", "DELETED")):
        for rel in side_effects[key]:
            done = " (restored)" if rel in side_effects["restored"] else ""
            print(f"NOTE  checks changed files on their own: {text} {rel}{done}")

    bad = [r for r in results if r["status"] in ("failed", "timeout", "skipped")]
    ok = len(results) - len(bad)
    print(f"\n{ok}/{len(results)} steps passed. Report: {out / 'VERIFICATION.md'}")
    for r in bad:
        if r["status"] in ("failed", "timeout"):
            print(f"\n--- {r['kind']}: {label(r)} ({r['status']}) ---\n{r['tail']}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
