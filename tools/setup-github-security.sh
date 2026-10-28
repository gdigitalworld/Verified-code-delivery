#!/usr/bin/env bash
# Apply security settings to the GitHub repository. See docs/REPO_SETUP.md.
# Needs: gh (logged in as a repo admin), git, python3. Run from the repo root after the first push.
set -euo pipefail

REPO_NAME="verified-code-delivery"
OWNER="$(gh api user --jq .login)"
FULL="$OWNER/$REPO_NAME"
APPROVALS="${REQUIRED_APPROVALS:-0}"
PLACEHOLDER="REPLACE_""OWNER"   # split so this file does not rewrite itself

echo "==> Repository: $FULL"
gh repo view "$FULL" >/dev/null

echo "==> 1/4 Replace owner placeholders"
files="$(grep -rl --exclude-dir=.git "$PLACEHOLDER" . || true)"
if [ -n "$files" ]; then
  # shellcheck disable=SC2086
  sed -i.bak "s/$PLACEHOLDER/$OWNER/g" $files
  find . -name '*.bak' -not -path './.git/*' -delete
  git add -A
  git commit -m "Set repository owner"
  git push origin HEAD
else
  echo "    nothing to replace"
fi

echo "==> 2/4 Security features"
gh api -X PATCH "repos/$FULL" --input - >/dev/null <<JSON
{"security_and_analysis": {
  "secret_scanning": {"status": "enabled"},
  "secret_scanning_push_protection": {"status": "enabled"}}}
JSON
gh api -X PUT "repos/$FULL/vulnerability-alerts"
gh api -X PUT "repos/$FULL/automated-security-fixes"
gh api -X PUT "repos/$FULL/private-vulnerability-reporting"
gh repo edit "$FULL" --enable-wiki=false --enable-projects=false --delete-branch-on-merge

echo "==> 3/4 Actions permissions"
gh api -X PUT "repos/$FULL/actions/permissions/workflow" \
  -f default_workflow_permissions=read -F can_approve_pull_request_reviews=false
gh api -X PUT "repos/$FULL/actions/permissions" -F enabled=true -f allowed_actions=selected
gh api -X PUT "repos/$FULL/actions/permissions/selected-actions" \
  -F github_owned_allowed=true -F verified_allowed=false

echo "==> 4/4 Branch protection on main"
CODE_OWNERS=false
[ "$APPROVALS" -gt 0 ] && CODE_OWNERS=true
gh api -X PUT "repos/$FULL/branches/main/protection" --input - >/dev/null <<JSON
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "tests (py3.11, ubuntu-latest)", "tests (py3.12, ubuntu-latest)", "tests (py3.13, ubuntu-latest)",
      "tests (py3.11, macos-latest)", "tests (py3.12, macos-latest)", "tests (py3.13, macos-latest)",
      "dogfood (the skill checks this repo)", "analyze (python)", "analyze (actions)"
    ]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": $APPROVALS,
    "require_code_owner_reviews": $CODE_OWNERS,
    "dismiss_stale_reviews": true
  },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
JSON
if [ "${REQUIRE_SIGNED:-0}" = "1" ]; then
  gh api -X POST "repos/$FULL/branches/main/protection/required_signatures" >/dev/null
fi

echo "Done. Review: https://github.com/$FULL/settings"
