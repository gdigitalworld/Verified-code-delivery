#!/usr/bin/env python3
"""Validate and package the skill as a reproducible .skill (ZIP) file.

Usage:
  python tools/build_skill.py --check
  python tools/build_skill.py [--out dist]

The archive is deterministic: sorted entries, fixed timestamps and permissions,
no caches. Building the same source twice gives the same SHA-256, so a release
artifact can be independently rebuilt and compared.
"""
import argparse
import hashlib
import re
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO / "skills" / "verified-code-delivery"
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".verify"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}
FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def parse_frontmatter(text: str) -> dict[str, str]:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        raise ValueError("SKILL.md must start with a --- frontmatter block")
    fields = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return fields


def validate(skill_dir: Path) -> list[str]:
    errors = []
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return [f"missing {skill_md}"]
    try:
        fm = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
    except ValueError as e:
        return [str(e)]
    name, desc = fm.get("name", ""), fm.get("description", "")
    if name != skill_dir.name:
        errors.append(f"frontmatter name {name!r} must equal folder name {skill_dir.name!r}")
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) or len(name) > 64:
        errors.append("name must be kebab-case, at most 64 characters")
    if not desc:
        errors.append("description is required")
    elif len(desc) > 1024:
        errors.append(f"description is {len(desc)} characters, the limit is 1024")
    if "<" in desc or ">" in desc:
        errors.append("description must not contain angle brackets")
    for path in skill_dir.rglob("*"):
        if path.is_symlink():
            errors.append(f"symlinks are not allowed in the skill: {path.relative_to(skill_dir)}")
    return errors


def collect(skill_dir: Path) -> list[Path]:
    files = []
    for path in sorted(skill_dir.rglob("*"), key=lambda p: p.relative_to(skill_dir).as_posix()):
        rel = path.relative_to(skill_dir)
        if path.is_dir() or any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if path.suffix in EXCLUDE_SUFFIXES:
            continue
        files.append(path)
    return files


def build(skill_dir: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{skill_dir.name}.skill"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in collect(skill_dir):
            arcname = f"{skill_dir.name}/{path.relative_to(skill_dir).as_posix()}"
            info = zipfile.ZipInfo(arcname, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            is_script = path.suffix == ".py"
            info.external_attr = (0o755 if is_script else 0o644) << 16
            zf.writestr(info, path.read_bytes())
    return target


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true", help="validate only, build nothing")
    p.add_argument("--skill-dir", default=str(SKILL_DIR))
    p.add_argument("--out", default=str(REPO / "dist"))
    args = p.parse_args()

    skill_dir = Path(args.skill_dir).resolve()
    errors = validate(skill_dir)
    if errors:
        for e in errors:
            print(f"ERROR  {e}", file=sys.stderr)
        sys.exit(1)
    print(f"OK     {skill_dir.name} is valid")
    if args.check:
        return

    target = build(skill_dir, Path(args.out))
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (target.parent / f"{target.name}.sha256").write_text(f"{digest}  {target.name}\n", encoding="utf-8")
    print(f"BUILT  {target}")
    print(f"SHA256 {digest}")


if __name__ == "__main__":
    main()
