# Changelog

## 1.2.0 (2026-10-30)

The skill now covers any language and any kind of coding task, and always verifies the specific thing that was asked for.

- `SKILL.md`: new section "Verify the task itself, in any language". Every request needs a stated acceptance check that is run for real (project tests, or a small test or script with realistic input including an edge case). A green build alone no longer counts as verified.
- `detect_checks.py` / `verify.py` now detect Java (Maven, Gradle, wrappers), .NET, PHP (Composer), Ruby (Bundler), Elixir, Dart and Flutter, Swift, C/C++ (CMake), Deno and Makefile targets, besides Node, Python, Go and Rust.
- A folder with no project file gets one syntax check per source file (Python, JS, shell, PHP, Ruby, Perl, Go, C/C++, Java, Rust, Swift, JSON) instead of "no steps". File names are shell-quoted, so an odd name cannot inject a command.
- Editor warnings cleaned up: `pyrightconfig.json` makes VS Code (Pylance) resolve the script imports in `tests/`, process-group calls are guarded with `sys.platform` so Windows type checking is clean, and a few loose type hints were fixed. Pyright reports 0 errors on Windows, Linux and macOS settings.
- The description of the skill names the languages it covers; trigger queries for Java, Go, PHP and shell were added.
- Landing page (`docs/index.html`): header is now sticky with a solid background, respects phone safe areas, anchor links no longer hide under it, and the menu scrolls instead of wrapping badly on small screens. The page lists the new languages.
- The Python syntax check (`compileall`) no longer walks `node_modules`, `.venv`, `site-packages`, build output and caches, so a foreign Python 2 file inside `node_modules` cannot fail good code.
- `python -m <tool>` with the tool not installed (for example `No module named pytest`) is reported as MISSING TOOL, not as a code failure.
- Python commands use `python3` when the machine has no `python` (macOS, minimal Ubuntu), and `pip` runs as `<python> -m pip`.
- A step that times out now stops the whole process tree. Before, a child such as a dev server could keep the output open and make `verify.py` wait long after the timeout.

## 1.1.0 (2026-10-30)

Fixes for false greens and a few gaps found while testing the skill on real projects.

- `check_imports.py` never reports a pass when it found no manifest: it prints `no manifest found, nothing checked` and exits with code 3. Python files without a `requirements.txt` or `pyproject.toml` now exit 3 instead of 0, so scripts that treated that case as a pass need updating.
- `--project` is applied before the 25-project cap, so projects beyond the cap can be chosen.
- A missing toolchain (exit 127) is reported as MISSING TOOL, not as a code failure.
- ESLint is detected from its config file when a project has no `lint` script.
- `SKILL.md` explains exit code 3 and MISSING TOOL, and says that `--project` works beyond the cap.

## 1.0.0 (2026-10-29)

First public release.

- Skill: run, build and test code in the sandbox before delivering it, then report honestly what was and was not verified.
- Scripts: `verify.py`, `smoke_test.py`, `check_imports.py`, `secret_scan.py`, `changed_files.py`, `make_zip.py`, `detect_checks.py`.
- Monorepo support: every project up to three levels deep is checked in its own folder; workspaces install once and use the workspace package manager; `--project` limits the scope and still runs the workspace root install.
- Environment variables for builds and smoke tests: `--env` and `--env-file`, with a filter for variables that change how code loads.
- Tool side effects: files that checks edit on their own (for example `next build` rewriting `tsconfig.json`) are reported, and `--restore-side-effects` undoes them. Failure output is stripped of colour codes.
- Failure reports show failing test assertions (TAP `not ok` blocks) first, so they are not buried in a long log.
- `check_imports.py` keeps checking imports in files that have a syntax error and reports both kinds of problem in its heading.
- Windows: `smoke_test.py` ends the whole process tree and tolerates a locked log file, messages always use `/` in paths, the `.skill` archive order no longer depends on the OS, and symlink tests skip where symlinks are not allowed.
- Landing page in `docs/index.html`, published by GitHub Pages straight from the branch (no workflow). `docs/_config.yml` keeps the maintainer docs out of the site.
- Security: symlinks are never followed, ZIP creation is blocked when secrets are found, `verify.py --ignore-scripts` for untrusted projects.
- Repository: tests, CI, CodeQL, pinned actions, reproducible builds with provenance attestation.
