#!/usr/bin/env python3
"""Scan files for hardcoded secrets before code is delivered.

Usage:
  python secret_scan.py <dir-or-file> [more paths ...]

Flags API keys, private keys, tokens, Supabase service_role JWTs, committed
.env files, and generic key/secret/password assignments with literal values.
Matches are masked in the output. Exit code 1 if anything is found.
make_zip.py runs this automatically on the files it packs.
"""
import base64
import json
import re
import sys
from pathlib import Path

IGNORE_DIRS = {
    ".git", "node_modules", ".next", ".nuxt", ".turbo", ".cache", "dist", "build",
    "out", "coverage", "__pycache__", ".venv", "venv", ".pytest_cache", ".mypy_cache", ".verify",
}
SKIP_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Cargo.lock", "uv.lock",
}
SAFE_ENV_NAMES = {".env.example", ".env.sample", ".env.template", ".env.dist"}
MAX_BYTES = 1_000_000

PATTERNS = [
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("Stripe live key", re.compile(r"\b[sr]k_live_[0-9a-zA-Z]{20,}\b")),
    ("Razorpay live key", re.compile(r"\brzp_live_[A-Za-z0-9]{10,}\b")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b")),
    ("OpenAI API key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{40,}\b")),
    ("Private key block", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY")),
]
JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.(eyJ[A-Za-z0-9_\-]{10,})\.[A-Za-z0-9_\-]{10,}\b")
GENERIC_RE = re.compile(
    r"""(?ix)
    (api[_-]?key|secret|token|passwd|password|private[_-]?key|client[_-]?secret)
    ["']?\s*[:=]\s*
    ["']([^"'\s]{16,})["']
    """
)
PLACEHOLDER_HINTS = (
    "your", "xxx", "example", "changeme", "change_me", "placeholder", "dummy", "sample",
    "<", ">", "${", "{{", "process.env", "env.", "todo", "replace", "insert", "test_", "fake",
)


def mask(value: str) -> str:
    return value[:4] + "***" if len(value) > 8 else "***"


def jwt_finding(payload_b64: str) -> str | None:
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        return "JWT token"
    role = payload.get("role") if isinstance(payload, dict) else None
    if role == "service_role":
        return "Supabase service_role key"
    if role == "anon":
        return None  # public by design
    return "JWT token"


def scan_text(label: str, text: str) -> list[dict]:
    findings = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if len(line) > 2000:
            continue
        for kind, rx in PATTERNS:
            m = rx.search(line)
            if m:
                findings.append({"file": label, "line": lineno, "kind": kind, "preview": mask(m.group(0))})
        m = JWT_RE.search(line)
        if m:
            kind = jwt_finding(m.group(1))
            if kind:
                findings.append({"file": label, "line": lineno, "kind": kind, "preview": mask(m.group(0))})
        m = GENERIC_RE.search(line)
        if m:
            value = m.group(2)
            low = value.lower()
            if not any(h in low for h in PLACEHOLDER_HINTS) and len(set(value)) > 4:
                findings.append({"file": label, "line": lineno,
                                 "kind": f"hardcoded {m.group(1).lower()}", "preview": mask(value)})
    return findings


def scan_file(path: Path, label: str | None = None) -> list[dict]:
    label = label or str(path)
    if path.is_symlink():
        return []
    name = path.name
    if name.startswith(".env") and name not in SAFE_ENV_NAMES:
        return [{"file": label, "line": 0, "kind": "env file (should not be delivered)", "preview": name}]
    if name in SKIP_FILES:
        return []
    try:
        if path.stat().st_size > MAX_BYTES:
            return []
        raw = path.read_bytes()
    except OSError:
        return []
    if b"\x00" in raw[:4096]:
        return []  # binary
    return scan_text(label, raw.decode("utf-8", errors="ignore"))


def scan_paths(paths: list[Path]) -> list[dict]:
    findings = []
    for base in paths:
        if base.is_file():
            findings += scan_file(base, base.name)
            continue
        for f in sorted(base.rglob("*")):
            rel = f.relative_to(base)
            if any(part in IGNORE_DIRS for part in rel.parts) or f.is_symlink() or not f.is_file():
                continue
            findings += scan_file(f, str(rel))
    return findings


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("Usage: secret_scan.py <dir-or-file> [more paths ...]")
    paths = [Path(a).resolve() for a in sys.argv[1:]]
    for p in paths:
        if not p.exists():
            sys.exit(f"Not found: {p}")
    findings = scan_paths(paths)
    if not findings:
        print("PASS  no secrets found")
        return
    print(f"FAIL  {len(findings)} possible secret(s):")
    for f in findings:
        where = f"{f['file']}:{f['line']}" if f["line"] else f["file"]
        print(f"  {where}  {f['kind']}  ({f['preview']})")
    print("Move these to environment variables and reference them via process.env / os.environ.")
    sys.exit(1)


if __name__ == "__main__":
    main()
