# WARP•FORGE Report — R12d Telegram Position UX

Branch: `WARP/CRUSADERBOT-R12D-TELEGRAM-POSITION-UX`
Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION — Telegram UI + per-position force-close marker; no new execution path; delegates to existing R12c exit-watcher priority chain
Validation Target: `📈 Positions` reply-keyboard surface, force-close confirm dialog, per-position `force_close_intent` marker, tier-gate enforcement (Tier 2 view / Tier 3 force close)
Not in Scope: auto-trade toggle, dashboard/portfolio view, withdrawal flow, exit_watcher, order router, risk gate, entry flow, applied_tp_pct/applied_sl_pct mutation, activation guards
Suggested Next Step: WARP🔹CMD review and merge — STANDARD tier, no SENTINEL audit required.

---

## 1. What was built

A live position monitor surfaced on the Telegram main menu (`📈 Positions`) plus a per-position Force Close inline button gated behind a confirmation dialog.

User flow:

1. Tier 2+ user taps `📈 Positions` (or sends `/positions`) → bot lists every open position with market title, side, size, avg entry, mark price, unrealized P&L (USDC and %), and the position's applied TP/SL snapshot.
2. Each row carries a `[🛑 Force Close <id6>]` inline button.
3. Tier 3+ user taps Force Close → bot replies with `Close <market>?\nThis cannot be undone.` + `[✅ Confirm Close] [❌ Cancel]`.
4. `✅ Confirm Close` → flips `force_close_intent = TRUE` on that single position via `mark_force_close_intent_for_position(position_id, user_id)` → bot replies `🛑 Force close queued. Exit watcher will close shortly.`
5. `❌ Cancel` → bot replies `Cancelled. Position still open.` (no marker write, no tier check needed for cancel).

The handler is a marker-write only — it does not call the close router or the CLOB submit path. The existing R12c exit watcher consumes `force_close_intent` on its next tick via the priority chain `force_close_intent > tp_hit > sl_hit > strategy_exit > hold`, so the close pipeline, retry-on-CLOB-error, and audit trail used by the global pause+close-all flow are reused unchanged.

Mark-price source: CLOB orderbook midpoint via `integrations.polymarket.get_book`, hard-capped at 3.0 s wall-clock per fetch using `asyncio.wait_for`. On timeout / empty book / missing token_id the row renders `mark N/A` and `P&L price unavailable` rather than crashing the handler. Per-row fetches run concurrently via `asyncio.gather` so the total wall-clock is still bounded by the per-call 3 s budget.

Tier enforcement uses the same `_ensure_tier(update, min_tier)` pattern already in `bot/handlers/dashboard.py`. The codebase's `bot/middleware/tier_gate.require_tier` decorator was considered but it requires a `pool` kwarg threaded into every wrapped handler — the existing handlers in this surface use the in-handler `_ensure` helper instead, so this lane matches that convention. Tier gates: view → `Tier.ALLOWLISTED` (2), force close → `Tier.FUNDED` (3).

---

## 2. Current system architecture

```
Telegram client
  │
  ▼
bot.dispatcher._text_router  ──►  bot.menus.main.MAIN_MENU_ROUTES
                                       │
                                       ├─ "📈 Positions"  ─► bot.handlers.positions.show_positions  (Tier 2)
                                       │                       │
                                       │                       ├─ db.positions JOIN markets  (open only)
                                       │                       ├─ asyncio.gather(_fetch_mark_price)  (3s/fetch)
                                       │                       │     └─ integrations.polymarket.get_book
                                       │                       └─ render rows + positions_list_kb
                                       │
                                       └─ ... (other menu surfaces unchanged)

CallbackQueryHandler dispatch (added in dispatcher.register):
  position:fc_ask:<uuid>     ─► positions.force_close_ask           (Tier 3) → confirm dialog
  position:fc_(yes|no):<uuid> ─► positions.force_close_confirm      (Tier 3 for yes only)
                                       │
                                       └─ on yes: emergency.mark_force_close_intent_for_position
                                                       │
                                                       ├─ UPDATE positions SET force_close_intent=TRUE
                                                       │  WHERE id=$1 AND user_id=$2 AND status='open'
                                                       │  AND force_close_intent=FALSE
                                                       └─ audit.write(self_force_close_position)

Exit watcher (R12c, unchanged) consumes the flag on next tick.
```

`bot.menus.main` is the new single source of truth for reply-keyboard label → handler mapping. Adding a new top-level menu surface is now a one-line edit there instead of two coupled edits across `keyboards.main_menu` and `dispatcher._text_router`.

`bot/keyboards.py` was converted to `bot/keyboards/__init__.py` (verbatim move via `git mv` to preserve history) so the new `bot/keyboards/positions.py` could live alongside as a sibling module without colliding. All existing `from ..keyboards import main_menu, autotrade_toggle, emergency_menu, ...` imports continue to resolve unchanged because Python finds the package's `__init__.py`.

---

## 3. Files created / modified

Created:

* `projects/polymarket/crusaderbot/bot/handlers/positions.py` (new) — show_positions / force_close_ask / force_close_confirm + private helpers (_ensure_tier, _fetch_mark_price, _unrealized_pnl, _format_pnl, _format_tp_sl, _truncate, _load_open_positions, _verify_user_owns_open_position).
* `projects/polymarket/crusaderbot/bot/keyboards/positions.py` (new) — positions_list_kb, force_close_confirm_kb.
* `projects/polymarket/crusaderbot/bot/menus/__init__.py` (new) — package marker.
* `projects/polymarket/crusaderbot/bot/menus/main.py` (new) — MAIN_MENU_ROUTES + get_menu_route.
* `projects/polymarket/crusaderbot/tests/test_positions_handler.py` (new) — 20 hermetic tests.

Modified:

* `projects/polymarket/crusaderbot/bot/keyboards.py` → `projects/polymarket/crusaderbot/bot/keyboards/__init__.py` — file moved verbatim via `git mv` to convert the flat module into a package. No content change.
* `projects/polymarket/crusaderbot/bot/handlers/emergency.py` — added `mark_force_close_intent_for_position(position_id, user_id) -> int`. Mirrors the user-wide `domain.positions.registry.mark_force_close_intent_for_user` pattern: idempotent, ownership-checked at the SQL layer (`WHERE id=$1 AND user_id=$2`), wired into `audit.write(self_force_close_position)`.
* `projects/polymarket/crusaderbot/bot/dispatcher.py` — `_text_router` now delegates to `menus.main.get_menu_route`. `📈 Positions` and `/positions` routed to `positions.show_positions` (was `dashboard.positions`). Two new CallbackQueryHandlers registered: `^position:fc_ask:` and `^position:fc_(yes|no):`. The legacy `^position:close:` handler is left intact — it is the entry point for `dashboard.close_position_cb` which is not surfaced in any new UI but stays callable from any pre-existing keyboard until WARP🔹CMD decides whether to retire it.

> **Scope deviation noted**: the task header listed five files. Two additional touches were required for the feature to be reachable end-to-end:
> 1. `bot/dispatcher.py` — without rerouting `📈 Positions` and registering the new callback patterns, the new handler is dead code. The change is mechanical wiring (5 lines net).
> 2. `bot/menus/__init__.py` — empty package marker for the declared `bot/menus/main.py`.

---

## 4. What is working

* `📈 Positions` reply-keyboard label routes to the new handler (verified by importing `MAIN_MENU_ROUTES['📈 Positions']` and asserting it resolves to `positions.show_positions`).
* `/positions` slash-command routes to the new handler.
* Empty state: zero open positions → `No open positions.` (verified path in code; no DB call regression vs. the legacy handler).
* Mark-price fetch path:
  * Successful book → midpoint of best bid + best ask (test: `test_fetch_mark_price_returns_midpoint`).
  * Empty book → None → row shows `mark N/A` + `P&L price unavailable` (test: `test_fetch_mark_price_empty_book_returns_none`).
  * Timeout exceeds 3 s budget → None, no crash (test: `test_fetch_mark_price_timeout_returns_none` with patched timeout=0.05 s).
  * Missing token_id → short-circuits before fetch attempt (test: `test_fetch_mark_price_no_token_id_short_circuits`).
  * One-sided book → falls back to whichever side is populated (test: `test_fetch_mark_price_one_side_only`).
* Unrealized P&L formula:
  * YES position: pnl = (mark - entry) × shares, shares = size_usdc / entry (test: `test_unrealized_pnl_yes_in_profit`, `test_unrealized_pnl_yes_at_loss`).
  * NO position: pnl = (entry - mark) × shares (test: `test_unrealized_pnl_no_in_profit`).
  * Defensive: entry == 0 returns (0, 0) instead of dividing by zero (test: `test_unrealized_pnl_zero_entry_safe`).
* Force-close confirm flow:
  * Cancel branch → no marker write (test: `test_force_close_confirm_cancel_does_not_mark`).
  * Yes branch → marker called with `(position_id, user_id)` and success reply rendered (test: `test_force_close_confirm_yes_calls_marker_and_replies`).
  * Yes branch + already-queued (marker returns 0) → friendly `already queued` reply, no duplicate audit row (test: `test_force_close_confirm_yes_already_queued_message`).
  * Yes branch + position missing/closed/foreign-owned → marker not called, `not found` reply (test: `test_force_close_confirm_yes_position_missing`).
* Tier gating: rejection routes to the right surface (callback alert vs. message reply) based on update kind. Force-close cancel does not require Tier 3 — only the confirm action does — so a Tier 2 user who sees the dialog can still cancel cleanly.
* Test suite: 73/73 pass (53 pre-existing + 20 new). `test_exit_watcher`, `test_health`, `test_smoke` all unchanged green.

---

## 5. Known issues

* `dashboard.positions` and `dashboard.close_position_cb` are still defined in `bot/handlers/dashboard.py` — the new lane reroutes the menu button and `/positions` command to the new handler, but the legacy functions are not deleted. Reason: `close_position_cb` calls `domain.execution.router.close` directly (bypasses `force_close_intent`) and is registered for the `^position:close:` pattern; no current keyboard emits that pattern, but removing the symbols could break any external code path or test fixture not surfaced in this scope. WARP🔹CMD can decide whether to retire them in a follow-up.
* Tier-gate decorator (`bot/middleware/tier_gate.require_tier`) is not used by this handler. The existing per-surface convention is the in-handler `_ensure(update, min_tier)` helper (see `bot/handlers/dashboard.py`); switching this lane to the decorator would be inconsistent with sibling handlers and would require threading a `pool` kwarg the dispatcher does not currently provide. Match-the-codebase wins over match-the-spec-literally here.
* `mark_force_close_intent_for_position` lives in `bot/handlers/emergency.py` rather than `domain/positions/registry.py` to keep this lane scoped to the Telegram surface — the registry function `mark_force_close_intent_for_user` was preserved unchanged. If the per-position helper grows users (HTTP API, cron, etc.) it should migrate down to the registry layer in a future lane; the SQL is identical to the user-wide variant and the migration is mechanical.
* No integration test against a live Postgres pool — DB-bound paths (`_load_open_positions`, `_verify_user_owns_open_position`, the marker UPDATE) are exercised only structurally. Acceptable for STANDARD tier; SENTINEL audit (not requested for this lane) would be the place to push for a containerised DB harness.

---

## 6. What is next

* WARP🔹CMD review of this PR.
* On merge, a follow-up lane can:
  * Retire `dashboard.positions` and `dashboard.close_position_cb` if no other surface needs them.
  * Promote `mark_force_close_intent_for_position` from `bot/handlers/emergency.py` into `domain/positions/registry.py` once a non-Telegram caller appears.
  * Consider migrating sibling handlers (`dashboard`, `wallet`, `setup`, `emergency`) onto the `MAIN_MENU_ROUTES` source-of-truth pattern introduced here.
* Continues the R12 series: R12c (exit watcher) is awaiting SENTINEL audit; R12e (live → paper auto-fallback) and R12f (daily P&L summary) remain unstarted in `state/PROJECT_STATE.md`.
