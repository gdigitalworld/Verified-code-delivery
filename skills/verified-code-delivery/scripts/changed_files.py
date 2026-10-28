#!/usr/bin/env python3
"""Detect which files actually changed, by comparing content hashes.

Usage:
  python changed_files.py snapshot <project-dir> --out <snapshot.json>
  python changed_files.py diff     <project-dir> --snapshot <snapshot.json> [--json]

Take the snapshot right after placing the user's original files in the project
and BEFORE editing anything. Later, diff reports new, modified and deleted files,
so only those go into the ZIP.

Ignored by default: dependency and build folders, caches, generated files
(next-env.d.ts, *.tsbuildinfo) and lockfiles. Use --include-lockfiles to keep
lockfiles in the comparison.
"""
import argparse
import fnmatch
import hashlib
import json
import sys
from pathlib import Path

IGNORE_DIRS = {
    ".git", "node_modules", ".next", ".nuxt", ".turbo", ".cache", "dist", "build",
    "out", "coverage", "__pycache__", ".venv", "venv", "env", ".pytest_cache",
    ".mypy_cache", ".verify", ".svelte-kit", ".vercel", ".ruff_cache", ".nyc_output", "htmlcov",
}
IGNORE_FILE_GLOBS = ["*.pyc", "*.tsbuildinfo", ".DS_Store", "next-env.d.ts", "*.log", ".eslintcache", ".coverage"]
LOCKFILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Cargo.lock", "uv.lock", "bun.lockb"}


def iter_files(root: Path, include_lockfiles: bool = False):
    ignore_dirs = set(IGNORE_DIRS)
    if (root / "Cargo.toml").exists():
        ignore_dirs.add("target")
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue  # never follow symlinks: they can point outside the project
        rel = path.relative_to(root)
        if any(part in ignore_dirs for part in rel.parts[:-1]):
            continue
        if any(fnmatch.fnmatch(path.name, g) for g in IGNORE_FILE_GLOBS):
            continue
        if not include_lockfiles and path.name in LOCKFILES:
            continue
        yield path, rel.as_posix()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def take_snapshot(root: Path, include_lockfiles: bool = False) -> dict[str, str]:
    return {rel: sha256(p) for p, rel in iter_files(root, include_lockfiles)}


def diff(root: Path, snapshot: dict[str, str], include_lockfiles: bool = False) -> dict[str, list[str]]:
    now = take_snapshot(root, include_lockfiles)
    return {
        "new": sorted(set(now) - set(snapshot)),
        "modified": sorted(r for r in now if r in snapshot and now[r] != snapshot[r]),
        "deleted": sorted(set(snapshot) - set(now)),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot")
    s.add_argument("project")
    s.add_argument("--out", required=True)
    s.add_argument("--include-lockfiles", action="store_true")
    d = sub.add_parser("diff")
    d.add_argument("project")
    d.add_argument("--snapshot", required=True)
    d.add_argument("--json", action="store_true")
    d.add_argument("--include-lockfiles", action="store_true")
    args = p.parse_args()

    root = Path(args.project).resolve()
    if not root.is_dir():
        sys.exit(f"Not a directory: {root}")

    if args.cmd == "snapshot":
        snap = take_snapshot(root, args.include_lockfiles)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(snap, indent=2), encoding="utf-8")
        print(f"Snapshot of {len(snap)} file(s) saved to {args.out}")
        return

    snap = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    result = diff(root, snap, args.include_lockfiles)
    if args.json:
        print(json.dumps(result, indent=2))
        return
    for label in ("new", "modified", "deleted"):
        for rel in result[label]:
            print(f"{label.upper():<9} {rel}")
    total = sum(len(v) for v in result.values())
    if not total:
        print("No changes since snapshot.")


if __name__ == "__main__":
    main()
