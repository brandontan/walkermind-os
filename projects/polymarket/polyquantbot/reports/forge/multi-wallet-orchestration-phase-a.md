# multi-wallet-orchestration-phase-a — Priority 6 Phase A Forge Report

## Validation Metadata

- Branch: NWAP/multi-wallet-orchestration
- Validation Tier: MAJOR
- Claim Level: FOUNDATION
- Validation Target: `server/orchestration/` — WalletOrchestrator, WalletSelectionPolicy, and orchestration domain schemas (sections 37–38 of WORKTODO.md)
- Not in Scope: DB persistence, Telegram surfaces, cross-wallet state aggregation, per-wallet controls, UX/API layer (Phase B/C scope)
- Suggested Next Step: SENTINEL validation required for Phase A before Phase B begins (cross-wallet state + controls)

---

## 1. What Was Built

Priority 6 Phase A delivers the orchestration foundation for multi-wallet routing.

**Section 37 — Orchestration Model:**
- `WalletCandidate` frozen dataclass: ownership scope (tenant_id, user_id), lifecycle_status, balance_usd, exposure_pct, drawdown_pct, strategy_tags, is_primary
- `RoutingRequest` frozen dataclass: caller requirements (ownership scope, required_usd, strategy_tag, mode, auto-generated correlation_id)
- `OrchestrationResult` frozen dataclass: outcome, selected_wallet_id, reason, candidates_evaluated, failover_used, routed_at
- `WalletOrchestrator`: async central routing authority — stateless, delegates to policy, logs every routing decision with structlog

**Section 38 — Allocation Across Wallets:**
- `WalletSelectionPolicy`: deterministic 6-filter chain
  1. Ownership filter (tenant_id + user_id must match)
  2. Lifecycle filter (status must be "active")
  3. Balance filter (balance_usd >= required_usd)
  4. Risk gate — HARD, never bypassed (drawdown_pct ≤ MAX_DRAWDOWN=0.08, exposure_pct < MAX_TOTAL_EXPOSURE_PCT=0.10); returns `risk_blocked` if all funded candidates fail
  5. Strategy compatibility filter (empty strategy_tags = all strategies permitted)
  6. Strategy failover: if no candidate passes strategy filter but risk-safe funded candidates exist, relaxes strategy only; `failover_used=True`; risk gate remains enforced
- Ranking: primary wallet preferred over secondary; descending balance as tiebreaker
- Risk constants imported directly from `server.schemas.portfolio` — no duplication

---

## 2. Current System Architecture

```
EXECUTION REQUEST
      ↓
WalletOrchestrator.route(request: RoutingRequest, candidates: list[WalletCandidate])
      ↓
WalletSelectionPolicy.select(request, candidates)
      │
      ├─ Filter 1: ownership (tenant_id + user_id)            → no_candidate if no match
      ├─ Filter 2: lifecycle_status == "active"               → no_active_wallet if none
      ├─ Filter 3: balance_usd >= required_usd                → insufficient_balance if none
      ├─ Filter 4: risk gate (drawdown + exposure) [HARD]     → risk_blocked if all fail
      ├─ Filter 5: strategy_tags compatibility                → strategy failover if all fail
      │            (failover relaxes strategy only —          → routed, failover_used=True
      │             risk gate is never relaxed)
      └─ Rank eligible: is_primary desc, balance_usd desc     → routed, failover_used=False
      ↓
OrchestrationResult(outcome, selected_wallet_id, failover_used, ...)
```

The orchestrator is stateless by design. The service layer (Phase B/C) fetches
WalletCandidate objects from PostgreSQL and passes them to route(). This keeps
the orchestrator fully unit-testable without DB fixtures or mocks.

Risk constants are locked per AGENTS.md:
- MAX_DRAWDOWN = 0.08
- MAX_TOTAL_EXPOSURE_PCT = 0.10
- KELLY_FRACTION = 0.25 (inherited by allocation layer in Phase B)

---

## 3. Files Created / Modified (full repo-root paths)

**Created:**
- `projects/polymarket/polyquantbot/server/orchestration/__init__.py`
- `projects/polymarket/polyquantbot/server/orchestration/schemas.py`
- `projects/polymarket/polyquantbot/server/orchestration/wallet_selector.py`
- `projects/polymarket/polyquantbot/server/orchestration/wallet_orchestrator.py`
- `projects/polymarket/polyquantbot/tests/test_priority6_wallet_orchestration_phase_a.py`
- `projects/polymarket/polyquantbot/reports/forge/multi-wallet-orchestration-phase-a.md`

**Modified:**
- `projects/polymarket/polyquantbot/state/PROJECT_STATE.md`
- `projects/polymarket/polyquantbot/state/WORKTODO.md`
- `projects/polymarket/polyquantbot/state/CHANGELOG.md`

---

## 4. What Is Working

- All 12 tests pass: WO-01 .. WO-12
- WalletCandidate + RoutingRequest + OrchestrationResult frozen dataclasses construct correctly
- Policy routes correctly for: single active wallet, multi-candidate ranking (primary first), strategy-aware selection, ownership mismatch, deactivated lifecycle, insufficient balance
- Risk gate is hard: wallets over MAX_DRAWDOWN (WO-07) or at MAX_TOTAL_EXPOSURE_PCT (WO-12) return `risk_blocked` — never routed
- Strategy failover (WO-11): wallet that fails strategy filter but passes risk gate is routed with `failover_used=True`; risk gate not relaxed
- WalletOrchestrator.route() is async, delegates to policy, catches policy exceptions and returns outcome="error" with reason
- Auto-generated correlation_ids are unique per request (rtr_ prefix)
- Structured logging on every routing decision (start, done, failover warning, error)
- Zero `phase*/` folders in repo
- Risk constants reused from `server.schemas.portfolio` — no duplication

---

## 5. Known Issues

- `server/orchestration/__init__.py` uses relative `server.*` imports; project-level tests use `projects.polymarket.polyquantbot.*` path. The `__init__.py` is a convenience export for runtime use — tests import directly from the submodule paths. No runtime wiring into `server/main.py` yet (Phase B will add service layer wiring).
- WalletCandidate.lifecycle_status is typed as `str` (not `WalletLifecycleStatus`) to avoid circular import from the schema package. Callers pass `.value` of the enum; this is an intentional boundary.
- `exposure_pct` risk ceiling uses strict `<` (less-than, not `<=`) while `drawdown_pct` uses `<=` — consistent with portfolio guardrails in Priority 5. A wallet at exactly MAX_TOTAL_EXPOSURE_PCT=0.10 is blocked.
- No DB persistence of routing decisions yet — deferred to Phase B (orchestration_persistence.py).

---

## 6. What Is Next

Phase B — Cross-Wallet State Truth + Controls (sections 39–40):
- `CrossWalletStateAggregator`: unified view across all wallets for a user
- Duplicate/conflict detection (shared exposure guard)
- Per-wallet enable/disable toggle
- Per-wallet health status and risk state tracking
- Portfolio-wide control overlay (global circuit breaker hooks)
- Service layer wiring into `server/main.py`

Phase C — UX/API, Recovery, and Persistence (sections 41–42):
- Telegram admin surfaces for per-wallet status
- Orchestration decision persistence (PostgreSQL)
- Reconciliation traces
- Full integration test suite

SENTINEL validation required for Phase A before Phase B implementation begins.
