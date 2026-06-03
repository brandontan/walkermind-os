# WARP•R00T — CrusaderBot Zero-Base Audit + BLOCKER-1 Fix (NO-side P&L frame)

Role: WARP•R00T (system-wide hardening / root-cause)
Validation Tier: MAJOR
Claim Level: FULL RUNTIME INTEGRATION
Validation Target: the runtime P&L / TP-SL price frame for NO-side positions across all execution + display surfaces
Not in Scope: edge-floor enforcement, max-concurrent invariant, complete-set 2% floor, audit-table unification (all surfaced as follow-ups, NOT changed in this lane)
Suggested Next Step: WARP•SENTINEL validation (MAJOR money-path); then a scoped lane per follow-up in §5

---

## 1. What was built

A zero-base WARP•R00T audit of CrusaderBot, plus the fix for the single confirmed
CRITICAL capital-correctness defect it found (BLOCKER-1).

BLOCKER-1: NO-side positions were mis-evaluated. The data pipeline stores and
feeds each position's OWN outcome-token price (entry stored from `markets.no_price`;
live exit mark fetched via `no_token_id` midpoint; `OpenPositionForExit.current_price()`
returns `no_price`), but the P&L / TP-SL math used a YES-denominated complement
formula `(1-current)-(1-entry))/(1-entry)`. Feeding side-own prices into that
formula INVERTS the sign and uses the wrong cost basis for every NO position —
e.g. a NO token bought at 0.40 and now worth 0.50 is a true +25% gain but was
computed as -16.7% (would fire SL on a winner). This corrupted both TP/SL exit
triggers and booked P&L for ~half of all candle trades (the late_entry_v3 engine
enters the favored side, which is NO whenever DOWN is favored; flip_hunter enters
the cheap side). PAPER-only today, so no real capital lost — but it poisons the
paper-validation dataset the owner uses for the go-live decision, and would
mis-fire real-money exits the instant the activation guards flip.

Fix: converge ALL P&L computations to the single, provably-correct SIDE-OWN frame
— the return on a bought outcome token is `(current - entry) / entry` for BOTH
sides (entry and current are always that token's own price). YES behaviour is
byte-identical; NO is corrected; NO data migration is required (existing NO rows
already store the side-own entry price, so they become correct from the next tick);
and the system is now consistent with `domain/copy_trade/repository.py` whose stats
SQL was already side-own.

The audit's remaining findings were NOT fixed in this lane (see §5).

## 2. Current system architecture

Pipeline unchanged: DATA -> STRATEGY -> RISK (domain/risk/gate.evaluate, 16 steps
0-15, enforced before every execution path — no bypass) -> EXECUTION
(domain/execution/router -> paper/live) -> MONITOR (exit_watcher + notifications).
This lane touches only the P&L/price-frame math inside the EXECUTION + MONITOR +
display surfaces; it does not alter control flow, the risk gate, activation guards,
Kelly, sizing, or idempotency.

Canonical P&L convention (now uniform): a position is "buy `size` USDC of the
chosen outcome token at `entry_price`"; its return is `(current - entry)/entry`,
identical for YES and NO, because `entry_price`/`current_price` are always the
position's own token price.

## 3. Files created / modified (full repo-root paths)

Production (7):
- projects/polymarket/crusaderbot/domain/execution/exit_watcher.py — `_return_pct`, `_tp_exit_price`, `_sl_exit_price` collapsed to side-own (uniform for both sides)
- projects/polymarket/crusaderbot/domain/execution/paper.py — `close_position` P&L to side-own
- projects/polymarket/crusaderbot/domain/execution/live.py — `close_position` P&L to side-own
- projects/polymarket/crusaderbot/services/portfolio_snapshots.py — unrealised-mark SQL CASE to side-own (single branch)
- projects/polymarket/crusaderbot/bot/handlers/trades.py — `_paper_pnl` to side-own
- projects/polymarket/crusaderbot/bot/handlers/positions.py — `_unrealized_pnl` to side-own
- projects/polymarket/crusaderbot/webtrader/backend/router.py — `_tp_sl_price` trigger-price to side-own

Tests (3 files, 8 cases rewritten to side-own semantics):
- projects/polymarket/crusaderbot/tests/test_exit_watcher.py — 4 NO-side cases
- projects/polymarket/crusaderbot/tests/test_fast_track_a.py — 2 NO-side cases
- projects/polymarket/crusaderbot/tests/test_positions_handler.py — 1 NO-side case
- projects/polymarket/crusaderbot/tests/test_live_execution_rewire.py — 1 NO-side case

Report:
- projects/polymarket/crusaderbot/reports/forge/no-side-pnl-frame.md (this file)

## 4. What is working

- 274 tests across all affected files pass (ruff + py_compile clean on every edited file).
- YES-side behaviour is unchanged (the side-own and old YES formula are identical for YES).
- NO-side TP/SL triggers and booked P&L are now correct, verified by the rewritten
  hermetic tests (TP fires when the NO token rises, SL when it falls; resolution
  relabel: NO token -> ~1 = win, -> ~0 = loss).
- All P&L surfaces (exit watcher, paper/live close, portfolio snapshot SQL, Telegram
  trades/positions handlers, WebTrader router, copy-trade stats SQL) now share ONE
  side-own convention — the pre-existing internal inconsistency (positions.py used
  `(entry-mark)/entry` while six others used `(entry-cur)/(1-entry)`) is resolved.

## 5. Known issues (audit findings NOT fixed in this lane — flagged for scoped lanes)

- HIGH — Edge floor never enforced on directional trades: `edge_bps=None` is hardcoded
  in `services/signal_scan/signal_scan_job.py:_build_trade_signal`, so gate step 12
  (MIN_EDGE_BPS=200 and profile 400/300/200) is always skipped. The "edge > 2%"
  invariant is structurally inert for late_entry_v3. (MAJOR)
- HIGH — Max-concurrent invariant drift: `domain/risk/constants.py` PROFILES set
  balanced=12 / aggressive=20 and `config.py MAX_OPEN_POSITIONS=20`; the blueprint
  §6 + hard-rule say 5. Mitigated by the 40% correlated-exposure cap (gate step 8)
  so not capital-catastrophic, but a real invariant/blueprint/state drift. (STANDARD/MAJOR)
- MEDIUM — Complete-set arb 2% floor not hard-wired: `MIN_COMPLETE_SET_EDGE`
  (default 0.0 = dormant) is the only floor; no enforced >=0.02 and fees/slippage
  not explicitly added to the per-pair margin. (STANDARD)
- MEDIUM — Weak strategy edge: late_entry_v3 is a favorite-buying book-imbalance
  heuristic (confidence = ask_diff, not EV); validate OOS via the replay engine. (STANDARD)
- MEDIUM — Observability: two audit destinations (`audit.log` schema table via
  audit.write vs public `audit_log` via kill_switch_exec) fragment forensic queries.
- LOW — `resume_safety_check` skips liquidity/market-status/impact on crash-recovery
  resume (documented, intentional).
- LOW — 2 unlogged silent excepts (users.py:254, bot/handlers/trades.py:276).

## 6. What is next

WARP•SENTINEL MAJOR validation of this money-path fix, then WARP🔹CMD merge decision.
Each §5 follow-up to be scoped as its own lane under WARP🔹CMD direction.
