# Contributing

Thanks for helping. A few ground rules keep this project safe to run on other people's code.

## Setup

Python 3.11 or newer. There is nothing to install.

```
python -m unittest discover -s tests -v
python tools/build_skill.py --check
python skills/verified-code-delivery/scripts/secret_scan.py .
```

## Rules

1. **Standard library only.** No runtime dependencies. This keeps the supply-chain surface at zero.
2. **Every behaviour change needs a test**, and every security fix needs a test that fails without the fix.
3. **Never follow symlinks, never touch paths outside `--root`, never contact anything except `127.0.0.1`.** If your change reads files, runs commands or writes archives, say how it respects these in the PR.
4. **No literal secrets in tests.** Build fake keys from fragments at runtime (see `tests/test_scripts.py`). The repo scans itself in CI.
5. Keep `SKILL.md` short and focused on what Claude should do. Details belong in the scripts.
6. Pin any new GitHub Action to a full commit SHA with a version comment.
7. If you change the `description` in `SKILL.md`, add or adjust queries in `evals/trigger_queries.json` (include look-alikes that should not trigger the skill).

## Pull requests

Open an issue first for anything large. PRs need passing CI and a review from a code owner.

## Security issues

Do not open a public issue. See [SECURITY.md](SECURITY.md).
