#!/usr/bin/env python3
"""Find imported packages that are missing from the dependency manifest.

Usage:
  python check_imports.py <project-dir>

JS/TS: every bare import (not relative, not a Node builtin, not a tsconfig
path alias) must appear in package.json dependencies/devDependencies/peer/optional.
Python: every third-party import must appear in requirements*.txt or pyproject.toml.
This is the most common bug in generated code: it imports a package it forgot
to add, and everything works until the user runs a clean install.
Exit code 1 if anything is missing, 3 if no manifest was found and nothing could be checked
(never read that as a pass).
"""
import ast
import json
import re
import sys
from pathlib import Path

IGNORE_DIRS = {
    ".git", "node_modules", ".next", ".nuxt", ".turbo", ".cache", "dist", "build",
    "out", "coverage", "__pycache__", ".venv", "venv", "env", ".pytest_cache",
    ".mypy_cache", ".verify", ".svelte-kit",
}

NODE_BUILTINS = {
    "assert", "async_hooks", "buffer", "child_process", "cluster", "console", "constants",
    "crypto", "dgram", "diagnostics_channel", "dns", "domain", "events", "fs", "http",
    "http2", "https", "inspector", "module", "net", "os", "path", "perf_hooks", "process",
    "punycode", "querystring", "readline", "repl", "stream", "string_decoder", "sys",
    "timers", "tls", "trace_events", "tty", "url", "util", "v8", "vm", "wasi",
    "worker_threads", "zlib", "test",
}

MAX_BYTES = 2_000_000  # skip huge generated/minified files

JS_EXT = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}

JS_IMPORT_RE = re.compile(
    r"""(?:\bfrom\s*|\bimport\s*\(\s*|\brequire\s*\(\s*|^\s*import\s+)['"]([^'"\n]+)['"]""",
    re.MULTILINE,
)

# import name -> distribution name(s) when they differ
PY_IMPORT_TO_DIST = {
    "PIL": ["pillow"], "yaml": ["pyyaml"], "cv2": ["opencv-python", "opencv-python-headless", "opencv-contrib-python"],
    "sklearn": ["scikit-learn"], "skimage": ["scikit-image"], "bs4": ["beautifulsoup4"],
    "dotenv": ["python-dotenv"], "jwt": ["pyjwt"], "dateutil": ["python-dateutil"],
    "attr": ["attrs"], "serial": ["pyserial"], "magic": ["python-magic"],
    "OpenSSL": ["pyopenssl"], "Crypto": ["pycryptodome", "pycryptodomex"],
    "fitz": ["pymupdf"], "docx": ["python-docx"], "pptx": ["python-pptx"],
    "psycopg2": ["psycopg2", "psycopg2-binary"], "MySQLdb": ["mysqlclient"],
    "git": ["gitpython"], "socketio": ["python-socketio"], "multipart": ["python-multipart"],
    "jose": ["python-jose"], "flask_cors": ["flask-cors"], "flask_sqlalchemy": ["flask-sqlalchemy"],
    "googleapiclient": ["google-api-python-client"], "google": None,  # namespace package: skip
    "yt_dlp": ["yt-dlp"], "razorpay": ["razorpay"], "supabase": ["supabase"],
}


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.strip().lower())


def walk(root: Path, exts: set[str]):
    for path in root.rglob("*"):
        if any(part in IGNORE_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_symlink() or not path.is_file() or path.suffix not in exts:
            continue
        if path.stat().st_size > MAX_BYTES:
            continue
        yield path


# ---------------------------------------------------------------- JS / TS
def load_json_loose(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="ignore")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"(^|[^:\"'])//.*$", r"\1", text, flags=re.MULTILINE)
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def package_jsons(root: Path) -> list[Path]:
    return [f for f in walk(root, {".json"}) if f.name == "package.json"]


def declared_in(pkg_path: Path) -> tuple[set[str], str]:
    try:
        pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set(), ""
    names = set()
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        names |= set(pkg.get(key, {}))
    return names, pkg.get("name", "")


def check_node(root: Path) -> list[str]:
    """Each file may import what its nearest package.json declares, what the root declares
    (workspace hoisting), and the names of the repo's own workspace packages."""
    manifests = {f.parent: declared_in(f) for f in package_jsons(root)}
    workspace_names = {name for _, name in manifests.values() if name}
    root_declared = manifests.get(root, (set(), ""))[0]

    alias_prefixes = {"@/", "~/", "#"}
    for cfg_dir in list(manifests) or [root]:
        for cfg in ("tsconfig.json", "jsconfig.json"):
            f = cfg_dir / cfg
            if f.exists():
                paths = load_json_loose(f).get("compilerOptions", {}).get("paths", {})
                for key in paths:
                    alias_prefixes.add(key.rstrip("*"))

    problems = []
    for path in walk(root, JS_EXT):
        owner = next((d for d in [path.parent, *path.parent.parents]
                      if d in manifests or d == root), root)
        if root not in owner.parents and owner != root:
            owner = root
        allowed = manifests.get(owner, (set(), ""))[0] | root_declared | workspace_names
        manifest_name = "package.json" if owner == root else f"{owner.relative_to(root).as_posix()}/package.json"
        text = path.read_text(encoding="utf-8", errors="ignore")
        for m in JS_IMPORT_RE.finditer(text):
            spec = m.group(1)
            if spec.startswith((".", "/", "node:", "data:", "http")):
                continue
            if any(spec.startswith(a) for a in alias_prefixes if a):
                continue
            parts = spec.split("/")
            name = "/".join(parts[:2]) if spec.startswith("@") else parts[0]
            if name in NODE_BUILTINS or name in allowed:
                continue
            line = text.count("\n", 0, m.start()) + 1
            problems.append(f"{path.relative_to(root).as_posix()}:{line} imports '{name}' but it is not in {manifest_name}")
    return sorted(set(problems))


# ----------------------------------------------------------------- Python
def manifest_dirs(root: Path) -> list[Path]:
    dirs = set()
    for f in walk(root, {".txt", ".toml"}):
        if f.name.startswith("requirements") or f.name == "pyproject.toml":
            dirs.add(f.parent)
    return sorted(dirs)


def python_declared(root: Path) -> set[str] | None:
    declared: set[str] = set()
    found = False
    reqs = [f for f in walk(root, {".txt"}) if f.name.startswith("requirements")]
    for req in reqs:
        found = True
        for line in req.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.split("#")[0].strip()
            if not line or line.startswith(("-", "git+", "http")):
                continue
            declared.add(norm(re.split(r"[<>=!~;\[ ]", line)[0]))
    for pyproject in (f for f in walk(root, {".toml"}) if f.name == "pyproject.toml"):
        found = True
        try:
            import tomllib
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        proj = data.get("project", {})
        specs = list(proj.get("dependencies", []))
        for group in proj.get("optional-dependencies", {}).values():
            specs += group
        for spec in specs:
            declared.add(norm(re.split(r"[<>=!~;\[ ]", spec)[0]))
        poetry = data.get("tool", {}).get("poetry", {})
        declared |= {norm(k) for k in poetry.get("dependencies", {})}
        for grp in poetry.get("group", {}).values():
            declared |= {norm(k) for k in grp.get("dependencies", {})}
    return declared if found else None


def local_python_modules(root: Path) -> set[str]:
    names = set()
    bases = {root, root / "src"}
    for d in manifest_dirs(root):
        bases |= {d, d / "src"}
    for py in walk(root, {".py"}):
        bases.add(py.parent)
    for base in bases:
        if not base.is_dir():
            continue
        for child in base.iterdir():
            if child.is_dir() and child.name not in IGNORE_DIRS:
                names.add(child.name)
            elif child.suffix == ".py":
                names.add(child.stem)
    return names


PY_IMPORT_RE = re.compile(r"^\s*(?:import\s+([A-Za-z_][\w.]*(?:\s*,\s*[A-Za-z_][\w.]*)*)|from\s+([A-Za-z_][\w.]*)\s+import\b)", re.MULTILINE)


def regex_imports(text: str) -> list[tuple[str, int]]:
    """Fallback for files that do not parse: best-effort import names with line numbers."""
    found = []
    for m in PY_IMPORT_RE.finditer(text):
        line = text.count("\n", 0, m.start()) + 1
        for mod in (m.group(1) or m.group(2)).split(","):
            found.append((mod.strip().split(".")[0], line))
    return found


def check_python(root: Path) -> tuple[list[str], str | None]:
    declared = python_declared(root)
    local = local_python_modules(root)
    stdlib = set(sys.stdlib_module_names)
    problems = []
    for path in walk(root, {".py"}):
        text = path.read_text(encoding="utf-8", errors="ignore")
        try:
            tree = ast.parse(text)
            names_by_node = None
        except SyntaxError as e:
            problems.append(f"{path.relative_to(root).as_posix()}:{e.lineno} syntax error: {e.msg}")
            tree, names_by_node = None, regex_imports(text)  # still check this file's imports
        for node in (ast.walk(tree) if tree else [None]):
            if tree is None:
                names = names_by_node
            elif isinstance(node, ast.Import):
                names = [(a.name.split(".")[0], node.lineno) for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [(node.module.split(".")[0], node.lineno)]
            else:
                continue
            for name, lineno in names:
                if name in stdlib or name in local or name == "__future__":
                    continue
                if declared is None:
                    continue
                dists = PY_IMPORT_TO_DIST.get(name, [name])
                if dists is None:
                    continue
                if not any(norm(d) in declared for d in dists):
                    problems.append(
                        f"{path.relative_to(root).as_posix()}:{lineno} imports '{name}' but "
                        f"'{dists[0]}' is not in requirements/pyproject"
                    )
    note = None
    if declared is None and any(walk(root, {".py"})):
        note = "No requirements.txt or pyproject.toml found, so Python imports were not checked."
    return sorted(set(problems)), note


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage: check_imports.py <project-dir>")
    root = Path(sys.argv[1]).resolve()
    if not root.is_dir():
        sys.exit(f"Not a directory: {root}")

    problems: list[str] = []
    notes: list[str] = []   # things that were NOT checked
    checked = False         # did at least one language actually get checked?

    has_js = any(True for _ in walk(root, JS_EXT))
    if package_jsons(root):
        problems += check_node(root)
        checked = True
    elif has_js:
        notes.append("JS/TS files found but no package.json, so their imports were not checked.")

    has_py = any(True for _ in walk(root, {".py"}))
    py_problems, py_note = check_python(root)
    problems += py_problems
    if py_note:
        notes.append(py_note)
    elif has_py:
        checked = True

    for n in notes:
        print(f"NOTE  {n}")
    if problems:
        syntax = sum("syntax error:" in p for p in problems)
        detail = f"{len(problems) - syntax} undeclared import(s)" + (f", {syntax} syntax error(s)" if syntax else "")
        print(f"FAIL  {len(problems)} problem(s): {detail}")
        for p in problems:
            print(f"  {p}")
        sys.exit(1)
    if notes and not checked:
        # Exit code 3 = nothing was checked. Never report this as a pass.
        print("NOTE  no manifest found, nothing checked")
        sys.exit(3)
    if notes:
        print("PASS  every import that could be checked is declared (see the NOTE lines for what was skipped)")
        return
    print("PASS  every import is declared in the dependency manifest")

if __name__ == "__main__":
    main()
