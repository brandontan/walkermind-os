# WARP•R00T FORGE REPORT — silent-broken-features

Branch: WARP/ROOT/silent-broken-features
Date: 2026-05-29 22:53 Asia/Jakarta
Lane: 2/5 of the WARP•R00T full-system pre-public-ready audit fix campaign

Validation Tier   : MAJOR
Claim Level       : NARROW INTEGRATION
Validation Target : copy-trade monitor produces a gate-valid signal; withdrawal outcome notifications reach users; WebTrader critical fetches surface errors instead of masquerading as empty/spinner
Not in Scope      : the gate logic itself (unchanged); the other audit lanes (api-hardening, tg-callback-routing, live-path-hardening)
Suggested Next    : WARP•SENTINEL (MAJOR — copy-trade execution path), then Lane 3 (api-hardening)

---

## 1. What was built

Closed audit Theme #2 — "silently swallowed failures hide broken features". No bare
`except: pass` exists in the repo, but several `try/except`/`.catch` blocks were
catching real bugs and returning, so whole features were dead with zero user signal.

Findings closed:
- copy-trade monitor (HIGH): `services/copy_trade/monitor.py:315` built `signal_ts`
  with naive `datetime.utcnow()`. Risk gate step 9 (`domain/risk/gate.py:342`) does
  `datetime.now(timezone.utc) - ctx.signal_ts` -> `TypeError` (aware minus naive),
  caught at `monitor.py:321` and `return`-ed. Result: EVERY copy-trade candidate
  through the monitor died at the gate and never traded. Fixed to
  `datetime.now(timezone.utc)`.
- withdrawal notifications (HIGH): `bot/handlers/admin.py:618/653` passed
  `parse_mode=ParseMode.MARKDOWN_V2` to `notify_user_by_telegram_id(telegram_user_id,
  text)`, which accepted no such kwarg -> `TypeError` caught at 624/659. Users never
  received approve/reject outcomes. Fixed by adding a `parse_mode` parameter
  (default `ParseMode.HTML`) that forwards to `send()`; the admin calls now render
  their MarkdownV2-escaped messages correctly.
- WebTrader error-vs-empty (HIGH): three fetch paths conflated failure with empty:
  - `SettingsPage.load()` did not guard `getSettings`/`getDashboard` -> any failure
    left `settings=null` and spun on the loading state forever. Now wrapped in
    try/catch with a `loadError` + Retry control.
  - `PortfolioPage` AnalyticsPanel `.catch(() => setData(null))` rendered the
    "No analytics yet" empty state on a 500. Now a distinct error + Retry state.
  - `DashboardPage` secondary loaders (`open positions`, `market feed`,
    `recent closed`) swallowed errors with `/* silent */`. Now `console.warn`
    (observable) while keeping last-known data — they are genuinely secondary to
    the primary `load()` which already surfaces errors.

## 2. Current system architecture (relevant slice)

Copy-trade path: `services/copy_trade/monitor.py` builds a `TradeSignal` and calls
`TradeEngine.execute()`, which maps `signal.signal_ts` straight into `GateContext`
(`services/trade_engine/engine.py:292`) and runs the mandatory risk gate. The gate's
staleness check requires a tz-aware `signal_ts`; all other producers
(`domain/signal/copy_trade.py`, `domain/strategy/strategies/*`) already used
`datetime.now(timezone.utc)` — the monitor was the lone naive producer.

Notification path: `notifications.send(chat_id, text, parse_mode=HTML, ...)` is the
single Telegram sender; `notify_user_by_telegram_id` is the user-facing wrapper and
now forwards `parse_mode` so callers can choose MarkdownV2 vs HTML.

## 3. Files created / modified (full repo-root paths)

Modified:
- projects/polymarket/crusaderbot/notifications.py (notify_user_by_telegram_id parse_mode passthrough)
- projects/polymarket/crusaderbot/services/copy_trade/monitor.py (tz-aware signal_ts + timezone import)
- projects/polymarket/crusaderbot/webtrader/frontend/src/pages/SettingsPage.tsx (load try/catch + error+Retry)
- projects/polymarket/crusaderbot/webtrader/frontend/src/pages/PortfolioPage.tsx (AnalyticsPanel error state + Retry)
- projects/polymarket/crusaderbot/webtrader/frontend/src/pages/DashboardPage.tsx (secondary loaders warn instead of silent)

Created:
- projects/polymarket/crusaderbot/tests/test_silent_broken_features.py (4 tests: tz-aware source pin + aware/naive contract + parse_mode forward/default)

Note: bot/handlers/admin.py needed no change — its calls already passed
parse_mode=MARKDOWN_V2; they were silently failing only because the wrapper rejected
the kwarg. They now work.

## 4. What is working

- py_compile clean on touched Python; `ruff` clean.
- 4/4 hermetic backend tests pass (incl. source pin that fails closed if
  `datetime.utcnow()` returns to the monitor, and a functional pin that
  `notify_user_by_telegram_id` forwards parse_mode to send).
- Frontend `tsc --noEmit` clean; `vite build` clean.
- Rebased onto post-Lane-1 main; DashboardPage/SettingsPage carry both lanes' edits
  cleanly (different regions); re-validated build + tests green after rebase.

## 5. Known issues

- The copy-trade end-to-end mirror was already noted in PROJECT_STATE as gated on a
  follow-up table-swap (MVP path); this lane fixes the monitor's gate-crash so the
  monitor path can actually execute, but the broader copy-trade enablement remains
  per existing roadmap notes.
- Frontend error states are functional (error text + Retry); not yet a designed
  error component — acceptable for this correctness lane.
- jobs/daily_pnl_summary.py naive utcnow in a zoneinfo-fallback date-label path left
  as-is (LOW, not a silent-failure: produces a correct UTC date string).

## 6. What is next

- WARP•SENTINEL validation (MAJOR — copy-trade execution path touched).
- Lane 3: WARP/ROOT/api-hardening (ops exposure, JWT-in-URL, input bounds, auth rate-limit).
- Lanes 4-5: tg-callback-routing, live-path-hardening.

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
