# WARP•R00T — live-mode-paper-trade-contamination-blocker

Branch: `WARP/live-mode-paper-trade-contamination-blocker`
Issue: #1810
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Role: WARP•R00T (root-cause + scoped hardening; R00T final gate)
Date: 2026-06-13 07:46 Asia/Jakarta

Validation Target: Prove and fix paper/live mode isolation for the post-`PAPER -> LIVE` exit-notification path so the system can no longer emit an active `[PAPER] Strategy exit/trade` for a user who is already in LIVE.

Not in Scope: strategy rewrite, new strategy rules, live-fire order placement, real fund movement, deposit/withdraw changes, risk/reward redesign, live-guard flag flips, CLOB credential changes.

---

## 1. Root-cause statement

**Category: stale-mode label on a racing worker close (not an active paper worker, not a label-only bug).**

The `PAPER -> LIVE` switch (`domain/activation/live_mode.enable_live_self_serve`) already does the right things in one atomic transaction: it sets `user_settings.trading_mode='live'`, forces `users.auto_trade_on=FALSE`, and archives every open paper position (`mode='paper_archived'`, `status='closed'`, `exit_reason='paper_to_live_switch'`).

The contamination is a **TOCTOU race against the exit watcher**:

- The exit watcher runs two loops — the 30s `exit_watch` (`registry.list_open_for_exit`) and the 5s candle fast loop (`registry.list_open_candle_positions_for_exit`). Both load open positions with `WHERE p.status='open'` and **no mode filter**, so they pick up paper positions too.
- Both loops funnel through `exit_watcher._act_on_decision`, which closed the position and emitted the user alert + `position.closed` event using `mode=position.mode` — the **stale position-row mode**, never the user's current authoritative mode.
- When the owner tapped LIVE while a candle paper position was still `status='open'`, the watcher could win the atomic close ahead of the switch's archival UPDATE. It then closed that position as `mode='paper'` and fired `[PAPER] Strategy exit` (and the `position.closed` event, which drives both Telegram via `notification_service` and WebTrader via SSE) — **after** the user was already LIVE. That is exactly the production evidence: `LIVE` mode on WebTrader, then a Telegram `[PAPER] Strategy exit` for `Ethereum Up or Down - June 12, 8:25PM-8:30PM ET`, `YES`, exit `0.065`, P&L `-$0.09`.

Note: when the switch instead wins the close race, the watcher's close becomes a `already_closed` no-op and the existing double-close dedup (`exit_watcher.py`) already suppresses the alert. The race only leaks when the **watcher** wins — which the existing code did not guard.

Confirmed NOT contaminated:
- ENTRY notifications. Paper/live entry mode is hardcoded at creation (`domain/execution/paper.py` `mode="paper"`, `domain/execution/live.py` `mode="live"`) and entry automation is gated by `auto_trade_on`, which the switch forces OFF. No post-switch paper entry path exists.
- WebTrader/Telegram mode disagreement. Both already read the same authoritative `user_settings.trading_mode` column (`webtrader/backend/router.py`, `bot/handlers/mvp/_users.fetch_trading_mode`), so invariant #7 already held.

## 2. The fix (minimal, central, race-proof)

A mode-isolation guard at the single exit emission chokepoint, reading the **committed authoritative mode** at emit time:

- `domain/activation/live_mode.py`
  - `get_active_trading_mode(user_id, conn=None)` — public authoritative read of `user_settings.trading_mode` (defaults to `paper`), the same column WebTrader + Telegram read, so every worker agrees.
  - `paper_event_contaminates_live(*, event_mode, active_mode)` — pure predicate: a `paper` / `paper_archived` event is contamination iff the user's current mode is `live`. Genuine paper-while-paper and any live event are never suppressed.
- `domain/execution/exit_watcher.py` `_act_on_decision` — after the close is persisted + audited (`exit_watcher_close_ok`) and after the `already_closed` dedup, resolve the authoritative current mode and, on contamination, record a diagnostic audit (`exit_watcher_paper_exit_suppressed_post_live`) + structured warning (`worker`, `position_id`, `user_id`, `event_mode`, `active_mode`, `reason`) and **return before** emitting the user alert AND the `position.closed` event. The close itself is already done, so the racing paper position is cleaned up silently as historical archived cleanup — never as active `[PAPER]` automation.

Because the guard reads the **committed** `user_settings.trading_mode`, any paper exit that resolves after the switch commits (the exact reported scenario) is suppressed. It covers BOTH watcher loops (single chokepoint) and BOTH surfaces (Telegram alert + `position.closed` → notification_service + SSE). The mode read fails OPEN to existing behaviour on a transient DB error (logged), so a DB blip can never silence a normal paper user's notifications — the committed read is the real protection and a switch is a rare, short window.

## 3. Files created / modified

- `projects/polymarket/crusaderbot/domain/activation/live_mode.py` — added `get_active_trading_mode()` + `paper_event_contaminates_live()`.
- `projects/polymarket/crusaderbot/domain/execution/exit_watcher.py` — `_act_on_decision` mode-isolation guard before alert + `position.closed` emit.
- `projects/polymarket/crusaderbot/tests/test_live_mode_paper_contamination.py` — new behaviour suite (14 tests).
- `projects/polymarket/crusaderbot/reports/forge/live-mode-paper-trade-contamination-blocker.md` — this report.
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`, `WORKTODO.md`, `CHANGELOG.md` — repo-truth sync.

## 4. What is working / validation evidence

- New behaviour suite `test_live_mode_paper_contamination.py` — 14 passed:
  - predicate truth table (paper/paper_archived/case/None vs live/paper);
  - `get_active_trading_mode` reads `trading_mode FROM user_settings` + defaults paper;
  - paper exit + user now LIVE -> close still submitted, NO `[PAPER]` alert, NO `position.closed` emit, suppression audit recorded;
  - control: paper exit + user still PAPER -> alert fires + event emitted (no regression);
  - per-user isolation: userA LIVE suppressed, userB PAPER still notified (exactly one alert, one suppression audit);
  - genuine live exit for a live user -> never suppressed.
- Regression suites green: `test_exit_watcher.py`, `test_live_switch_notification_isolation.py`, `test_self_serve_live_mode.py`, `test_live_mode_truth.py`, `test_live_activation_flow.py` (114 passed).
- Full suite: `pytest projects/polymarket/crusaderbot/tests/` -> 3622 passed, 15 skipped.
- `ruff check` + `py_compile` clean on the three touched Python files.
- Secret-leak / UTF-8 mojibake / BOM scans clean on touched files.

## 5. Safety invariant statement

No live order placed, no real funds moved, no forced trade. No live-guard flips: `USE_REAL_CLOB`, `EXECUTION_PATH_VALIDATED`, `ENABLE_LIVE_TRADING`, `CAPITAL_MODE_CONFIRMED` untouched. Kelly stays 0.25, asyncio only, no hardcoded secrets, no `phase*/` folders. Auto-Trade-OFF-on-LIVE, per-user balance/risk gating, the $5 live Auto-Trade start gate, and the kill switch are all unchanged. The guard only ever SUPPRESSES a paper notification for a now-LIVE user; it never emits a live notification, never changes close P&L, never mutates LIVE data, and the position close itself is unchanged (still atomic, still audited).

Mode-isolation invariants serviced: #2 (paper data not converted to live — close stays paper, just silenced), #3/#7 (single authoritative `user_settings.trading_mode` read), #6 (paper/live notifications mode-isolated + diagnostic trace), #8 (no active paper automation surfaces after LIVE — racing close becomes silent historical cleanup).

## 6. Known issues / what is next

- The position loaders still load both modes (`WHERE status='open'`, no mode filter). This is intentional — live positions for a live user, and paper positions for a paper user, both legitimately need exit processing. The fix guards the EMISSION boundary rather than the loader, which is the correct minimal seam and avoids stranding any position. A loader-level mode filter is unnecessary and was deliberately not added.
- LIVE -> PAPER fresh-session behaviour is unchanged and already covered by `enable_live_self_serve` (paper session reset; LIVE ledgers/positions untouched) and its existing tests; this lane did not need to touch it.
- Suggested next step: WARP🔹CMD first-pass; merge under WARP•R00T final gate on CI green (MAJOR mode-isolation, behaviour-tested, no execution-path change), or route to WARP•SENTINEL if deeper validation is desired.

---

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: post-`PAPER -> LIVE` exit-notification mode isolation (exit watcher emission boundary).
Not in Scope: strategy/risk/execution/order/deposit logic, live-guard flags, real fund movement.
Suggested Next Step: WARP🔹CMD first-pass -> R00T final-gate merge on CI green.
