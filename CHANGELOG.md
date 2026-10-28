# Changelog

## 1.0.0 (unreleased)

First public release.

- Skill: run, build and test code in the sandbox before delivering it, then report honestly what was and was not verified.
- Scripts: `verify.py`, `smoke_test.py`, `check_imports.py`, `secret_scan.py`, `changed_files.py`, `make_zip.py`, `detect_checks.py`.
- Monorepo support: every project up to three levels deep is checked in its own folder; workspaces install once and use the workspace package manager; `--project` limits the scope.
- Environment variables for builds and smoke tests: `--env` and `--env-file`, with a filter for variables that change how code loads.
- Tool side effects: files that checks edit on their own (for example `next build` rewriting `tsconfig.json`) are reported, and `--restore-side-effects` undoes them. Failure output is stripped of colour codes.
- Security: symlinks are never followed, ZIP creation is blocked when secrets are found, `verify.py --ignore-scripts` for untrusted projects.
- Repository: tests, CI, CodeQL, pinned actions, reproducible builds with provenance attestation.
