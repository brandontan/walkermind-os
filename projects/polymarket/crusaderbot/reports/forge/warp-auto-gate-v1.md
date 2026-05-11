# WARP•FORGE Report — WARP Auto Gate v1

Branch: WARP/warp-auto-gate-v1
Issue: #980

## 1. What was built
- Added a repo-local WARP Auto Gate v1 design for GitHub PR automation.
- The gate runs from GitHub Actions and checks PR metadata, changed files, head checks, and patch-level safety patterns.
- The gate posts one idempotent PR comment marked with `<!-- warp-auto-gate -->`.
- Auto-merge is intentionally not implemented in v1.

## 2. Current system architecture
- Existing `.github/workflows/gate-pr.yml` remains a best-effort external webhook notification path.
- New local gate is designed to work without Custom GPT background execution.
- The workflow runs from base-branch checkout only and uses GitHub REST API metadata for PR inspection.
- This avoids executing untrusted PR-head code under `pull_request_target`.

## 3. Files created / modified
- `.github/workflows/warp-auto-gate.yml`
- `scripts/warp_auto_gate.py`
- `projects/polymarket/crusaderbot/reports/forge/warp-auto-gate-v1.md`

## 4. What is working
- Branch format validation for `WARP/{feature}`.
- Required PR declaration validation for Validation Tier, Claim Level, Validation Target, and Not in Scope.
- Valid claim/tier enforcement for AGENTS.md claim levels.
- Forge/sentinel report path presence check for code/state/workflow/script PRs.
- Report branch traceability check against actual PR head branch.
- Patch-level hard stops for activation guard flips, full Kelly sizing, and inline silent exception handling.
- Check-run failure detection for current PR head.
- Idempotent PR comment create/update behavior.

## 5. Known issues
- v1 is rule-based and does not replace WARP🔹CMD reasoning.
- v1 does not auto-merge.
- v1 does not run WARP•SENTINEL validation.
- v1 does not include Telegram notification or an external GitHub App daemon.
- Pending check handling is warning-only; failed checks are blockers.

## 6. What is next
Validation Tier   : STANDARD
Claim Level       : NARROW INTEGRATION
Validation Target : GitHub PR automation workflow + stdlib gate script only.
Not in Scope      : runtime trading, guards, CLOB, risk, execution, capital, auto-merge.
Suggested Next    : WARP🔹CMD review, then optional v2 GitHub App / Telegram notification / controlled auto-merge lane.
