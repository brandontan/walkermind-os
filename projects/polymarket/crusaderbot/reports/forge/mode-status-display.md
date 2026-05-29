# WARP•R00T FORGE REPORT — mode-status-display

Branch: WARP/ROOT/mode-status-display
Date: 2026-05-29 22:40 Asia/Jakarta
Lane: 1/5 of the WARP•R00T full-system pre-public-ready audit fix campaign

Validation Tier   : STANDARD
Claim Level       : NARROW INTEGRATION
Validation Target : Telegram + WebTrader trading-mode / auto-trade-status display reads the canonical DB source on every surface
Not in Scope      : execution / risk / capital logic (untouched); the other 4 audit lanes (silent-broken-features, api-hardening, tg-callback-routing, live-path-hardening)
Suggested Next    : WARP🔹CMD review, then proceed to Lane 2 (silent-broken-features)

---

## 1. What was built

Fixed audit Theme #1 — "mode/status indicators read phantom DB keys". Across both
surfaces the trading-mode and auto-trade-status indicators were wired to columns
that do not exist, so users were shown PAPER / STOPPED regardless of reality — a
trust blocker for a product about to allow real-money LIVE trading.

Findings closed:
- T-1: `bot/handlers/mvp/settings.py` read `live_mode_enabled`/`live_trading_enabled`
  (phantom — found nowhere else in the codebase) -> always PAPER.
- T-2: `bot/handlers/mvp/autotrade.py` read `auto_trade_enabled` (phantom; canonical
  is `users.auto_trade_on`) -> always STOPPED.
- M1: `bot/handlers/mvp/onboarding.py` same `auto_trade_enabled` phantom in the
  returning-user classifier.
- F-1: `components/TopBar.tsx` defaulted `tradingMode` to the literal `"paper"`, and
  PortfolioPage/WalletPage/DiscoverPage/AdminPage/SettingsPage render `<TopBar />`
  with no prop -> LIVE users saw a PAPER pill on most pages.
- F-2: `pages/SettingsPage.tsx` Activation-Guards row was a hardcoded `🔒 LOCKED`
  regardless of the already-fetched `liveStatus`.

## 2. Current system architecture (relevant slice)

Telegram: trading-mode is canonical in `user_settings.trading_mode` (written by the
live-gate flow); auto-trade is canonical in `users.auto_trade_on`. The MVP
`_users.fetch_settings()` now SELECTs `trading_mode`; `_users.fetch_user()` already
returns `users.*` (so `auto_trade_on` was always available). Handlers read those.

WebTrader: a new app-wide `TradingModeContext` is fed once from `GET /api/web/me`
(extended to return `trading_mode`) and refreshed on every `system` SSE event (live
enable/disable broadcasts one). `TopBar` falls back to that context when a page does
not pass an explicit `tradingMode` prop; pages that already fetch the mode
(Dashboard loaded-state, AutoTrade loaded-state) still pass it and win. This fixes
all five no-prop pages at once and future-proofs new pages.

## 3. Files created / modified (full repo-root paths)

Modified:
- projects/polymarket/crusaderbot/bot/handlers/mvp/_users.py (SELECT + default trading_mode)
- projects/polymarket/crusaderbot/bot/handlers/mvp/settings.py (read trading_mode from settings row)
- projects/polymarket/crusaderbot/bot/handlers/mvp/autotrade.py (auto_trade_enabled -> auto_trade_on)
- projects/polymarket/crusaderbot/bot/handlers/mvp/onboarding.py (auto_trade_enabled -> auto_trade_on)
- projects/polymarket/crusaderbot/webtrader/backend/router.py (GET /me returns trading_mode)
- projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts (MeResponse.trading_mode)
- projects/polymarket/crusaderbot/webtrader/frontend/src/App.tsx (TradingModeContext + /me fetch + SSE refresh + provider)
- projects/polymarket/crusaderbot/webtrader/frontend/src/components/TopBar.tsx (context fallback, no hardcoded "paper")
- projects/polymarket/crusaderbot/webtrader/frontend/src/pages/DashboardPage.tsx (loading-state TopBar uses context)
- projects/polymarket/crusaderbot/webtrader/frontend/src/pages/SettingsPage.tsx (Activation-Guards row reflects liveStatus.operator_guards_open)

Created:
- projects/polymarket/crusaderbot/tests/test_mode_status_display.py (5 source-level regression pins)

## 4. What is working

- py_compile clean on all 5 touched Python files + the test.
- 5/5 hermetic regression tests pass (phantom keys absent; canonical keys present;
  fetch_settings SELECTs trading_mode).
- `ruff check` clean on all touched Python.
- Frontend `tsc --noEmit` clean; `vite build` clean (6.02s).
- Telegram Settings now shows LIVE when `user_settings.trading_mode='live'`; MVP
  Auto-Trade shows RUNNING when `users.auto_trade_on=true`.
- WebTrader TopBar shows the real LIVE/PAPER pill on every page; Settings
  Activation-Guards row reflects real operator-guard state.

## 5. Known issues

- The regression pins are source-level (matching the repo's established convention,
  e.g. test_paper_default_invariant.py); no DB-backed functional test was added for
  the Telegram read path. Acceptable for a display-only STANDARD lane.
- `/me` now does one extra single-column `user_settings` read per call (`/me` is a
  once-per-session identity call — negligible).

## 6. What is next

- WARP🔹CMD review of this lane.
- Lane 2: WARP/ROOT/silent-broken-features (copy-trade monitor naive-datetime dead
  path, withdrawal-notify TypeError, frontend error-vs-empty states).
- Lanes 3-5: api-hardening, tg-callback-routing, live-path-hardening.

Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
