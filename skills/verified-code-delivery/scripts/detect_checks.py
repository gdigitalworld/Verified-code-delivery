#!/usr/bin/env python3
"""Detect a project's stack and list the verification steps that apply.

Usage:
  python detect_checks.py <project-dir> [--json] [--project <subdir> ...]

Steps come back in the order they should run:
install -> typecheck -> lint -> build -> test.

Monorepos are supported. Every directory (up to 3 levels deep) that holds a
package.json, pyproject.toml, requirements.txt, setup.py, Cargo.toml or go.mod
is treated as a project and its steps carry a "cwd" relative to the root.
In a JS workspace root (package.json "workspaces" or pnpm-workspace.yaml) the
install runs once at the root, and a kind the root already provides (for
example a turbo "build") is not repeated inside each package.
Other scripts (verify.py) import detect() from here.
"""
import argparse
import json
import os
import sys
from pathlib import Path

IGNORE_DIRS = {
    ".git", "node_modules", ".next", ".nuxt", ".turbo", ".cache", "dist", "build",
    "out", "coverage", "__pycache__", ".venv", "venv", "env", ".pytest_cache",
    ".mypy_cache", ".verify", ".svelte-kit", ".vercel", "target",
}
MARKERS = ("package.json", "pyproject.toml", "requirements.txt", "setup.py", "Cargo.toml", "go.mod")
MAX_DEPTH = 3
MAX_PROJECTS = 25
KIND_ORDER = ["install", "typecheck", "lint", "build", "test"]


def find_projects(root: Path, max_depth: int = MAX_DEPTH) -> list[Path]:
    root = Path(root).resolve()
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        depth = len(d.relative_to(root).parts)
        if depth < max_depth:
            dirnames[:] = sorted(n for n in dirnames if n not in IGNORE_DIRS and not (d / n).is_symlink())
        else:
            dirnames[:] = []
        if any(m in filenames for m in MARKERS):
            found.append(d)
    return sorted(found, key=lambda p: (len(p.relative_to(root).parts), str(p)))


def is_workspace_root(d: Path) -> bool:
    if (d / "pnpm-workspace.yaml").exists():
        return True
    pkg = d / "package.json"
    if pkg.exists():
        try:
            return "workspaces" in json.loads(pkg.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False
    return False


def package_manager(d: Path) -> str:
    if (d / "pnpm-lock.yaml").exists() or (d / "pnpm-workspace.yaml").exists():
        return "pnpm"
    if (d / "yarn.lock").exists():
        return "yarn"
    return "npm"


def _node_steps(d: Path, pm: str | None = None) -> list[dict]:
    try:
        pkg = json.loads((d / "package.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    scripts = pkg.get("scripts", {})
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}

    pm = pm or package_manager(d)
    install, run = {"pnpm": ("pnpm install", "pnpm run"),
                    "yarn": ("yarn install", "yarn run"),
                    "npm": ("npm install", "npm run")}[pm]

    stack = "node/" + pm
    steps = [{"stack": stack, "kind": "install", "cmd": install}]

    if "typecheck" in scripts:
        steps.append({"stack": stack, "kind": "typecheck", "cmd": f"{run} typecheck"})
    elif (d / "tsconfig.json").exists() and "typescript" in deps:
        steps.append({"stack": stack, "kind": "typecheck", "cmd": "npx --no-install tsc --noEmit"})

    if "lint" in scripts:
        steps.append({"stack": stack, "kind": "lint", "cmd": f"{run} lint"})
    if "build" in scripts:
        steps.append({"stack": stack, "kind": "build", "cmd": f"{run} build"})

    test_script = scripts.get("test", "")
    if test_script and "no test specified" not in test_script:
        steps.append({"stack": stack, "kind": "test", "cmd": f"{run} test"})
    elif "vitest" in deps:
        steps.append({"stack": stack, "kind": "test", "cmd": "npx --no-install vitest run"})
    elif "jest" in deps:
        steps.append({"stack": stack, "kind": "test", "cmd": "npx --no-install jest --ci"})
    return steps


def _python_steps(d: Path) -> list[dict]:
    stack = "python"
    steps = []
    if (d / "requirements.txt").exists():
        steps.append({"stack": stack, "kind": "install",
                      "cmd": "pip install -r requirements.txt --break-system-packages"})
    elif (d / "pyproject.toml").exists():
        steps.append({"stack": stack, "kind": "install",
                      "cmd": "pip install -e . --break-system-packages"})
    steps.append({"stack": stack, "kind": "typecheck", "cmd": "python -m compileall -q ."})

    text = ""
    for name in ("pyproject.toml", "setup.cfg", "tox.ini", "requirements.txt"):
        f = d / name
        if f.exists():
            text += f.read_text(encoding="utf-8", errors="ignore").lower()
    if "ruff" in text:
        steps.append({"stack": stack, "kind": "lint", "cmd": "ruff check ."})
    if "mypy" in text:
        steps.append({"stack": stack, "kind": "typecheck", "cmd": "mypy ."})
    if (d / "tests").exists() or (d / "test").exists() or "pytest" in text:
        steps.append({"stack": stack, "kind": "test", "cmd": "python -m pytest -q"})
    return steps


def _steps_for_dir(d: Path, pm: str | None = None) -> list[dict]:
    steps: list[dict] = []
    if (d / "package.json").exists():
        steps += _node_steps(d, pm)
    if any((d / n).exists() for n in ("pyproject.toml", "requirements.txt", "setup.py")):
        steps += _python_steps(d)
    if (d / "Cargo.toml").exists():
        steps += [
            {"stack": "rust", "kind": "build", "cmd": "cargo check"},
            {"stack": "rust", "kind": "test", "cmd": "cargo test"},
        ]
    if (d / "go.mod").exists():
        steps += [
            {"stack": "go", "kind": "build", "cmd": "go build ./..."},
            {"stack": "go", "kind": "lint", "cmd": "go vet ./..."},
            {"stack": "go", "kind": "test", "cmd": "go test ./..."},
        ]
    return steps


def detect(root: Path, only: list[str] | None = None) -> list[dict]:
    """Steps for the whole tree, each with a 'cwd' relative to root ('.' for the root)."""
    root = Path(root).resolve()
    projects = find_projects(root)[:MAX_PROJECTS]
    ws_root = root if is_workspace_root(root) else None

    root_kinds = {s["kind"] for s in _steps_for_dir(root)} if ws_root else set()
    ws_pm = package_manager(root) if ws_root else None  # packages use the workspace's package manager

    steps: list[dict] = []
    for proj in projects:
        rel = proj.relative_to(root).as_posix() or "."
        for s in _steps_for_dir(proj, ws_pm if proj != root else None):
            if ws_root and proj != root and s["stack"].startswith("node/"):
                if s["kind"] == "install" or s["kind"] in root_kinds:
                    continue  # installed once at the workspace root / root already runs this kind
            steps.append({**s, "cwd": rel})

    if only:
        wanted = [w.strip("/").removeprefix("./") or "." for w in only]
        keep_root_install = ws_root is not None and "." not in wanted
        steps = [s for s in steps
                 if any(s["cwd"] == w or s["cwd"].startswith(w + "/") for w in wanted)
                 # a workspace's packages need the root install even when only one is selected
                 or (keep_root_install and s["cwd"] == "." and s["kind"] == "install")]
    return steps


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("project")
    p.add_argument("--json", action="store_true")
    p.add_argument("--project", dest="only", action="append", default=[],
                   help="limit to a subdirectory (repeatable)")
    args = p.parse_args()

    root = Path(args.project)
    if not root.is_dir():
        sys.exit(f"Not a directory: {root}")
    steps = detect(root, args.only)
    if args.json:
        print(json.dumps(steps, indent=2))
    elif not steps:
        print("No known project files found. Run the code directly with a realistic input.")
    else:
        for s in steps:
            where = "" if s["cwd"] == "." else f"  (in {s['cwd']})"
            print(f"{s['kind']:<10} {s['cmd']}{where}    [{s['stack']}]")


if __name__ == "__main__":
    main()
