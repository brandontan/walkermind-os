# Telegram UX 04 — Public Command-Set Hygiene + Help Surface Alignment

Date: 2026-04-21 19:51 (Asia/Jakarta)
Branch: feature/public-command-set-hygiene-and-help-alignment
Project Root: projects/polymarket/polyquantbot/

## 1. What was built

- Audited the currently exposed public command copy and tightened `/help` to a trusted public-safe baseline (`/start`, `/help`, `/status`) only.
- Removed premature command advertising from shared public-facing reply surfaces so the public guide no longer over-promises control-plane/operator-managed commands.
- Softened unknown-command guidance to direct users to the trusted public baseline and explicitly state that advanced controls are operator-managed during paper beta.
- Synced runtime startup/polling observability metadata (`registered_commands`) to match the public command set shown in `/help`.
- Added focused test assertions to lock help-surface hygiene (hidden commands not shown in `/help` and unknown fallback).
- Synced `projects/polymarket/polyquantbot/work_checklist.md` with public command-set hygiene completion for the current lane.

## 2. Current system architecture (relevant slice)

1. `client/telegram/presentation.py` remains the single formatting authority for public Telegram copy, including `/help` and unknown-command fallback.
2. `client/telegram/dispatcher.py` still supports the broader command router surfaces, but public guidance now intentionally exposes only trusted commands for paper-beta users.
3. `client/telegram/bot.py` and `client/telegram/runtime.py` startup logs now report the same public baseline command set to keep presentation and runtime metadata aligned.
4. `tests/test_phase8_8_telegram_dispatch_20260419.py` includes explicit anti-regression checks to prevent overexposed command listings from reappearing in the public help surface.

## 3. Files created / modified (full repo-root paths)

- projects/polymarket/polyquantbot/client/telegram/presentation.py
- projects/polymarket/polyquantbot/client/telegram/bot.py
- projects/polymarket/polyquantbot/client/telegram/runtime.py
- projects/polymarket/polyquantbot/tests/test_phase8_8_telegram_dispatch_20260419.py
- projects/polymarket/polyquantbot/work_checklist.md
- projects/polymarket/polyquantbot/reports/forge/telegram_ux_04_public-command-hygiene.md
- PROJECT_STATE.md

## 4. What is working

- `/help` now presents a concise public-safe command guide aligned with current paper-beta truth boundaries.
- Unknown-command fallback no longer advertises non-public/advanced command surfaces.
- `/start`, `/help`, `/status` dispatch semantics are unchanged and preserved.
- Existing command router behavior remains intact while public command copy is tightened.
- Checklist truth now reflects that public command-set hygiene/help alignment is landed at code level.

## 5. Known issues

- Deploy-capable live Telegram render proof for the updated `/help` surface is still pending in this runner environment.
- Hidden commands remain routable internally but are intentionally not advertised publicly until readiness and posture are validated for broader exposure.

## 6. What is next

- Run deploy-capable verification on the updated help surface and collect live Telegram `/help` render evidence.
- Continue COMMANDER review for this STANDARD lane with paper-only/public-safe posture validation.

Validation Tier   : STANDARD
Claim Level       : NARROW INTEGRATION
Validation Target : Public-facing `/help` + unknown-command copy hygiene and runtime metadata alignment for trusted paper-beta command surface.
Not in Scope      : Runtime activation redesign, command-routing redesign, deploy/debug work, live-trading enablement, production-capital readiness.
Suggested Next    : COMMANDER review
