# Threat model

The skill makes Claude run a project's checks before handing code over. The scripts run inside Claude's sandbox or on a developer's machine, against code Claude just wrote or code the user supplied.

## What the scripts do

| Script | Touches |
|---|---|
| `verify.py` | Runs the project's own install, typecheck, lint, build and test commands |
| `smoke_test.py` | Starts the app with a command you pass, then sends GET requests to `127.0.0.1` only |
| `check_imports.py`, `secret_scan.py`, `changed_files.py`, `detect_checks.py` | Read files inside the project directory |
| `make_zip.py` | Reads files inside the project directory, writes one ZIP |

No script sends data to the network except through the project's package manager (during install) and the loopback requests of `smoke_test.py`. There are no runtime dependencies: everything is Python standard library.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Running untrusted project code | Unavoidable for build and test. Run in a sandbox or container. Use `verify.py --ignore-scripts` so dependency install hooks do not run. |
| Command injection | Commands come from a fixed set built in `detect_checks.py`. File contents never become command text. For folders without a project file, `detect_checks.py` puts file names into syntax-check commands, always shell-quoted with `shlex.quote` (covered by a test). `--cmd` for the smoke test is an explicit argument from the caller. |
| Reading or packaging files outside the project (symlinks, `..`) | Symlinks are skipped by every scanner and refused by `make_zip.py`. Paths must resolve inside `--root`. Covered by tests. |
| Leaking secrets in a delivered ZIP | `make_zip.py` scans every file it packs and refuses to create the archive on a match. Output masks the matched value. |
| Fetching arbitrary URLs from a crafted `--path` | Paths must start with a single `/` and are always joined to `http://127.0.0.1:<port>`. |
| Hostile `.env.example` used with `--env-file` | Variables that change how code is loaded or fetched (`PATH`, `NODE_OPTIONS`, `LD_PRELOAD`, `PYTHONPATH`, package-manager registry settings) are refused. Values are never printed. Covered by tests. |
| Prompt injection from project files, logs or error text | The skill tells Claude to treat that text as data, never as instructions. |
| Oversized or hostile input files | Files over a size limit are skipped by the scanners. Python files are parsed with `ast`, never executed. |
| Compromised CI or release | Actions are pinned to commit SHAs and updated by Dependabot, workflows run with read-only permissions by default, releases are reproducible and carry a signed provenance attestation. |

## Non-goals

- This is not a malware sandbox. Running `verify.py` on hostile code is unsafe without your own isolation.
- The secret scanner is pattern-based. It will miss secrets with no recognisable shape.
- Native Windows is not tested. Use WSL.
