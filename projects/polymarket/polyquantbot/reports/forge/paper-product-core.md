# FORGE-X Report — paper-product-core

Date: 2026-04-24 21:11 (Asia/Jakarta)
Branch: NWAP/paper-product-core
Project Root: projects/polymarket/polyquantbot/

---

## 1. What was built

Priority 3 paper trading product completion (WORKTODO sections 17–24).

The core engines (PaperEngine, WalletEngine, PaperPositionManager, TradeLedger, PnLTracker,
RiskGuard, PaperRiskGate) were already fully implemented. This lane wires them together into
the production server layer, surfaces the paper account through Telegram bot commands, adds
strategy visibility, and validates end-to-end with a 19-test suite.

**Section 17 — Paper Account Model:** WalletEngine (initial balance from PAPER_INITIAL_BALANCE
env var, default $10,000), PaperPositionManager, TradeLedger, PnLTracker all wired.
Operator reset path added (clears all state, rebuilds engine stack).

**Section 18 — Paper Execution Engine:** PaperPortfolio replaces the 21-line stub.
Fractional Kelly (a=0.25) sizing: `size = min(equity*0.25*edge/price, equity*0.10)`,
floor $10. PaperEngine.execute_order() called async. Idempotent by trade_id.

**Section 19 — Paper Portfolio Surface:** `/portfolio` → open positions with per-position
unrealized PnL (delegated to existing `handle_trade()` in trade handler with full card UI).
`/pnl` → realized + unrealized PnL + wallet cash/equity. STATE synced after every execution.

**Section 20 — Paper Risk Controls:** PaperRiskGate already had all 5 checks (kill switch,
idempotency, edge >= 2%, liquidity >= $10k, drawdown <= 8%, exposure < 10%). Added `status()`
method returning live snapshot. `/paper_risk` command surfaces it via `format_risk_state_reply()`.

**Section 21 — Paper Strategy Visibility:** `/strategies` now falls back to worker signal
stats (iterations, candidates, accepted, rejected, per-reason rejection breakdown) from
`STATE.worker_runtime.last_iteration` when MultiStrategyMetrics is not injected.
`format_strategy_visibility_reply()` renders it cleanly.

**Section 22 — Admin/Operator Paper Controls:** `/reset` (operator) rebuilds engine stack
and clears STATE. `/pause`, `/resume`, `/kill` already wired (Priority 1/2). All missing
operator command handlers (14 stubs) added to complete the truncated command_handler.py.

**Section 23 — Public Paper UX:** `/paper` now shows real wallet state (cash, equity,
realized PnL, position count, kill switch) from STATE. `format_paper_account_reply()` added.
Paper boundary block preserved on all public commands.

**Section 24 — Paper Validation:** 19-test e2e suite (PE-01..PE-15) covering Kelly sizing,
execute/close order lifecycle, STATE sync, all 5 risk gate blocks, operator reset,
worker run_once() accepted/rejected paths, and all 3 new presentation helpers. 19/19 passing.

---

## 2. Current system architecture

```
FalconGateway (signals)
     │
     ▼
PaperBetaWorker.run_once()
     │
     ├── PaperRiskGate.evaluate() — 5 checks: kill_switch, idempotency, edge,
     │                               liquidity, drawdown, exposure_cap
     │                               + status() for /paper_risk visibility
     │
     └── PaperExecutionEngine.execute() [async]
               │
               └── PaperPortfolio.open_position() [async]
                         │
                         ├── _kelly_size(edge, price, equity) → position size USD
                         │   (a=0.25 fractional Kelly, max 10% equity, floor $10)
                         │
                         └── PaperEngine.execute_order() [async]
                                   ├── WalletEngine.lock_funds()
                                   ├── PaperPositionManager.open_position()
                                   └── TradeLedger.record(OPEN)

After every execution:
     PaperPortfolio._sync_state() → PublicBetaState
          wallet_cash / wallet_locked / wallet_equity
          positions (list[StatePaperPosition])
          exposure (locked / equity)
          realized_pnl (ledger.get_realized_pnl())

Telegram surface:
     /portfolio → handle_trade() → PaperPositionManager.get_all_open()
     /pnl       → PnLTracker.summary() + wallet state
     /paper     → STATE wallet fields via format_paper_account_reply()
     /paper_risk → PaperRiskGate.status(STATE)
     /strategies → worker signal stats fallback via STATE.worker_runtime
     /reset     → PaperPortfolio.reset(STATE) — operator only
```

---

## 3. Files created / modified (full repo-root paths)

**Modified:**
- projects/polymarket/polyquantbot/server/core/public_beta_state.py
- projects/polymarket/polyquantbot/server/portfolio/paper_portfolio.py
- projects/polymarket/polyquantbot/server/execution/paper_execution.py
- projects/polymarket/polyquantbot/server/workers/paper_beta_worker.py
- projects/polymarket/polyquantbot/server/risk/paper_risk_gate.py
- projects/polymarket/polyquantbot/telegram/command_handler.py
- projects/polymarket/polyquantbot/client/telegram/presentation.py

**Created:**
- projects/polymarket/polyquantbot/tests/test_priority3_paper_execution_e2e.py
- projects/polymarket/polyquantbot/reports/forge/paper-product-core.md

---

## 4. What is working

- PaperPortfolio wires real PaperEngine (WalletEngine + PaperPositionManager + TradeLedger + PnLTracker)
- Fractional Kelly (a=0.25) position sizing with 10% equity cap and $10 floor
- Async execute path: PaperBetaWorker → PaperExecutionEngine → PaperPortfolio → PaperEngine
- STATE synchronised after every execution: wallet_cash, wallet_locked, wallet_equity, exposure, realized_pnl, positions
- PaperRiskGate.status() returns live risk snapshot
- /portfolio command surfaces open positions with per-card unrealized PnL
- /pnl command shows realized + unrealized + wallet state
- /paper command shows real account state from STATE
- /paper_risk command shows live risk gate state
- /strategies falls back to worker signal stats (iterations, candidates, accepted, rejected, reasons)
- /reset operator command rebuilds engine stack and clears STATE
- /pause, /resume, /kill operator controls remain wired
- All previously truncated command_handler.py handlers completed (14 operator stubs)
- 19/19 Priority 3 e2e tests passing (PE-01..PE-15)

---

## 5. Known issues

- PaperBetaWorker.price_updater() is a no-op stub — unrealized PnL updates require
  real market price polling (deferred to post-Priority-3 market data integration lane).
- Worker signal source (FalconGateway.rank_candidates()) returns bounded sample data —
  real production signal retrieval is a separate lane.
- /reset creates a fresh PaperPortfolio instance but does not re-inject into the running
  worker (worker holds its own PaperExecutionEngine reference) — operator restart required
  for worker to pick up the reset state.

---

## 6. What is next

SENTINEL MAJOR validation required before merge.

After SENTINEL APPROVED:
- Priority 4 kickoff: Wallet lifecycle foundation (sections 25–30)
- Market price polling for unrealized PnL updates (price_updater() stub)
- Real signal retrieval via FalconGateway (production data lane)

---

Validation Tier   : MAJOR
Claim Level       : FULL RUNTIME INTEGRATION
Validation Target : Paper trading product pipeline end-to-end — signal → risk gate →
                    PaperEngine → STATE sync → Telegram surface commands → e2e tests
Not in Scope      : Live trading, wallet lifecycle, portfolio management, multi-wallet
                    orchestration, settlement engine, real market price polling
Suggested Next    : SENTINEL validation — MAJOR tier — before merge to main
