# WARP•FORGE — fix-full-system-audit

Branch: WARP/fix-full-system-audit
Issue: #1186
Last Updated: 2026-05-20 07:07
Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: Telegram bot main-menu routing for `💼 Trades (N)` + `🤖 Auto Mode`; dashboard ghost inline-keyboard cleanup; WebTrader unrealized P&L strict-interior guard.
Not in Scope: New features; refactors of unrelated handlers; cleanup of `WARP/CRUSADERBOT-TG-KB-CLEANUP` lane (separate PR); frontend changes (BUG-6 covered by backend clamp); BUG-7 cleared by code audit.
Suggested Next: WARP🔹CMD review.

---

## 1. What was built

Scoped fixes for the 5 P1+P2 bugs called out in issue #1186 (WARP-40 full system audit). Pipeline-neutral; no new features.

- **BUG-1 (P1)** — Telegram `💼 Trades (N)` dynamic main-menu label was not routed (only `💼 Portfolio` was registered in `MAIN_MENU_ROUTES`). Taps were silently dropped.
- **BUG-2 (P1)** — `🤖 Auto Mode` button (only surfaces when `auto_trade_on=True`) routed to the preset picker. Users with an active preset expected the status card, not a picker.
- **BUG-3 (P1)** — Stale `📋 COPY CODE` ghost inline keyboard floating above Dashboard / Auto Mode screens from prior onboarding / `p5_dashboard_kb` messages.
- **BUG-4 (P1)** — Single tap on the dynamic `💼 Trades (N)` button produced duplicate sends because the label fell through to wizard text-input handlers.
- **BUG-5 (P2)** — WebTrader `_unrealized_pnl()` used `current_price` without the strict-interior guard PR #1182 applied on the fetch path. Pre-fix DB rows with the CLOB empty-book 1.0 sentinel still inflated P&L (BUG-6 propagated to frontend; covered by backend clamp).
- **INFO (P3)** — Dead `📈 My Trades` group=-1 handler removed (label no longer in any keyboard).

## 2. Current system architecture (relevant slice)

Telegram bot text-input routing (post-fix):

```
update.message (text)
   │
   ├─ group=-1 MessageHandler  filters.Regex(r"^📊 Dashboard$")          → dashboard()
   ├─ group=-1 MessageHandler  filters.Regex(r"^🤖 Auto-Trade$")         → show_autotrade()
   ├─ group=-1 MessageHandler  filters.Regex(r"^💰 Wallet$")              → wallet_root()
   ├─ group=-1 MessageHandler  filters.Regex(r"^💼 (Portfolio|Trades \(\d+\))$")
   │                                                                       → positions.show_portfolio()   ← NEW (BUG-1 + BUG-4)
   ├─ group=-1 MessageHandler  filters.Regex(r"^🚨 Emergency$")           → emergency_root()
   │
   ├─ (ConversationHandlers — never reach `💼 Portfolio|Trades (N)` now)
   │
   └─ default group MessageHandler  TEXT & ~COMMAND → _text_router
         │
         ├─ matches r"^💼 Trades \(\d+\)$"  → clear awaiting, return (BUG-1 short-circuit)
         ├─ MAIN_MENU_ROUTES["📊 Dashboard" | "💼 Portfolio"]  → _group0_noop (sentinel)
         ├─ MAIN_MENU_ROUTES["🤖 Auto Mode"]                    → autotrade.auto_mode_entry  ← NEW (BUG-2)
         ├─ MAIN_MENU_ROUTES["🤖 Setup Auto"]                   → presets.show_preset_picker
         └─ wizard text_input fallthrough (live_gate / activation / copy_trade / settings / setup)
```

WebTrader unrealized P&L (post-fix):

```
GET /portfolio/summary
   └─ _unrealized_pnl(open_rows)
         for row in rows:
           ep = entry_price
           cp_raw = row.current_price
           cp = cp_raw  if  cp_raw is not None and 0 < cp_raw < 1
                      else  ep      ← BUG-5 clamp: stale 1.0 sentinel ignored
           total += (cp / ep - 1) * size_usdc
```

## 3. Files created / modified (full repo-root paths)

Modified:

- `projects/polymarket/crusaderbot/bot/dispatcher.py` — BUG-1 + BUG-4 group=-1 handler for `💼 Portfolio|Trades (N)`; dynamic-label short-circuit in `_text_router`; dead `📈 My Trades` handler removed.
- `projects/polymarket/crusaderbot/bot/menus/main.py` — `💼 Portfolio` → `_group0_noop` (group=-1 owns the render); `🤖 Auto Mode` → `autotrade.auto_mode_entry`.
- `projects/polymarket/crusaderbot/bot/handlers/autotrade.py` — new `auto_mode_entry()` checks active preset first; falls back to picker on missing state.
- `projects/polymarket/crusaderbot/bot/handlers/dashboard.py` — `_clear_tracked_inline()` + `_track_inline()` helpers; called from both `show_dashboard` and `show_dashboard_for_cb` (BUG-3).
- `projects/polymarket/crusaderbot/webtrader/backend/router.py` — `_unrealized_pnl()` strict-interior guard `0 < cp < 1`; safe fallback to entry_price on out-of-band values.

Created:

- `projects/polymarket/crusaderbot/reports/forge/fix-full-system-audit.md` — this report.

## 4. What is working

- `python -m py_compile` clean on all 5 touched Python files.
- `python -c "import ast; ast.parse(...)"` clean on all 5 touched files.
- Routing path for `💼 Trades (N)`: regex captures `💼 Portfolio` and `💼 Trades (\d+)` at group=-1; `_text_router` short-circuits the dynamic form via the noop sentinel pattern; ConversationHandler states no longer intercept Portfolio taps.
- `auto_mode_entry`: reuses the existing `_get_active_preset()` + `_show_active_status()` plumbing that the `auto_trade:strategy` callback already drives, so the `p5:active:edit/switch/pause/stop` callbacks continue to work from the status card.
- `_clear_tracked_inline`: best-effort `edit_message_reply_markup(reply_markup=None)` on the previously tracked inline message; failures (too-old / unmodified) are silently swallowed.
- `_unrealized_pnl` guard mirrors the strict-interior contract PR #1182 (WARP-38) applied to `get_live_market_price` — same `0 < cp < 1` semantics, same entry-price fallback meaning P&L = 0 for stale rows until `exit_watcher` overwrites them on next tick.

## 5. Known issues

- BUG-3 ghost-clearing tracks only inline messages re-rendered through `show_dashboard` / `show_dashboard_for_cb`. Ghost keyboards from other surfaces (onboarding, wallet flow, settings) are not tracked here; full eradication still depends on `WARP/CRUSADERBOT-TG-KB-CLEANUP` lane (see PROJECT_STATE).
- `_unrealized_pnl` fallback returns `cp = entry_price` (P&L = 0) when `current_price` is stale; this is the safer choice but means the user sees a flat row until the next exit_watcher tick. Acceptable per BUG-5 fix intent.
- `bot/menus/main.py` `positions` import is now unused at module level (route swapped to `_group0_noop`); left in place to avoid an unrelated diff and because the symbol may be re-referenced if future menu routing is added.

## 6. What is next

- WARP🔹CMD review of this PR.
- After merge: Fly.io redeploy so the bot picks up the new dispatcher wiring; backend redeploy so `/portfolio/summary` and `/portfolio/chart` apply the strict-interior guard. No migration required.
- BUG-6 (frontend P&L) is intentionally not edited; the backend clamp here is the single source of truth and the existing PortfolioPage code path consumes the clamped value as-is.
