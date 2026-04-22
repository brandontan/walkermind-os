# phase10-3_01_blueprint-template-restore-sync

## 1. What was changed
- Restored `docs/crusader_blueprint_v2.html` as a premium dark/glass visual shell and rebuilt the page content to match the canonical 21-section blueprint order from `docs/blueprint/crusaderbot_final_decisions.md`.
- Source-lock wording was normalized across all sections:
  - Telegram is treated as control surface only, never custody authority.
  - On-chain truth is authoritative over off-chain projection.
  - Execution begins only after risk approval.
  - Risk engine is fail-closed and non-optional.
  - Blueprint describes target shape, not current merged implementation truth.
- Canonical terminology was frozen to source lock:
  - Control verbs: START / PAUSE / RESUME / HALT / EMERGENCY_STOP / KILL.
  - Roles: USER / MODERATOR / OPERATOR / ADMIN / SUPER ADMIN.
  - Auth tiers: TIER 0 ANONYMOUS / TIER 1 TG_AUTHENTICATED / TIER 2 PIN_VERIFIED / TIER 3 STEP_UP_VERIFIED.
  - KILL remains canonical command verb; EMERGENCY_HALT remains runtime-state term only in runtime-modes section.
- Updated `PROJECT_STATE.md` in scoped sections only to reflect this blueprint sync lane on branch `work` and set next gate to COMMANDER review.

## 2. Files modified
- docs/crusader_blueprint_v2.html
- PROJECT_STATE.md
- projects/polymarket/polyquantbot/reports/forge/phase10-3_01_blueprint-template-restore-sync.md

## 3. Validation Tier / Claim Level / Validation Target / Not in Scope / Suggested Next
- Validation Tier   : MINOR
- Claim Level       : FOUNDATION
- Validation Target : docs/crusader_blueprint_v2.html blueprint-template restore + content sync only
- Not in Scope      : repo tree refactor, runtime behavior, execution/risk logic, API/schema changes, current implementation truth changes
- Suggested Next    : COMMANDER review
