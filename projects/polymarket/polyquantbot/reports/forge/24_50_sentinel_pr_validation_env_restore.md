# 24_50_sentinel_pr_validation_env_restore

- Validation Tier: MAJOR
- Claim Level: NARROW INTEGRATION
- Validation Target: `/workspace/walker-ai-team/projects/polymarket/polyquantbot/infra/sentinel/prepare_pr_validation_env.sh` preflight for GitHub-authenticated PR fetch + checkout + symbol verification (`AccountEnvelope`, `_persist_trade_intent`) on PR refs.
- Not in Scope: Trading strategy logic, risk sizing logic, execution behavior, market data logic, and test internals.
- Suggested Next Step: SENTINEL validation required before merge. Source: `projects/polymarket/polyquantbot/reports/forge/24_50_sentinel_pr_validation_env_restore.md`. Tier: MAJOR

## 1. What was built

Built a SENTINEL preflight script that restores PR-aware validation workflow by configuring authenticated GitHub remote access, neutralizing proxy/tunnel constraints for GitHub endpoints, and enforcing fetch/checkout/symbol checks before validation starts.

## 2. Current system architecture

SENTINEL preflight path:

1. Resolve token from `GITHUB_TOKEN` / `GH_TOKEN` / `GITHUB_APP_TOKEN`.
2. Normalize `origin` remote to authenticated URL for `github.com/{repo}.git`.
3. Disable proxy variables for GitHub fetch commands to avoid CONNECT-tunnel 403 behavior.
4. Execute `git fetch origin pull/<pr>/head`.
5. Execute `git checkout FETCH_HEAD`.
6. Execute `rg AccountEnvelope` and `rg _persist_trade_intent`.
7. Mark environment READY only when all checks pass.

## 3. Files created / modified (full paths)

- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/infra/sentinel/prepare_pr_validation_env.sh` (created)
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/reports/forge/24_50_sentinel_pr_validation_env_restore.md` (created)
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/PROJECT_STATE.md` (updated)

## 4. What is working

- Script now enforces token presence and fails fast if credentials are missing.
- Script creates or updates `origin` with authenticated GitHub URL.
- Script clears proxy variables for GitHub fetch path to prevent known proxy CONNECT 403 failure mode.
- Script runs the exact required command chain for PR-aware SENTINEL gate:
  - `git fetch origin pull/377/head`
  - `git checkout FETCH_HEAD`
  - `rg AccountEnvelope`
  - `rg _persist_trade_intent`
- Script returns READY only after all required checks succeed.

## 5. Known issues

- In the current container, outbound GitHub connectivity is blocked before token auth can be exercised (`CONNECT tunnel failed, response 403`), so end-to-end fetch success cannot be proven locally.
- This change provides deterministic runner-side setup so SENTINEL can execute real PR validation when runner network policy allows GitHub egress.

## 6. What is next

- Run this script in the SENTINEL runner with valid GitHub token and GitHub egress allowed.
- Confirm successful fetch/checkout/symbol checks on PR branch.
- Start SENTINEL runtime validation only after script returns READY.
