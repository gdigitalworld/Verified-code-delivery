# Changelog

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
- `--project` is applied before the 25-project cap, so projects beyond the cap can be chosen.
- `check_imports.py` never reports a pass when it found no manifest: it prints `no manifest found, nothing checked` and exits with code 3.
- A missing toolchain (exit 127) is reported as MISSING TOOL, not as a code failure.
- ESLint is detected from its config file when a project has no `lint` script.
- Security: symlinks are never followed, ZIP creation is blocked when secrets are found, `verify.py --ignore-scripts` for untrusted projects.
- Repository: tests, CI, CodeQL, pinned actions, reproducible builds with provenance attestation.
