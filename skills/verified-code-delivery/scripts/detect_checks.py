#!/usr/bin/env python3
"""Detect a project's stack and list the verification steps that apply.

Usage:
  python detect_checks.py <project-dir> [--json] [--project <subdir> ...]

Steps come back in the order they should run:
install -> typecheck -> lint -> build -> test.

Monorepos are supported. Every directory (up to 3 levels deep) that holds a
package.json, pyproject.toml, requirements.txt, setup.py, Cargo.toml, go.mod, pom.xml,\nbuild.gradle, *.csproj, composer.json, Gemfile, mix.exs, pubspec.yaml, Package.swift,\nCMakeLists.txt, Makefile or deno.json is treated as a project and its steps carry a "cwd" relative to the root.
A folder with no project file at all falls back to one syntax check per source file
(Python, JS, shell, PHP, Ruby, Perl, Go, C/C++, Java, Rust, Swift, JSON), kind "syntax".
In a JS workspace root (package.json "workspaces" or pnpm-workspace.yaml) the
install runs once at the root, and a kind the root already provides (for
example a turbo "build") is not repeated inside each package.
Other scripts (verify.py) import detect() from here.
"""
import argparse
import json
import os
import re
import shlex
import shutil
import sys
from pathlib import Path

# Many systems (macOS, minimal Ubuntu) only have python3, so use whichever exists.
PY = "python" if shutil.which("python") else ("python3" if shutil.which("python3") else "python")

IGNORE_DIRS = {
    ".git", "node_modules", ".next", ".nuxt", ".turbo", ".cache", "dist", "build",
    "out", "coverage", "__pycache__", ".venv", "venv", "env", ".pytest_cache",
    ".mypy_cache", ".verify", ".svelte-kit", ".vercel", "target",
}
MARKERS = (
    "package.json", "pyproject.toml", "requirements.txt", "setup.py", "Cargo.toml", "go.mod",
    "pom.xml", "build.gradle", "build.gradle.kts", "composer.json", "Gemfile", "mix.exs",
    "pubspec.yaml", "Package.swift", "CMakeLists.txt", "Makefile", "deno.json", "deno.jsonc",
)
MARKER_SUFFIXES = (".csproj", ".fsproj", ".sln")
MAX_LOOSE_FILES = 40
# Single files with no project file: a syntax check per language. {f} is shell-quoted.
LOOSE_SYNTAX = {
    ".py": PY + " -m py_compile {f}",
    ".js": "node --check {f}", ".mjs": "node --check {f}", ".cjs": "node --check {f}",
    ".sh": "bash -n {f}", ".bash": "bash -n {f}",
    ".php": "php -l {f}",
    ".rb": "ruby -c {f}",
    ".pl": "perl -c {f}",
    ".go": "gofmt -e -l {f}",
    ".c": "gcc -fsyntax-only {f}",
    ".cpp": "g++ -fsyntax-only {f}", ".cc": "g++ -fsyntax-only {f}",
    ".java": 'javac -proc:none -d "$(mktemp -d)" {f}',
    ".rs": 'rustc --crate-type lib --emit=metadata --out-dir "$(mktemp -d)" {f}',
    ".swift": "swiftc -parse {f}",
    ".json": PY + " -m json.tool {f} > /dev/null",
}
MAX_DEPTH = 3
MAX_PROJECTS = 25
KIND_ORDER = ["install", "typecheck", "lint", "build", "test"]
COMPILEALL_CMD = (
    PY + r' -m compileall -q -x "(^|[/\\\\])(node_modules|[.]venv|venv|env|[.]git|dist|build|[.]next|'
    r'[.]nuxt|[.]turbo|[.]cache|target|[.]verify|[.]svelte-kit|[.]vercel|[.]tox|site-packages)([/\\\\]|$)" .'
)


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
        if any(m in filenames for m in MARKERS) or any(f.endswith(MARKER_SUFFIXES) for f in filenames):
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


def _has_eslint_config(d: Path) -> bool:
    legacy = (".eslintrc", ".eslintrc.json", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.yml", ".eslintrc.yaml")
    return any(d.glob("eslint.config.*")) or any((d / n).exists() for n in legacy)


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
    elif "eslint" in deps and _has_eslint_config(d):
        steps.append({"stack": stack, "kind": "lint", "cmd": "npx --no-install eslint ."})
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
                      "cmd": f"{PY} -m pip install -r requirements.txt --break-system-packages"})
    elif (d / "pyproject.toml").exists():
        steps.append({"stack": stack, "kind": "install",
                      "cmd": f"{PY} -m pip install -e . --break-system-packages"})
    # Skip dependency and build folders: node_modules and .venv hold other people's .py files
    # (some with Python 2 syntax) that would fail the check for code that is fine.
    steps.append({"stack": stack, "kind": "typecheck", "cmd": COMPILEALL_CMD})

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
        steps.append({"stack": stack, "kind": "test", "cmd": f"{PY} -m pytest -q"})
    return steps


def _read(d: Path, name: str) -> str:
    try:
        return (d / name).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _other_stack_steps(d: Path) -> list[dict]:
    """Java, .NET, PHP, Ruby, Elixir, Dart/Flutter, Swift, C/C++, Deno."""
    steps: list[dict] = []

    def add(stack: str, kind: str, cmd: str) -> None:
        steps.append({"stack": stack, "kind": kind, "cmd": cmd})

    if (d / "pom.xml").exists():
        mvn = "./mvnw" if (d / "mvnw").exists() else "mvn"
        add("java/maven", "build", f"{mvn} -B -q -DskipTests package")
        add("java/maven", "test", f"{mvn} -B -q test")
    if (d / "build.gradle").exists() or (d / "build.gradle.kts").exists():
        gr = "./gradlew" if (d / "gradlew").exists() else "gradle"
        add("java/gradle", "build", f"{gr} --console=plain -q build -x test")
        add("java/gradle", "test", f"{gr} --console=plain -q test")
    if any(d.glob("*.csproj")) or any(d.glob("*.fsproj")) or any(d.glob("*.sln")):
        add("dotnet", "build", "dotnet build --nologo -v q")
        add("dotnet", "test", "dotnet test --nologo -v q")
    if (d / "composer.json").exists():
        add("php", "install", "composer install --no-interaction")
        try:
            scripts = json.loads(_read(d, "composer.json") or "{}").get("scripts", {})
        except json.JSONDecodeError:
            scripts = {}
        if "test" in scripts:
            add("php", "test", "composer test")
        elif (d / "phpunit.xml").exists() or (d / "phpunit.xml.dist").exists():
            add("php", "test", "vendor/bin/phpunit")
    if (d / "Gemfile").exists():
        add("ruby", "install", "bundle install")
        if (d / "spec").is_dir():
            add("ruby", "test", "bundle exec rspec")
        elif (d / "test").is_dir() or (d / "Rakefile").exists():
            add("ruby", "test", "bundle exec rake test")
    if (d / "mix.exs").exists():
        add("elixir", "install", "mix deps.get")
        add("elixir", "build", "mix compile")
        add("elixir", "test", "mix test")
    if (d / "pubspec.yaml").exists():
        tool = "flutter" if re.search(r"^\s*flutter\s*:", _read(d, "pubspec.yaml"), re.MULTILINE) else "dart"
        add(tool, "install", f"{tool} pub get")
        add(tool, "lint", f"{tool} analyze")
        if (d / "test").is_dir():
            add(tool, "test", f"{tool} test")
    if (d / "Package.swift").exists():
        add("swift", "build", "swift build")
        add("swift", "test", "swift test")
    if (d / "CMakeLists.txt").exists():
        add("cmake", "build", "cmake -S . -B build && cmake --build build")
        if re.search(r"enable_testing|add_test", _read(d, "CMakeLists.txt"), re.IGNORECASE):
            add("cmake", "test", "ctest --test-dir build --output-on-failure")
    if (d / "deno.json").exists() or (d / "deno.jsonc").exists():
        add("deno", "lint", "deno lint")
        add("deno", "test", "deno test")
    return steps


def _make_steps(d: Path) -> list[dict]:
    """A Makefile is used only when it defines the target and nothing else covers the folder."""
    text = _read(d, "Makefile")
    steps = []
    for kind, target in (("build", "build"), ("lint", "lint"), ("test", "test"), ("test", "check")):
        if re.search(rf"^{target}\s*:", text, re.MULTILINE) and not (kind == "test" and steps and steps[-1]["kind"] == "test"):
            steps.append({"stack": "make", "kind": kind, "cmd": f"make {target}"})
    return steps


def loose_file_steps(root: Path) -> list[dict]:
    """Syntax checks for source files when the folder has no project file at all."""
    root = Path(root).resolve()
    steps: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        depth = len(d.relative_to(root).parts)
        dirnames[:] = sorted(n for n in dirnames if n not in IGNORE_DIRS and not (d / n).is_symlink()) if depth < MAX_DEPTH else []
        for name in sorted(filenames):
            f = d / name
            tpl = LOOSE_SYNTAX.get(f.suffix.lower())
            if not tpl or f.is_symlink() or not f.is_file():
                continue
            rel = f.relative_to(root).as_posix()
            steps.append({"stack": "files", "kind": "syntax", "cwd": ".", "cmd": tpl.format(f=shlex.quote(rel))})
            if len(steps) >= MAX_LOOSE_FILES:
                return steps
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
    steps += _other_stack_steps(d)
    if not steps:
        steps += _make_steps(d)
    return steps


def detect(root: Path, only: list[str] | None = None) -> list[dict]:
    """Steps for the whole tree, each with a 'cwd' relative to root ('.' for the root)."""
    root = Path(root).resolve()
    wanted = [w.strip("/").removeprefix("./") or "." for w in only or []]

    def chosen(p: Path) -> bool:
        rel = p.relative_to(root).as_posix() or "."
        # the root stays in so a workspace can still run its single install
        return not wanted or p == root or any(rel == w or rel.startswith(w + "/") for w in wanted)

    # Filter first, then cap: --project must be able to reach a project beyond the cap.
    projects = [p for p in find_projects(root) if chosen(p)][:MAX_PROJECTS]
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

    if not steps and not wanted:
        steps = loose_file_steps(root)  # no project file anywhere: at least syntax-check each file

    if only:
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
        print("No project files or known source files found. Run the code directly with a realistic input.")
    else:
        for s in steps:
            where = "" if s["cwd"] == "." else f"  (in {s['cwd']})"
            print(f"{s['kind']:<10} {s['cmd']}{where}    [{s['stack']}]")


if __name__ == "__main__":
    main()
