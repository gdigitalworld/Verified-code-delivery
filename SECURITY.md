# Security policy

## Reporting a vulnerability

Please report security problems **privately**, not in a public issue.

Use GitHub's private reporting: open the repository's **Security** tab, choose **Report a vulnerability**, or go directly to
https://github.com/gdigitalworld/Verified-code-delivery/security/advisories/new

Include what you found, how to reproduce it, and the impact you expect. This is a volunteer-run project: the aim is to acknowledge a report within 7 days and to publish a fix and an advisory once one is ready. Please give us reasonable time to fix the issue before disclosing it.

## Supported versions

Only the latest release receives security fixes.

## What counts as a vulnerability here

In scope, for example:

- a script reading or writing files **outside** the project directory (symlink or path-traversal escapes)
- `make_zip.py` including a file it should have refused, or a secret slipping past the scan in a documented pattern
- a script contacting any host other than `127.0.0.1`
- a variable that changes how code is loaded getting through the `--env` / `--env-file` filter
- shell or command injection through script arguments or file contents
- a tampered or non-reproducible release artifact

Out of scope:

- the fact that `verify.py` and `smoke_test.py` execute the project's own build, test and start commands. That is their purpose. See the [threat model](docs/THREAT_MODEL.md) for how to run them on code you do not fully trust.
- secret patterns the scanner does not know about. It is a heuristic safety net, not a guarantee. Feature requests are welcome as normal issues.

## Verifying a release

Each release includes `verified-code-delivery.skill`, a SHA-256 file, and a signed build-provenance attestation:

```
gh attestation verify verified-code-delivery.skill --repo gdigitalworld/Verified-code-delivery
sha256sum -c verified-code-delivery.skill.sha256
```

The build is reproducible: `python tools/build_skill.py` on the tagged source produces a byte-identical file.
