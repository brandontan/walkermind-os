# Exit double-close $0 P&L duplicate alert — fix

Role: WARP•R00T (owner-directed bug fix — "check n fix")
Branch: WARP/exit-double-close-zero-pnl
Validation Tier: MAJOR (execution / exit path — user-facing financial notification)
Claim Level: NARROW INTEGRATION (notification dedup in the close path; P&L math + DB state unchanged)
Validation Target: a racing second close on an already-closed position no longer fires a
  duplicate "[PAPER] TP/SL hit … P&L: $+0.00" alert. The winning close (real P&L) is the
  only one that notifies.
Not in Scope: the P&L formula; the two-loop exit architecture (30s exit_watch + 5s fast
  loop is intentional); the atomic close claim (paper WHERE status='open' / live
  open→closing→closed); MARKET_EXPIRED settlement (separate path); ENABLE_LIVE_TRADING /
  guards / Kelly / risk constants / migrations.
Suggested Next Step: WARP🔹CMD review + merge. Operator: redeploy; the duplicate "+0" exit
  notifications stop immediately (no DB backfill needed — the duplicates were notification-only).

---

## 1. What was built

User report (Telegram, paper test-live): exit notifications show **P&L: $+0.00** even though
entry price ≠ exit price — e.g. a "[PAPER] TP hit … Exit: 0.555 … P&L: $+0.00" and a
"[PAPER] SL hit … P&L: $+0.00". "Before today's updates I did not see +0."

ROOT CAUSE — duplicate notification from a no-op double-close:

- A candle position is evaluated by TWO concurrent scheduler loops: the 30s `exit_watch`
  (`scheduler.check_exits` → `exit_watcher.run_once()`) and the 5s `check_candle_exits`
  fast loop (`exit_watcher.run_once(position_loader=list_open_candle_positions_for_exit, …)`).
- **WARP-93 (today, #1712)** added `candle_auto` to `domain/positions/registry.py:_CANDLE_PRESETS`
  — the fast-loop scoping set. So Smart Strike (candle_auto) positions are now raced by BOTH
  loops. Before WARP-93 candle_auto was only in the 30s loop → no race → no "+0". This is the
  exact regression the user noticed.
- When both loops decide to exit the same position in the same ~5s window, the FIRST close wins
  the atomic `WHERE status='open'` claim and records the REAL P&L + fires the correct alert.
  The racing SECOND close finds the row already closed, so both `paper.close_position`
  (paper.py:131-135) and `live.close_position` (live.py:439-445) return a NO-OP payload:
  `{"pnl_usdc": Decimal("0"), "exit_reason": "already_closed"}`.
- `order.submit_close_with_retry` wraps any non-raising submit as `CloseResult(ok=True)`
  (order.py:105), so `exit_watcher._act_on_decision` treated the no-op as a successful close
  and fired a SECOND user alert with `pnl=0` → the duplicate "P&L: $+0.00" message.

DB integrity was never wrong: the wallet is credited once (only the winning close runs the
ledger credit); the position closes once with real P&L. The bug was purely a duplicate
notification.

FIX (one guard, mode-agnostic): in `_act_on_decision`, after a successful close, if the
payload's `exit_reason == "already_closed"` treat it as a silent dedup — skip the user alert,
the `position.closed` emit, and the fake "close_ok" audit; log an info line instead. The
winning close already notified + credited.

## 2. Current system architecture (close path, after fix)

```
scheduler.check_exits (30s) ─┐
                             ├─> exit_watcher.run_once ─> evaluate ─> _act_on_decision
scheduler.check_candle_exits ┘                                           │
  (5s, candle_auto in scope)                                            │
                                                                         ▼
                                          order.submit_close_with_retry ─> router.close
                                                                         ▼
                                       paper/live.close_position (atomic WHERE status='open')
                                              │                         │
                                   WINNER: real pnl              LOSER: exit_reason=
                                   + alert + emit                "already_closed", pnl=0
                                                                         │
                                                          NEW: _act_on_decision returns early
                                                          (no alert, no emit) — silent dedup
```

## 3. Files created / modified (full repo-root paths)

Modified:
- projects/polymarket/crusaderbot/domain/execution/exit_watcher.py — `_act_on_decision`:
  skip alert + emit when the close payload is the `already_closed` no-op (double-close dedup).
- projects/polymarket/crusaderbot/tests/test_exit_watcher.py — new regression test
  `test_run_once_already_closed_no_op_suppresses_duplicate_alert`.

Created:
- projects/polymarket/crusaderbot/reports/forge/exit-double-close-zero-pnl.md (this report)

## 4. What is working

- New test: an `already_closed` no-op payload → close counted as submitted, but ZERO user
  alerts fire (tp/sl/strategy/force all empty) — the duplicate "+0" is suppressed.
- Existing exit_watcher suite unchanged: 60 passed (TP/SL/force/strategy/resolution/horizon
  + retry/failure paths intact — a REAL close with real pnl still alerts exactly once).
- ruff clean.

## 5. Known issues / notes

- This fixes the duplicate notification (the visible bug). The underlying double-evaluation is
  intentional (the 5s fast loop is the near-resolution SL backstop) and remains; the atomic DB
  claim already makes it state-safe. No change to that design.
- The `already_closed` signal is identical for paper and live, so the guard covers both modes.
- MARKET_EXPIRED closes (`close_as_expired`, pnl_usdc=0.0) are a separate path and legitimately
  report $0 at settlement — not touched.

## 6. What is next

- WARP🔹CMD review + merge.
- Operator: redeploy. No data backfill — past "+0" messages were notification-only; positions
  and balances are correct.
