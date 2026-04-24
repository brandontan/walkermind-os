# FORGE Report — paper-core-foundation

## 1) What was built
- Implemented a paper account domain model inside `server/core/public_beta_state.py` with explicit account/order/position state for paper-only runtime.
- Added a persistence/runtime boundary `server/storage/paper_account_store.py` (deterministic JSON load/save, UTF-8, atomic temp-file replace).
- Upgraded `PaperExecutionEngine` to deterministic lifecycle transitions (`created -> accepted -> filled`) and deterministic fill/slippage behavior with no live order/wallet side effects.
- Upgraded `PaperPortfolio` accounting mutations to update cash/equity/unrealized pnl on paper-only state.
- Extended paper API surface in the active runtime path (`/beta/status`, `/beta/positions`, `/beta/pnl`, new `/beta/portfolio`) to expose baseline portfolio summary.
- Extended paper risk gate with paper-only baseline controls for daily loss stop + per-order notional cap while preserving existing kill-switch/exposure/drawdown checks.
- Wired paper account persistence load into `server/main.py` and save path from `PaperBetaWorker` loop.

## 2) Current system architecture (relevant slice)
- Narrow runtime slice for this lane:
  - `FalconGateway.rank_candidates` -> `PaperBetaWorker.run_once`
  - `PaperRiskGate.evaluate` (paper-only guards)
  - `PaperExecutionEngine.execute` (deterministic simulated lifecycle)
  - `PaperPortfolio.open_position` (paper account/position/pnl mutation)
  - `PersistentPaperAccountStore.save` (paper-only persisted state)
  - `public_beta_routes` reads `STATE` for `/beta/positions`, `/beta/pnl`, `/beta/portfolio`.
- Boundary remains explicit: no live wallet lifecycle, no live exchange order submission, no production-capital authority claimed.

## 3) Files created / modified
- Modified: `projects/polymarket/polyquantbot/server/core/public_beta_state.py`
- Modified: `projects/polymarket/polyquantbot/server/portfolio/paper_portfolio.py`
- Modified: `projects/polymarket/polyquantbot/server/execution/paper_execution.py`
- Modified: `projects/polymarket/polyquantbot/server/risk/paper_risk_gate.py`
- Modified: `projects/polymarket/polyquantbot/server/workers/paper_beta_worker.py`
- Modified: `projects/polymarket/polyquantbot/server/api/public_beta_routes.py`
- Modified: `projects/polymarket/polyquantbot/server/main.py`
- Created: `projects/polymarket/polyquantbot/server/storage/paper_account_store.py`
- Created: `projects/polymarket/polyquantbot/tests/test_paper_core_foundation.py`
- Modified state truth: `projects/polymarket/polyquantbot/state/PROJECT_STATE.md`, `projects/polymarket/polyquantbot/state/ROADMAP.md`, `projects/polymarket/polyquantbot/state/WORKTODO.md`, `projects/polymarket/polyquantbot/state/CHANGELOG.md`

## 4) What is working
- Paper account model exists with persisted load/save boundary and deterministic default account creation.
- Paper execution lifecycle emits deterministic transition trail and deterministic filled output (`paper-ord-N`, `created/accepted/filled`).
- Paper risk controls enforce kill switch, exposure cap, drawdown stop, daily loss stop, and per-order notional cap on the paper execution path.
- Baseline portfolio summary is exposed through active paper API path (`/beta/portfolio`, enriched `/beta/pnl`, `/beta/positions`, `/beta/status`).
- Deterministic tests added for account persistence, execution lifecycle, risk guard, and portfolio reflection on narrow worker path.

## 5) Known issues
- Environment dependency gap: existing legacy test `test_phase8_3_public_paper_beta_spine_20260419.py` is currently skipped because `fastapi` dependency is unavailable in this runner (no runtime claim impact for this lane evidence).
- This lane intentionally does not include live trading, real wallet lifecycle, or public/admin completeness.

## 6) What is next
- Next gate: COMMANDER review then SENTINEL MAJOR validation on branch `NWAP/paper-core-foundation`.
- Suggested follow-up after gate: extend Priority 3 items 21–24 (strategy visibility, admin/operator controls, full paper validation archive).

Validation Tier   : MAJOR
Claim Level       : NARROW INTEGRATION
Validation Target : Paper-only account, execution, portfolio, and risk path for Priority 3 lane in `projects/polymarket/polyquantbot`
Not in Scope      : Live trading, real wallet lifecycle, real exchange execution, production capital readiness, public paper UX completion, admin/operator completion, strategy visibility completion, full release readiness
Suggested Next    : COMMANDER review

## Validation evidence (exact commands + results)
1. `locale && echo PYTHONIOENCODING=${PYTHONIOENCODING:-<unset>}`
   - Result: `LANG=C.UTF-8`, `LC_ALL=C.UTF-8`; `PYTHONIOENCODING=<unset>`
2. `PYTHONIOENCODING=utf-8 python3 -m py_compile projects/polymarket/polyquantbot/server/api/public_beta_routes.py projects/polymarket/polyquantbot/server/core/public_beta_state.py projects/polymarket/polyquantbot/server/execution/paper_execution.py projects/polymarket/polyquantbot/server/main.py projects/polymarket/polyquantbot/server/portfolio/paper_portfolio.py projects/polymarket/polyquantbot/server/risk/paper_risk_gate.py projects/polymarket/polyquantbot/server/workers/paper_beta_worker.py projects/polymarket/polyquantbot/server/storage/paper_account_store.py projects/polymarket/polyquantbot/tests/test_paper_core_foundation.py`
   - Result: pass (exit 0)
3. `PYTHONIOENCODING=utf-8 pytest -q projects/polymarket/polyquantbot/tests/test_paper_core_foundation.py`
   - Result: `4 passed in 0.29s`
4. `PYTHONIOENCODING=utf-8 pytest -q projects/polymarket/polyquantbot/tests/test_phase8_3_public_paper_beta_spine_20260419.py`
   - Result: `1 skipped in 0.06s` (missing fastapi dependency in runner)
