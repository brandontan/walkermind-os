# WARP•R00T FORGE REPORT — portfolio-status-alert-fixes

Branch: `WARP/ROOT/portfolio-status-alert-fixes`
Role: WARP•R00T (owner-reported bugs)
Validation Tier: **MAJOR** (touches exit-watcher close-reason labelling in the trading core)
Claim Level: NARROW INTEGRATION
Validation Target: three owner-reported UX bugs — TP/SL mislabel at resolution, Telegram dashboard "Stopped", alert ordering.
Not in Scope: changing the live-mark TP fill price (deliberate prior design — see note); per-user strategy control.
Suggested Next Step: WARP🔹CMD review + merge.

---

## 1. What was built (3 bug fixes)

### Bug 1 — "TP hit" shown for a market resolution (realised return ≫ TP setting)
A NO position (entry 0.69, TP +30%) closed at +217.7% and was labelled "Take
Profit (TP)". Ground-truth DB row confirmed `exit_reason='tp_hit'` with the
mark gapped to `0.015` (YES resolved → ~0). Root cause: `exit_watcher.evaluate`
fires TP/SL whenever the return crosses the threshold, but on 5-min binary
markets the price gaps to resolution (≈0/≈1) between polls — so a *resolution*
was mislabelled as a clean TP/SL trigger.
Fix: when the live mark is at a resolution extreme (`<=0.02` or `>=0.98`) at the
moment a threshold is crossed, label `resolution_win` / `resolution_loss`
instead of `tp_hit` / `sl_hit`. WebTrader then shows "Market Resolution
(Won/Lost)"; Telegram sends an honest "Market resolved — Won/Lost" alert.
Genuine intraday TP/SL (mark still trading) is unaffected.

### Bug 2 — Telegram dashboard "🔴 Stopped" while the bot is running
`bot/handlers/mvp/dashboard.py` read `u.get("auto_trade_enabled")` — a key that
never exists on the user row (the column is `auto_trade_on`) — so `running` was
always False and the dashboard always showed Stopped. One-key fix → now shows
"🟢 Running" when `auto_trade_on` and not paused (confirmed: owner's account is
`auto_trade_on=true`).

### Bug 3 — Notifications not newest-first
`App.tsx` concatenated system alerts + trade alerts from two separate sources
without a time sort, so a newer "Trade Closed" sat below older system alerts.
Fix: sort the merged list by `created_at` descending.

## 2. Current system architecture

`exit_watcher.evaluate` now classifies a threshold-crossing close as a
resolution when the mark is settled. New `ExitReason.RESOLUTION_WIN/LOSS` (in
`WATCHER_EXIT_REASONS`) route to new `alert_user_resolution_win/loss`. Frontend
`EXIT_FULL_LABEL` already maps `resolution_win/loss`. No change to fill price or
P&L maths.

## 3. Files modified (full repo-root paths)

- `projects/polymarket/crusaderbot/domain/execution/exit_watcher.py` (resolution detection + relabel + alert routing + `_RESOLUTION_PRICE_EPS`)
- `projects/polymarket/crusaderbot/domain/positions/registry.py` (ExitReason RESOLUTION_WIN/LOSS + WATCHER_EXIT_REASONS)
- `projects/polymarket/crusaderbot/monitoring/alerts.py` (alert_user_resolution_win/loss)
- `projects/polymarket/crusaderbot/bot/handlers/mvp/dashboard.py` (auto_trade_on key fix)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/App.tsx` (newest-first alert sort)
- `projects/polymarket/crusaderbot/tests/test_exit_watcher.py` (+5 tests)
- `projects/polymarket/crusaderbot/tests/test_mvp_dashboard_status.py` (+3 tests, new)

## 4. What is working

- Resolution-driven closes label "Market Resolution (Won/Lost)"; genuine TP/SL unchanged.
- TG dashboard shows Running when auto_trade_on.
- Alerts render newest-first.
- Full suite 2026/2026 pass; ruff + py_compile clean; tsc + vite build clean.

## 5. Known issues / notes

- The realised % on a genuine intraday TP can still slightly exceed the setting
  because the exit fills at the LIVE mark (not the synthetic `entry×(1+tp%)`).
  This was a deliberate prior decision (realtime-fill-price lane) to avoid fake
  identical exits — NOT changed here. Can revisit if exact-target fills are wanted.

## 6. What is next

WARP🔹CMD review + merge → Fly deploy.
