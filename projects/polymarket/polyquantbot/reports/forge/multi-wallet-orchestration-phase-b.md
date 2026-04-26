# multi-wallet-orchestration-phase-b — Priority 6 Phase B Forge Report

## Validation Metadata

- Branch: NWAP/multi-wallet-orchestration
- Validation Tier: MAJOR
- Claim Level: NARROW INTEGRATION
- Validation Target: `server/orchestration/` — CrossWalletStateAggregator, WalletControlsStore, WalletOrchestrator Phase B extension (sections 39–40 of WORKTODO.md)
- Not in Scope: DB persistence of control state, FastAPI/Telegram exposure, Phase C UX/recovery, SENTINEL
- Suggested Next Step: SENTINEL validation required for Phase B before Phase C begins (UX/API, persistence, integration tests)

---

## 1. What Was Built

Priority 6 Phase B delivers the stateful aggregation and control layer on top of Phase A.

**Section 39 — Cross-Wallet State Truth:**
- `WalletHealthStatus` frozen dataclass: per-wallet snapshot with risk_state classification (healthy/at_risk/breached), is_enabled toggle, lifecycle_status, drawdown_pct, exposure_pct
- `CrossWalletState` frozen dataclass: unified cross-wallet view — wallet_count, active_count, total_exposure_pct (balance-weighted), max_drawdown_pct, per-wallet WalletHealthStatus tuple, has_conflict, conflict_reasons
- `CrossWalletStateAggregator`: stateless async aggregator — classifies risk per wallet, computes weighted exposure, detects conflicts (total_exposure_pct >= MAX_TOTAL_EXPOSURE_PCT)
- Risk state thresholds: at_risk = drawdown > MAX_DRAWDOWN * 0.75; breached = drawdown > MAX_DRAWDOWN

**Section 40 — Cross-Wallet Controls:**
- `WalletControlResult` frozen dataclass: action result for enable/disable operations
- `PortfolioControlOverlay` frozen dataclass: portfolio-wide control snapshot for WalletOrchestrator
- `WalletControlsStore`: in-memory per-session control state — enable_wallet, disable_wallet, set_global_halt, clear_global_halt, build_overlay
- `WalletOrchestrator` Phase B extension: optional `overlay` param — global_halt → outcome="halted"; disabled wallets filtered before Phase A policy; overlay=None is 100% backward-compatible

---

## 2. Current System Architecture

```
EXECUTION REQUEST
      ↓
[Optional Phase B pre-hook]
WalletOrchestrator.route(request, candidates, overlay=overlay)
      │
      ├─ overlay.global_halt=True → OrchestrationResult(outcome="halted")
      ├─ Filter: remove wallet_ids not in overlay.enabled_wallet_ids
      │
      ↓
[Phase A filter chain — unchanged]
WalletSelectionPolicy.select(request, filtered_candidates)
      │
      ├─ ownership → lifecycle → balance → risk gate [HARD] → strategy → failover
      └─ Rank: primary first, then descending balance
      ↓
OrchestrationResult

[Parallel — aggregation path]
CrossWalletStateAggregator.aggregate(tenant_id, user_id, candidates, enabled_wallet_ids)
      │
      ├─ Per-wallet: classify risk_state (healthy/at_risk/breached)
      ├─ Portfolio: balance-weighted total_exposure_pct, max_drawdown_pct
      └─ Conflict: total_exposure_pct >= MAX_TOTAL_EXPOSURE_PCT → has_conflict=True
      ↓
CrossWalletState

[Control layer]
WalletControlsStore
      ├─ enable_wallet / disable_wallet → WalletControlResult
      ├─ set_global_halt / clear_global_halt
      └─ build_overlay(tenant_id, user_id, candidates) → PortfolioControlOverlay
```

Risk constants locked (imported from server.schemas.portfolio — no duplication):
- MAX_DRAWDOWN = 0.08
- MAX_TOTAL_EXPOSURE_PCT = 0.10
- at_risk threshold = MAX_DRAWDOWN * 0.75 = 0.06

---

## 3. Files Created / Modified (full repo-root paths)

**Created:**
- `projects/polymarket/polyquantbot/server/orchestration/cross_wallet_aggregator.py`
- `projects/polymarket/polyquantbot/server/orchestration/wallet_controls.py`
- `projects/polymarket/polyquantbot/tests/test_priority6_wallet_orchestration_phase_b.py`
- `projects/polymarket/polyquantbot/reports/forge/multi-wallet-orchestration-phase-b.md`

**Modified:**
- `projects/polymarket/polyquantbot/server/orchestration/schemas.py` (Phase B models appended)
- `projects/polymarket/polyquantbot/server/orchestration/wallet_orchestrator.py` (overlay pre-hook added)
- `projects/polymarket/polyquantbot/server/orchestration/__init__.py` (Phase B exports added)
- `projects/polymarket/polyquantbot/state/PROJECT_STATE.md`
- `projects/polymarket/polyquantbot/state/WORKTODO.md`
- `projects/polymarket/polyquantbot/state/CHANGELOG.md`

---

## 4. What Is Working

- All 15 Phase B tests pass: WO-13..WO-27
- CrossWalletStateAggregator: correct risk_state classification, balance-weighted exposure, conflict detection, empty-candidate edge case
- WalletControlsStore: enable/disable toggle, global halt set/clear, overlay builder respects both per-wallet and global halt
- WalletOrchestrator Phase B: global_halt → "halted"; disabled wallet excluded; overlay=None → Phase A unchanged; all candidates disabled → "no_candidate"
- Integration test WO-27: aggregate detects breached wallet → operator disables → route selects healthy wallet
- Phase A filter chain is 100% unchanged — risk gate still hard, strategy failover still risk-safe only
- Zero phase*/ folders in repo

---

## 5. Known Issues

- WalletControlsStore is in-memory only — control state does not survive process restart. DB persistence deferred to Phase C.
- Phase A tests WO-09 and WO-10 use @pytest.mark.asyncio which requires pytest-asyncio (not installed in current env). Pre-existing issue — unrelated to Phase B changes. All 10 other Phase A tests pass.
- CrossWalletStateAggregator receives pre-fetched candidates — no DB fetch in this layer. Service layer wiring (fetching from PostgreSQL) is Phase C scope.
- is_enabled in WalletHealthStatus reflects the overlay state passed to aggregate(); no live sync with WalletControlsStore.

---

## 6. What Is Next

Phase C — UX/API, Recovery, and Persistence (sections 41–42):
- Telegram admin surfaces: per-wallet status, enable/disable commands, global halt command
- Orchestration decision persistence (PostgreSQL — orchestration_decisions table)
- WalletControlsStore DB-backed persistence (wallet_controls table)
- Reconciliation traces for routing decisions
- Full integration test suite (DB + Telegram + HTTP)
- Service layer wiring: fetch WalletCandidate objects from wallet_lifecycle_store, build overlay from DB-backed controls, pass to WalletOrchestrator

SENTINEL validation required for Phase B before Phase C begins.
