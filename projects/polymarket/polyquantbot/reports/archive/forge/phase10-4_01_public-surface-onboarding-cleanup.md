## 1. What was built

- Aligned root `README.md` public-surface wording with current staged-runtime rollout truth and clarified that `/risk_info` is public informational while `/risk` remains runtime/operator-only.
- Refined Telegram first-run onboarding guidance strings in the active command handler so the next-step path is explicit (`/about -> /paper -> /link -> /start -> /status`) and easier to follow for first-time and unlinked users.
- Updated public-help surfaces to include `/link` in the trusted public command set across command payload and rendered Help Center output.
- Added focused test assertions to lock the clearer onboarding flow and `/link` visibility in help output.

## 2. Current system architecture (relevant slice)

1. Telegram inbound commands still route through `telegram.command_router.CommandRouter` into `telegram.command_handler.CommandHandler`.
2. `/start` continues to derive onboarding context via `_derive_onboarding_context(...)` and now emits clearer stepwise guidance from `_build_home_payload(...)`.
3. Public-safe informational command surfaces remain in the same runtime path (`/start`, `/help`, `/status`, `/paper`, `/about`, `/risk_info`, `/account`, `/link`), while `/risk` remains an operator/runtime command.
4. Rendered user-facing help text remains generated through `telegram.ui_formatter` and now reflects `/link` in the public command list.

## 3. Files created / modified (full repo-root paths)

- `README.md`
- `projects/polymarket/polyquantbot/telegram/command_handler.py`
- `projects/polymarket/polyquantbot/telegram/ui_formatter.py`
- `projects/polymarket/polyquantbot/tests/test_telegram_start_numeric_safety.py`
- `projects/polymarket/polyquantbot/reports/forge/phase10-4_01_public-surface-onboarding-cleanup.md`
- `PROJECT_STATE.md`
- `ROADMAP.md`

## 4. What is working

- Public README wording now matches current merged rollout posture and does not claim live-trading or production-capital readiness.
- Telegram onboarding/home decision guidance now gives a clearer first-run path with explicit sequence and return path.
- `/risk_info` remains public informational and `/risk` remains runtime/operator-only in wording and command behavior.
- Help surfaces now consistently include `/link` as part of the public-safe command baseline.
- Targeted regression test coverage for the touched Telegram onboarding/help slice passes.

## 5. Known issues

- This lane does not change backend auth/session productization depth; `/account` and `/link` remain guidance/control-surface commands only.
- Deploy-side Sentry evidence requirements remain blocked and unchanged from prior state tracking.

## 6. What is next

- Submit this post-launch public-surface cleanup lane for COMMANDER review as the next gate.

Validation Tier   : STANDARD
Claim Level       : NARROW INTEGRATION
Validation Target : README/public-surface wording alignment and Telegram onboarding flow clarity only
Not in Scope      : trading logic, risk engine, execution flow, capital controls, async core, strategy behavior, order lifecycle, live-trading enablement
Suggested Next    : COMMANDER review
