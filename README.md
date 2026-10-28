# verified-code-delivery

A skill for Claude that makes it **run, build and test code before handing it to you**, fix what breaks, and finish with an honest note on what was and was not verified.

Without it, generated code often arrives with a missing import, a type error, a crash on startup or a leaked key, and you find out when you run it. With it, Claude proves the code works in its sandbox first, using scripts whose exit codes and logs back every claim.

## What it does

1. Detects the stack (Node, Python, Rust, Go), including monorepos and workspaces, and runs install, typecheck, lint, build and tests in each project (`verify.py`). Placeholder env vars can be passed with `--env-file .env.example`, and edits that tools make to your files on their own (like `next build` rewriting `tsconfig.json`) are reported and can be undone.
2. Checks that every import is declared in `package.json` / `requirements.txt` / `pyproject.toml` (`check_imports.py`)
3. Starts the app for real and hits its endpoints (`smoke_test.py`)
4. Scans for hardcoded keys, tokens and `.env` files (`secret_scan.py`)
5. Works out exactly which files changed (`changed_files.py`) and ZIPs only those, with correct repo-relative paths (`make_zip.py`). The ZIP is refused if a secret is found.
6. Ends with a short note: what ran, what passed, what could not be verified (live APIs, databases, secrets)

## Install

**Claude (claude.ai / desktop / mobile):** download `verified-code-delivery.skill` from the [latest release](https://github.com/REPLACE_OWNER/verified-code-delivery/releases/latest) and upload it in Claude's Skills settings.

**Claude Code:** copy the skill folder into your skills directory.

```
git clone https://github.com/REPLACE_OWNER/verified-code-delivery
cp -r verified-code-delivery/skills/verified-code-delivery ~/.claude/skills/
```

Requirements: Python 3.11+. Node/npm for JavaScript projects. Linux and macOS are supported; on Windows use WSL.

## Use

Just ask Claude to write, fix or refactor code. The skill triggers on its own for coding tasks, especially multi-file changes. You can also say "verify it and give me a ZIP of the changed files".

You can run any script by hand too:

```
python scripts/verify.py ./my-project
python scripts/verify.py ./my-monorepo --project apps/web --env-file apps/web/.env.example
python scripts/check_imports.py ./my-project
python scripts/secret_scan.py ./my-project
```

## Security

This tool runs your project's own build and test commands, so treat it like running that code yourself. Use a sandbox, and add `--ignore-scripts` to `verify.py` for code you do not trust.

Built-in protections: symlinks are never followed, nothing outside the project directory is read or packaged, only `127.0.0.1` is contacted, ZIPs are blocked on secrets, there are zero runtime dependencies, and releases are reproducible with signed provenance.

Read the [threat model](docs/THREAT_MODEL.md). Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

## Development

```
python -m unittest discover -s tests -v    # tests
python tools/build_skill.py --check        # validate SKILL.md
python tools/build_skill.py                # build dist/verified-code-delivery.skill
```

See [CONTRIBUTING.md](CONTRIBUTING.md). Maintainers: [docs/REPO_SETUP.md](docs/REPO_SETUP.md).

## License

[MIT](LICENSE)
