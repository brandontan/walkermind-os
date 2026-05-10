# WARP•FORGE Report — Phase 5J Emergency Menu Redesign

**Date:** 2026-05-10  
**Branch:** claude/emergency-menu-redesign-okgLY (declared: WARP/CRUSADERBOT-PHASE5J-EMERGENCY)  
**Validation Tier:** STANDARD (bumped from MINOR — Codex P1 addressed; DB migration + gate logic added)  
**Claim Level:** UI text + confirmation flow + operator-enforced account lock  
**Validation Target:** bot/handlers/emergency.py, bot/keyboards/__init__.py, users.py, migrations/017, presets.py (resume/activate gates), dashboard.py (autotrade toggle gate), admin.py (/unlock), dispatcher.py  
**Not in Scope:** trading logic, execution, risk gate, CLOB, activation guards (ENABLE_LIVE_TRADING etc.)  
**Suggested Next Step:** WARP🔹CMD review → merge direct (STANDARD, no SENTINEL required per workflow)

---

## 1. What Was Built

Emergency menu surface redesigned per Phase 5 UX Spec v2.0, Section 7, with full operator-enforced lock enforcement (Codex P1 addressed):

- **Emergency menu intro** — descriptive header with one-line description per action.
- **3-action menu in 2-column grid** — Pause Auto-Trade, Pause + Close All, Lock Account, Back.
- **Per-action confirmation dialog** — every destructive action requires a Confirm step. Cancel returns to intro menu.
- **Post-action feedback** — result message + 2-column nav: [Dashboard] [Auto-Trade].
- **Lock Account action** — sets `paused=True` + `locked=True` (new DB column). Writes `self_lock_account` audit event.
- **`users.locked` column** — `migrations/017_user_locked.sql`: `ALTER TABLE users ADD COLUMN IF NOT EXISTS locked BOOLEAN NOT NULL DEFAULT false`. Idempotent.
- **`set_locked()` primitive** — added to `users.py` alongside `set_paused()`.
- **Self-service resume gates** — `presets._on_activate` and `presets._on_pause(paused=False)` reject with "Account locked" when `user.locked=True`. `dashboard.autotrade_toggle_cb` rejects toggle-to-True when locked.
- **`/unlock` operator command** — `admin.unlock_command`: operator-only, accepts `@username` or Telegram user ID, calls `set_locked(False)`, writes `operator_unlock` audit event, notifies user via Telegram.

---

## 2. Current System Architecture

```
"🚨 Emergency" reply-keyboard button
  → emergency_root (reply_text: _EMERGENCY_INTRO + emergency_menu())

emergency:pause / pause_close / lock  (step 1 — show confirm)
  → q.edit_message_text(confirm text + emergency_confirm(action))

emergency:cancel / back  (dismiss confirm)
  → q.edit_message_text(_EMERGENCY_INTRO + emergency_menu())

emergency:confirm:lock  (step 2 — execute lock)
  → set_paused(True) + set_locked(True) + audit(self_lock_account)
  → feedback message + emergency_feedback() nav

Self-service resume gates (all check user.get("locked", False)):
  presets._on_activate       → rejects if locked
  presets._on_pause(False)   → rejects if locked
  dashboard.autotrade_toggle → rejects toggle-to-True if locked

Operator unlock:
  /unlock @username → set_locked(False) + audit(operator_unlock) + notify user
```

Dispatcher: `^emergency:` pattern unchanged; `/unlock` registered as new CommandHandler.

---

## 3. Files Created / Modified

Created:
- `projects/polymarket/crusaderbot/migrations/017_user_locked.sql`
- (report: this file)

Modified:
- `projects/polymarket/crusaderbot/users.py` — `set_locked()` added
- `projects/polymarket/crusaderbot/bot/handlers/emergency.py` — lock action calls `set_locked(True)`; `set_locked` imported
- `projects/polymarket/crusaderbot/bot/handlers/presets.py` — locked gate in `_on_activate` and `_on_pause`
- `projects/polymarket/crusaderbot/bot/handlers/dashboard.py` — locked gate in `autotrade_toggle_cb`
- `projects/polymarket/crusaderbot/bot/handlers/admin.py` — `unlock_command` added
- `projects/polymarket/crusaderbot/bot/dispatcher.py` — `/unlock` CommandHandler registered
- `projects/polymarket/crusaderbot/bot/keyboards/__init__.py` — `emergency_menu()` rewritten (4 buttons, 2×2); `emergency_confirm()` + `emergency_feedback()` added
- `projects/polymarket/crusaderbot/tests/test_phase5d_grid_menu_split.py` — `test_emergency_menu_is_two_col` updated for 4-button layout

---

## 4. What Is Working

- Emergency menu shows descriptive intro before any action is reachable.
- All 3 actions require explicit Confirm tap — no accidental trigger.
- Lock Account sets `locked=True` in DB — persists across bot restarts.
- All known self-service resume paths gated: preset activate, preset resume, dashboard autotrade toggle.
- `/unlock` is operator-only (silent reject for non-operators), accepts @username or telegram ID.
- Operator unlock clears `locked=False`, audits, notifies user.
- All 7 modified Python files pass AST syntax check.
- Migration is additive idempotent (`ADD COLUMN IF NOT EXISTS`, `DEFAULT false`).

---

## 5. Known Issues

- `_on_switch_yes` and `_on_stop_yes` in presets.py set `paused=False` but also set `auto_trade_on=False` — no trading bypass since the scheduler requires both flags; not gated (acceptable).
- Existing activation flows in `bot/handlers/activation.py` not audited for locked gate (out of scope — those are live-activation 2FA flows that already require operator action).
- Residual pre-5J `emergency:resume` callback data produces a no-op (acceptable for UI redesign).

---

## 6. What Is Next

- WARP🔹CMD review → merge (STANDARD, direct per workflow).
- Phase 5E (Copy Trade dashboard + wallet discovery) is the next active lane post-merge.
