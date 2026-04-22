# Phase 10.2 Post-Merge Sync + Onboarding/Public Command Surface

Date: 2026-04-22 07:07 (Asia/Jakarta)
Branch: feature/phase10-2-postmerge-sync-onboarding-command-surface
Project Root: projects/polymarket/polyquantbot/

## 1. What was built

- Synced post-merge repo truth to reflect PR #712 lane closure and Phase 10.2 execution truth in `PROJECT_STATE.md` and `ROADMAP.md`.
- Refined `/start` onboarding/session guidance in the active Telegram command runtime path by adding explicit context-aware next-step messaging for `new_user`, `unlinked_user`, `linked_user`, and `session_ready` states.
- Extended public-safe command surface on the active Telegram runtime path with `/paper`, `/about`, `/risk`, `/account`, and `/link` routes while preserving explicit paper-only/no live-capital boundary language.
- Updated Telegram command parsing so `/start <context>` deep-link style arguments are preserved as string context (instead of being dropped when non-numeric).
- Updated focused Telegram tests to validate onboarding friction reduction behavior and new public-safe command routing behavior.

## 2. Current system architecture (relevant slice)

1. `telegram.command_router.CommandRouter` parses Telegram command text and now forwards `/start` string arguments to the command handler.
2. `telegram.command_handler.CommandHandler` remains the authoritative command dispatcher and now includes explicit public-safe handlers for `/paper`, `/about`, `/risk`, `/account`, and `/link`.
3. `/start` routes through `_build_home_payload(start_context=...)` with deterministic onboarding guidance derived from deep-link context tokens.
4. Existing rendering stays centralized via `telegram.view_handler.render_view(...)` and `telegram.ui_formatter.render_dashboard(...)` with updated public command list/guidance copy.
5. Public-safe command surfaces remain informational and paper-only, with no admin/internal operator command exposure.

## 3. Files created / modified (full repo-root paths)

- `PROJECT_STATE.md`
- `ROADMAP.md`
- `projects/polymarket/polyquantbot/telegram/command_handler.py`
- `projects/polymarket/polyquantbot/telegram/command_router.py`
- `projects/polymarket/polyquantbot/telegram/ui_formatter.py`
- `projects/polymarket/polyquantbot/tests/test_telegram_start_numeric_safety.py`
- `projects/polymarket/polyquantbot/reports/forge/phase10-2_01_postmerge-sync-onboarding-command-surface.md`

## 4. What is working

- Post-merge truth sync reflects PR #712 as merged-main historical truth and updates Phase 10 roadmap focus to 10.2 lane wording.
- `/start` can now consume context strings (example: `/start unlinked`) and return reduced-friction next-step onboarding guidance.
- `/paper`, `/about`, `/risk`, `/account`, and `/link` all resolve through the active Telegram runtime command path.
- Help surface now advertises expanded public-safe command set and maintains explicit paper-only boundaries.
- Focused Telegram pytest coverage passes for updated onboarding/session and public-command routing behavior.

## 5. Known issues

- `/account` and `/link` are currently guidance-only public surfaces; full auth/session productization and account-link lifecycle automation remain intentionally out of scope.
- This lane does not implement deploy/runtime environment changes, admin/internal controls, or live-trading claims.

## 6. What is next

- COMMANDER review of this STANDARD, NARROW INTEGRATION lane.
- If approved, continue with next paper-only Telegram hardening priorities from `projects/polymarket/polyquantbot/work_checklist.md`.

Validation Tier   : STANDARD
Claim Level       : NARROW INTEGRATION
Validation Target : Active Telegram public product surface under `projects/polymarket/polyquantbot/telegram`, plus truthful post-merge sync in `PROJECT_STATE.md` and `ROADMAP.md`.
Not in Scope      : Trading/risk engine expansion, DB hardening, deployment/runtime environment work, admin/internal command exposure, live-trading or production-capital claims.
Suggested Next    : COMMANDER review
