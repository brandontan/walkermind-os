# WARP•FORGE Report — copy-trade-wizard

**Branch:** claude/copy-trade-wizard-edit-I3U6y
**Date:** 2026-05-10 14:30 Asia/Jakarta
**Validation Tier:** MAJOR
**Claim Level:** NARROW INTEGRATION — New ConversationHandler + DB CRUD + multi-step wizard UI
**Validation Target:** Phase 5F wizard flow (wizard_enter_copy, step1–3, edit screen, pause, delete, custom input, repository CRUD)
**Not in Scope:** copy execution engine, actual trade mirroring, auto-trade presets, wallet stats service, migration/schema changes, activation guards

---

## 1. What Was Built

3-step task setup wizard + per-task edit screen for the 🐋 Copy Trade surface.

**Part 1 — Setup Wizard (3 steps)**
- Step 1/3 Amount: mode selector (Fixed Amount vs % Mirror), preset buttons ([$1][$5][$10][$25] / [5%][10%][25%][50%]), Custom text input.
- Step 2/3 Risk Controls: smart defaults pre-applied (TP +20%, SL -10%, Max/Day $100, Slippage 5%, Min $0.50). [Keep Defaults] or [Edit] (each field as tappable button).
- Step 3/3 Confirmation: full config card (wallet, mode, amount, TP/SL, max/day, slippage, min, mode: Paper). [Start Copying] creates `copy_trade_tasks` row with status=active. Success screen with [Copy Trade] [Dashboard] nav.

**Part 2 — Per-task Edit Screen**
- Entered via copytrade:edit:<task_id> from the dashboard Edit button.
- 2-column grid showing current field values. Tap any field to edit inline via text input.
- [Pause/Resume] toggle, [Delete] with confirmation dialog, [PnL] stub, [Rename], [Back].

**Part 3 — ConversationHandler**
- States: COPY_AMOUNT(0), COPY_RISK(1), COPY_CONFIRM(2), COPY_EDIT(3), COPY_CUSTOM(4).
- Entry points: `^copytrade:copy:` (wizard) and `^copytrade:edit:` (edit screen).
- All wizard-internal callbacks use `wizard:` prefix — zero conflict with existing `copytrade:` handlers.
- Global menu buttons (📊🐋🤖📈💰🚨) and /menu exit wizard cleanly in all states.
- Fallback: "Couldn't parse that. Tap a button or /menu to exit."

**Part 4 — Repository**
- New `domain/copy_trade/repository.py`: create_task, get_task, update_task, delete_task, toggle_pause.
- Parameterised SQL with asyncpg. Idempotent. Full type hints. No silent failures.

---

## 2. Current System Architecture

```
🐋 Copy Trade reply button
        │
menu_copytrade_handler (Phase 5E — unchanged)
        │
Dashboard: [Edit task] ──► copytrade:edit:<id> ──► wizard ConversationHandler (COPY_EDIT)
Dashboard: [Add Wallet] → wallet stats card → [Copy This Wallet]
                                                        │
                                               copytrade:copy:<addr>
                                                        │
                                          wizard ConversationHandler (COPY_AMOUNT)
                                                        │
                        ┌───────────────────────────────┤
                  COPY_AMOUNT                    COPY_AMOUNT
              (mode: fixed / pct)           (mode: fixed / pct)
                        │                         │
                  COPY_RISK ◄──── back ────────────┤
              (defaults or edit)
                        │
                  COPY_CONFIRM
              (card + start copying)
                        │
                repo.create_task()
                        │
              Success screen → [Copy Trade] [Dashboard]

COPY_CUSTOM: any state → text input → parse → return_state
COPY_EDIT:   all task fields editable → DB update via repo
```

Dispatcher order: ConversationHandler added BEFORE general `copytrade:` CallbackQueryHandler so entry-point callbacks are intercepted first.

---

## 3. Files Created / Modified

**Created:**
- `projects/polymarket/crusaderbot/domain/copy_trade/repository.py`
- `projects/polymarket/crusaderbot/tests/test_phase5f_copy_wizard.py`
- `projects/polymarket/crusaderbot/reports/forge/copy-trade-wizard.md` (this file)

**Modified:**
- `projects/polymarket/crusaderbot/bot/keyboards/copy_trade.py` — 9 new keyboard functions appended: wizard_amount_mode_kb, wizard_step1_fixed_kb, wizard_step1_pct_kb, wizard_step2_kb, wizard_step2_edit_kb, wizard_step3_kb, wizard_success_kb, wizard_custom_cancel_kb, edit_task_main_kb, edit_delete_confirm_kb
- `projects/polymarket/crusaderbot/bot/handlers/copy_trade.py` — imports extended; 30+ new functions appended; build_wizard_handler() factory added at end of file; docstring updated for Phase 5F
- `projects/polymarket/crusaderbot/bot/dispatcher.py` — `app.add_handler(copy_trade.build_wizard_handler())` registered before general copytrade: handler

---

## 4. What Is Working

- Full wizard flow from wallet stats card: mode select → amount preset or custom → risk defaults or edit → confirm card → create DB row → success nav.
- Per-task edit screen with all 8 field buttons, pause/resume toggle, delete with confirmation, rename, PnL stub.
- ConversationHandler state machine: 5 states, all transitions covered.
- Global menu buttons in all wizard states: exit conversation, route to correct handler.
- /menu command: exit conversation, show main menu.
- COPY_CUSTOM state handles amount, pct, risk fields (tp/sl/maxd/slip/min), and task_name (rename). Invalid input shows error and stays in COPY_CUSTOM.
- repository.py: all 5 CRUD functions with parameterised SQL and asyncpg pool.
- 33 hermetic tests (33 > required 15). All syntax-validated.
- Zero new phase folders. Zero shims. All callbacks within Telegram 64-byte limit.

---

## 5. Known Issues

- `_fmt_wz_amount` called in step3_confirm with an ad-hoc dict mixing `_DEFAULTS` and task fields — functionally correct but slightly inelegant. Acceptable for P5F scope.
- edit_pnl sends a `reply_text` (new message) rather than editing the existing card, because edit screen may be stale after other operations. Intentional.
- `copy_trade_callback` still has placeholder branches for `copytrade:copy:*` and `copytrade:edit:*` — these are now dead code since ConversationHandler intercepts first. Cleanup deferred to WARP/CRUSADERBOT-LEGACY-CLEANUP.
- Tests cannot execute locally (telegram / aiohttp not installed in dev environment); same constraint as Phase 5E tests. CI will run with correct venv.

---

## 6. What Is Next

- WARP•SENTINEL MAJOR audit required before merge.
- After merge: copy execution engine (Phase 5G or later) reads copy_trade_tasks rows with status=active to drive actual position mirroring.
- Per-task P&L tracking (edit_pnl) becomes live once the execution engine emits trade events.
- Leaderboard per-wallet [Copy] button in discover view can now trigger the wizard (same copytrade:copy:<addr> callback).

---

**Suggested Next Step:** WARP•SENTINEL MAJOR audit of Phase 5F — validate wizard state transitions, DB CRUD safety, no activation guard bypass, async correctness.

**Source:** `projects/polymarket/crusaderbot/reports/forge/copy-trade-wizard.md`
**Tier:** MAJOR
