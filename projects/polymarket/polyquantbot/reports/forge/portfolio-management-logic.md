# FORGE-X Report — portfolio-management-logic

**Branch:** NWAP/portfolio-management-logic
**Date:** 2026-04-25 18:30 Asia/Jakarta
**Validation Tier:** MAJOR
**Claim Level:** NARROW INTEGRATION
**Validation Target:** Sections 31–36 of WORKTODO.md — Portfolio Management Logic
**Not in Scope:** Multi-wallet orchestration, settlement/retry/reconciliation, live trading, on-chain settlement, production RBAC, public/live-capital readiness

---

## 1. What Was Built

Priority 5 Portfolio Management Logic builds the internal portfolio management layer on top of the Priority 4 wallet lifecycle foundation.

Scope delivered:

**Section 31 — Portfolio Model:**
- `PortfolioPosition` frozen dataclass: market_id, side, size_usd, entry_price, current_price, unrealized_pnl, opened_at
- `PortfolioSummary` frozen dataclass: full portfolio state with cash/locked/equity, realized/unrealized/net PnL, drawdown, exposure_pct, position tuple
- `PortfolioSnapshot` frozen dataclass: point-in-time DB record with snapshot_id (pfs_ prefix), mode, metadata JSONB
- `PortfolioOperationResult` result type: outcome (ok | no_wallet | no_positions | db_error | error)

**Section 32 — Exposure Aggregation:**
- `PortfolioService.aggregate_exposure()`: per-market and total exposure from paper_positions table
- `ExposureReport` with total_exposure_usd, exposure_pct, per_market dict, market_count
- Zero-equity safe floor (defaults to 1.0 to avoid division by zero)
- DB error returns safe zero report, never raises

**Section 33 — Allocation Logic:**
- `PortfolioService.compute_allocation()`: fractional Kelly sizing for a set of signals
- `SignalAllocation` per-signal: size_usd, kelly_fraction, edge, price
- `AllocationPlan`: total_bankroll, all allocations, total_allocated_usd
- Constants enforced: KELLY_FRACTION=0.25, MAX_POSITION_PCT=0.10, MIN_POSITION_USD=10.0

**Section 34 — PnL Logic:**
- `PortfolioService.compute_summary()`: realized PnL from trades table + unrealized PnL from paper_positions
- Net PnL = realized + unrealized
- Drawdown = (peak_equity - current_equity) / peak_equity
- `PortfolioService.get_pnl_history()`: returns ordered PortfolioSnapshot list (newest first)
- `PortfolioService.record_snapshot()`: persists PortfolioSummary to portfolio_snapshots table

**Section 35 — Portfolio Guardrails:**
- `PortfolioService.check_guardrails()`: 4-check enforcement
  1. Kill switch
  2. Drawdown cap (> 8%)
  3. Total exposure cap (> 10% of equity)
  4. Concentration cap (any single market > 20% of equity)
- Returns `GuardrailCheckResult` with allowed bool, violations tuple, per-metric values
- Structured log warning on any violation

**Section 36 — Portfolio Surfaces and Validation:**
- 5 FastAPI routes under `/portfolio`:
  - `GET /portfolio/summary` — equity, PnL, drawdown, positions
  - `GET /portfolio/positions` — open positions list
  - `GET /portfolio/pnl` — snapshot history (last 30)
  - `GET /portfolio/exposure` — per-market exposure report
  - `GET /portfolio/guardrails` — live guardrail check
  - `GET /portfolio/admin` — full admin surface with last snapshot (protected by `PORTFOLIO_ADMIN_TOKEN` env + `X-Portfolio-Admin-Token` header; returns 403 by default)
- `portfolio_snapshots` PostgreSQL table with DDL, two indexes (user+time, wallet+time)
- 29/29 e2e tests passing (PM-01..PM-28 + PM-13b)
- Runtime wired in `server/main.py` lifespan after DB connect

---

## 2. Current System Architecture

```text
DatabaseClient
  -> portfolio_snapshots DDL (new)
  -> trades / paper_positions / wallet_lifecycle (existing)

PortfolioStore
  -> insert_snapshot()
  -> get_latest_snapshot()
  -> list_snapshots()
  -> get_realized_pnl()          (reads trades table)
  -> get_open_positions()        (reads paper_positions table)
  -> get_exposure_per_market()   (reads paper_positions table)

PortfolioService
  -> compute_summary()           (Section 34 — PnL Logic)
  -> aggregate_exposure()        (Section 32 — Exposure Aggregation)
  -> compute_allocation()        (Section 33 — Allocation Logic)
  -> check_guardrails()          (Section 35 — Portfolio Guardrails)
  -> record_snapshot()           (Section 36 — Surfaces)
  -> get_pnl_history()
  -> get_latest_snapshot()

FastAPI routes (server/api/portfolio_routes.py)
  -> GET /portfolio/summary
  -> GET /portfolio/positions
  -> GET /portfolio/pnl
  -> GET /portfolio/exposure
  -> GET /portfolio/guardrails
  -> GET /portfolio/admin

server/main.py lifespan
  -> PortfolioStore wired after DB connect
  -> PortfolioService wired after PortfolioStore
  -> app.state.portfolio_service available to all route handlers
```

---

## 3. Files Created / Modified

Created:
- `projects/polymarket/polyquantbot/server/schemas/portfolio.py`
- `projects/polymarket/polyquantbot/server/storage/portfolio_store.py`
- `projects/polymarket/polyquantbot/server/services/portfolio_service.py`
- `projects/polymarket/polyquantbot/server/api/portfolio_routes.py`
- `projects/polymarket/polyquantbot/tests/test_priority5_portfolio_management_e2e.py`
- `projects/polymarket/polyquantbot/reports/forge/portfolio-management-logic.md`

Modified:
- `projects/polymarket/polyquantbot/infra/db/database.py` (portfolio_snapshots DDL + _apply_schema)
- `projects/polymarket/polyquantbot/server/main.py` (imports + service wiring + router registration)
- `projects/polymarket/polyquantbot/state/PROJECT_STATE.md`
- `projects/polymarket/polyquantbot/state/WORKTODO.md`
- `projects/polymarket/polyquantbot/state/CHANGELOG.md`

---

## 4. What Is Working

- All 4 exposure aggregation checks pass (PM-06..PM-10)
- All 5 Kelly allocation checks pass (PM-11..PM-15): fractional Kelly enforced, max cap, min floor, multi-signal totals
- All 5 PnL logic checks pass (PM-16..PM-20): realized PnL from trades, unrealized from positions, drawdown, snapshot persist
- All 5 guardrail checks pass (PM-21..PM-25): kill switch, drawdown cap, exposure cap, concentration cap
- DB error in store returns safe zero defaults, never propagates to callers
- portfolio_snapshots DDL is idempotent (CREATE TABLE IF NOT EXISTS)
- Runtime wiring in main.py follows same pattern as wallet_lifecycle_service
- All public API routes return 503 when portfolio_service is not wired (safe default)
- `/portfolio/admin` returns 403 unless `PORTFOLIO_ADMIN_TOKEN` env is set and matching header is provided

**Test evidence: 28/28 passing (PM-01..PM-28)**

---

## 5. Known Issues

- `compute_summary()` reads paper_positions without user_id filter — paper mode uses a single shared position store; per-user isolation is deferred to multi-wallet lane (Priority 6)
- Unrealized PnL relies on `current_price` in paper_positions — this field is only updated when positions are persisted; live mark-to-market requires market data integration (deferred, same as Priority 3 debt)
- `/portfolio` routes hardcode `tenant_id="system"` and `user_id="paper_user"` — per-user routing to be added in Priority 6
- No live PostgreSQL validation for snapshot persistence; mocked in tests — live validation deferred to full SENTINEL pre-public sweep
- This lane does not claim public readiness, live trading readiness, or production-capital readiness

---

## 6. What Is Next

Degen structure-mode merge posture:
- COMMANDER review is sufficient for this per-task merge
- SENTINEL is deferred to the full structure sweep before public launch / public-ready claim / live-capital claim
- Priority 6 can proceed only as internal structure work, not as public/live-capital readiness

Suggested next internal lane:
- Priority 6 Multi-Wallet Orchestration, sections 37–42, branch to be declared by COMMANDER

---

## Metadata

- **Validation Tier:** MAJOR
- **Claim Level:** NARROW INTEGRATION
- **Validation Target:** Sections 31–36 — Portfolio Management Logic
- **Not in Scope:** Multi-wallet orchestration, settlement/retry/reconciliation, live Polymarket signing, production RBAC, public readiness, live-capital readiness
- **Suggested Next Step:** COMMANDER merge under degen structure mode; full SENTINEL deferred to pre-public sweep
