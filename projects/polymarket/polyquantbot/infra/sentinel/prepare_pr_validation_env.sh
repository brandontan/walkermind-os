#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./prepare_pr_validation_env.sh [pr_number]
# Default PR number is 377 to match active SENTINEL task.

PR_NUMBER="${1:-377}"
REPO_SLUG="${GITHUB_REPO_SLUG:-bayuewalker/walker-ai-team}"
REMOTE_NAME="${GITHUB_REMOTE_NAME:-origin}"

TOKEN="${GITHUB_TOKEN:-${GH_TOKEN:-${GITHUB_APP_TOKEN:-}}}"
if [[ -z "${TOKEN}" ]]; then
  echo "[SENTINEL][BLOCKED] Missing GitHub token. Set one of: GITHUB_TOKEN, GH_TOKEN, GITHUB_APP_TOKEN."
  exit 1
fi

# Corporate proxy in this environment returns HTTP 403 for CONNECT github.com.
# Bypass proxies for GitHub endpoints during git operations.
export NO_PROXY="${NO_PROXY:-},github.com,api.github.com,raw.githubusercontent.com"
export no_proxy="${no_proxy:-},github.com,api.github.com,raw.githubusercontent.com"
unset HTTPS_PROXY HTTP_PROXY https_proxy http_proxy ALL_PROXY all_proxy

AUTH_REMOTE_URL="https://x-access-token:${TOKEN}@github.com/${REPO_SLUG}.git"

if git remote get-url "${REMOTE_NAME}" >/dev/null 2>&1; then
  git remote set-url "${REMOTE_NAME}" "${AUTH_REMOTE_URL}"
else
  git remote add "${REMOTE_NAME}" "${AUTH_REMOTE_URL}"
fi

echo "[SENTINEL] Remote configured: ${REMOTE_NAME} -> https://github.com/${REPO_SLUG}.git"

echo "[SENTINEL] Fetching PR #${PR_NUMBER}"
git fetch "${REMOTE_NAME}" "pull/${PR_NUMBER}/head"

echo "[SENTINEL] Checking out FETCH_HEAD"
git checkout FETCH_HEAD

echo "[SENTINEL] Verifying required symbols"
rg "AccountEnvelope"
rg "_persist_trade_intent"

echo "[SENTINEL][READY] PR branch is accessible and validation symbols are present."
