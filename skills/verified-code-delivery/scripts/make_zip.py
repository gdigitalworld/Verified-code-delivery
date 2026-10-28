#!/usr/bin/env python3
"""Build a ZIP of selected files, preserving repo-relative paths.

Usage:
  python make_zip.py --root <project-dir> --out <file.zip> [--since <snapshot.json>]
                     [--exclude <glob> ...] [<file> ...]

Files come from the explicit list, from --since (every new or modified file
since the snapshot from changed_files.py), or both. Paths inside the ZIP are
relative to --root, so the user can unzip straight over their repo.

Safety gate: the selected files are scanned for hardcoded secrets first.
If anything is found the ZIP is NOT created (override with --allow-secrets).
Deleted files can't be shipped in a ZIP, so they are listed for the user.
"""
import argparse
import fnmatch
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from changed_files import diff  # noqa: E402
from secret_scan import scan_file  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--since", help="snapshot.json from changed_files.py snapshot")
    p.add_argument("--exclude", action="append", default=[], help="glob to leave out (repeatable)")
    p.add_argument("--allow-secrets", action="store_true")
    p.add_argument("files", nargs="*")
    args = p.parse_args()

    root = Path(args.root).resolve()
    out = Path(args.out).resolve()
    if not args.files and not args.since:
        sys.exit("Give files to include, or --since <snapshot.json> to auto-detect changes.")

    rels: list[str] = []
    deleted: list[str] = []
    if args.since:
        snap = json.loads(Path(args.since).read_text(encoding="utf-8"))
        d = diff(root, snap)
        rels += d["new"] + d["modified"]
        deleted = d["deleted"]

    missing, outside = [], []
    for f in args.files:
        raw = Path(f)
        raw = raw if raw.is_absolute() else root / raw
        if raw.is_symlink():
            sys.exit(f"Refusing to ZIP a symlink (it could point outside the project): {f}")
        path = raw.resolve()
        if not path.is_file():
            missing.append(f)
            continue
        try:
            rels.append(path.relative_to(root).as_posix())
        except ValueError:
            outside.append(f)
    if missing or outside:
        if missing:
            print("Missing files:", ", ".join(missing), file=sys.stderr)
        if outside:
            print("Outside --root:", ", ".join(outside), file=sys.stderr)
        sys.exit(1)

    rels = sorted({r for r in rels if not any(fnmatch.fnmatch(r, g) for g in args.exclude)})
    if not rels:
        sys.exit("Nothing to ZIP: no changed files found.")

    findings = []
    for rel in rels:
        findings += scan_file(root / rel, rel)
    if findings and not args.allow_secrets:
        print("BLOCKED  possible secrets found, ZIP not created:", file=sys.stderr)
        for f in findings:
            where = f"{f['file']}:{f['line']}" if f["line"] else f["file"]
            print(f"  {where}  {f['kind']}  ({f['preview']})", file=sys.stderr)
        sys.exit(2)

    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in rels:
            zf.write(root / rel, rel)

    print(f"Created {out} with {len(rels)} file(s):")
    for rel in rels:
        print(f"  {rel}")
    if deleted:
        print("\nDeleted since the snapshot (a ZIP can't delete files, tell the user to remove them):")
        for rel in deleted:
            print(f"  {rel}")


if __name__ == "__main__":
    main()
