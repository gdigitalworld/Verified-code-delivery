# Publishing and securing the repository (maintainers)

## 1. Create and push

```
git init -b main
git add -A
git commit -m "Initial commit"
gh repo create verified-code-delivery --public --source . --remote origin --push
```

## 2. Apply the security settings

```
./tools/setup-github-security.sh
```

It needs the GitHub CLI logged in as a repository admin (`gh auth login`). It does these things in order:

1. Replaces the owner placeholders in the README, SECURITY.md, issue config and CODEOWNERS with your GitHub username, then commits and pushes that change
2. Turns on secret scanning, push protection, Dependabot alerts and security updates, and private vulnerability reporting
3. Limits Actions: read-only default token, no PR approval by workflows, only GitHub-owned actions allowed
4. Protects `main`: pull request required, status checks required, no force pushes or deletions, linear history, conversations resolved, rules apply to admins

Optional environment variables: `REQUIRED_APPROVALS` (default `0`, set `1` when you have a second maintainer), `REQUIRE_SIGNED=1` to require signed commits.

## 3. Do by hand (no API for these)

- Settings, Actions, General: set **Fork pull request workflows** to require approval for all outside contributors
- Account level: turn on 2FA with a hardware key or passkey, and sign your commits and tags
- Settings, Rules: add a tag ruleset for `v*` so only maintainers can create release tags

## 4. First release

```
git tag -s v1.0.0 -m "v1.0.0"
git push origin v1.0.0
```

The Release workflow tests, builds a reproducible `.skill`, attests its provenance and creates the GitHub release.

## Notes

The workflow files and the settings script were written without access to a GitHub account, so they are untested until their first real run. After the first pull request, confirm the required status check names in branch protection match the job names shown in the Actions tab.
