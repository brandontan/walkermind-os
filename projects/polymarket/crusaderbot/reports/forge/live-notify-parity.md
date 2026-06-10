# live-notify-parity — LIVE entry card + close snapshot parity

Role: WARP•R00T | Branch: WARP/root-live-notify-parity | Linear: WARP-96
Date: 2026-06-11 Asia/Jakarta
Source gap: reports/forge/readiness-matrix.md row 8(a) — Telegram bot × LIVE

## 1. What was built

Paper/live user-visibility parity on the execution engines:

1. `live.execute()` success path now fires the full `TradeNotifier.notify_entry` card (mode="live", position_id threaded, View/Close action buttons, WebTrader AlertCenter mirror, notification-preference routing) — replacing the legacy bare `notifications.send("📈 [LIVE] Opened …")` text line which bypassed prefs and never reached the AlertCenter. The card's entry price is the SUBMITTED `limit_price` (the same value persisted to `positions.entry_price`), not the raw signal price.
2. The notify call is wrapped fail-soft at the call site: it sits AFTER broker submit + DB persist, and `TradeNotifier._send`'s prefs read (`notifications_enabled_by_telegram_id`) is awaited outside `_send`'s own try/except — a transient DB blip there could otherwise raise out of `execute()` after capital moved. The wrapper logs at ERROR and never re-raises (zero silent failure, zero new failure mode on the money path).
3. `live.close_position()` finalize path now writes a `portfolio_snapshots` row (best-effort by writer contract — `write_snapshot` never raises), so the `cb_portfolio` NOTIFY trigger pushes live-close equity/PnL to WebTrader SSE listeners exactly like the paper close path (paper.py:147-151). The two early-return paths (not-claimed / finalize-lost) deliberately do NOT snapshot.
4. `TradeNotifier.notify_entry` renders a loud `🔴  LIVE TRADE OPENED` header when mode=="live"; paper rendering stays byte-identical (regression-pinned).

## 2. Current system architecture (relevant slice)

entry: signal → gate → router → live.execute → [guards → pending order → CLOB submit → persist position+ledger (atomic) → audit → **TradeNotifier card (fail-soft)**] — notification strictly after the money path completes; no new awaits before broker submission.
close: exit_watcher/router → live.close_position → [claim → SELL → finalize+credit (atomic) → audit → **portfolio snapshot (best-effort)**] → exit_watcher emits position.closed (unchanged, mode-agnostic).

## 3. Files created / modified

- projects/polymarket/crusaderbot/domain/execution/live.py — modified (imports, `_notifier` singleton, entry-card swap, close snapshot; removed now-unused `html` import)
- projects/polymarket/crusaderbot/services/trade_notifications/notifier.py — modified (mode-aware entry header, paper byte-identical)
- projects/polymarket/crusaderbot/tests/test_live_notify_parity.py — created (7 hermetic tests)
- projects/polymarket/crusaderbot/reports/forge/live-notify-parity.md — this report
- projects/polymarket/crusaderbot/state/PROJECT_STATE.md, state/CHANGELOG.md — synced

## 4. What is working

- 7 new hermetic tests: card fired with mode="live" + position_id + tp/sl; legacy bare send gone; notification failure never fails the order (result contract byte-asserted); finalized close snapshots once with user_id; unclaimed close skips snapshot; LIVE header renders; paper header byte-unchanged.
- Full suite **3409 passed / 11 skipped** (baseline 3402/11 — +7 new, 0 regressions); ruff clean on touched files.

## 5. Known issues

- None in-lane. Live close user-facing notification remains exit_watcher's job (position.closed event), unchanged by design.
- Muting "trade_opened" in notification prefs now also mutes LIVE entry pings on the TG channel (web AlertCenter mirror still records when web channel enabled) — this is the parity contract: paper and live behave identically, user-controlled.

## 6. What is next

- Inline WARP•SENTINEL validation (MAJOR), then merge per WARP•R00T authority.

Validation Tier   : MAJOR (touches domain/execution/live.py)
Claim Level       : NARROW INTEGRATION (live entry/close user-visibility side effects only)
Validation Target : live.execute notify call-site placement + fail-soft wrapper; close_position snapshot placement; paper rendering regression
Not in Scope      : order/guard/risk logic (byte-unchanged), exit_watcher event bridge, prefs routing internals, paper engine
Suggested Next    : WARP•SENTINEL inline → WARP•R00T merge
