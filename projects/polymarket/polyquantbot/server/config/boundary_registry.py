"""§49 Capital Boundary Registry — paper-only surface audit for CrusaderBot.

This module is the authoritative record of every paper-only assumption in the
server domain. Each entry describes:
  - Where the assumption lives (file path + surface name)
  - What makes it paper-only
  - The capital risk level if deployed without hardening
  - Which P8 gate must clear it before LIVE
  - Current readiness status

Status values:
    SAFE_AS_IS       — surface is already safe for capital mode with no changes
    NEEDS_HARDENING  — surface needs changes before P8 SENTINEL gate (tracked in §51-54)
    BLOCKED          — surface is blocked from capital mode until its P8 gate approves

This registry is consumed by:
  - WARP•SENTINEL during P8-B through P8-E sweeps (each sweep clears its gate)
  - WARP•ECHO for capital readiness dashboard reporting
  - WARP•FORGE as the build contract for P8-B through P8-E

Capital-readiness criteria (all must be met before any LIVE claim):
  See get_capital_readiness_criteria() — returns the exact ordered checklist.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

CapitalRisk = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
ReadinessGate = Literal["P8-A", "P8-B", "P8-C", "P8-D", "P8-E"]
BoundaryStatus = Literal["SAFE_AS_IS", "NEEDS_HARDENING", "BLOCKED"]


@dataclass(frozen=True)
class PaperOnlyBoundary:
    """A single paper-only assumption in the server domain.

    Attributes:
        surface: Short name identifying the surface (used in reports).
        file_path: Full repo-root path to the relevant file.
        assumption: What assumption makes this surface paper-only.
        capital_risk: Risk level if deployed to capital mode unmodified.
        readiness_gate: Which P8 phase must clear this (e.g. "P8-B").
        status: SAFE_AS_IS | NEEDS_HARDENING | BLOCKED.
    """

    surface: str
    file_path: str
    assumption: str
    capital_risk: CapitalRisk
    readiness_gate: ReadinessGate
    status: BoundaryStatus


# ── Registry ──────────────────────────────────────────────────────────────────

PAPER_ONLY_BOUNDARIES: tuple[PaperOnlyBoundary, ...] = (
    # ── Execution layer ───────────────────────────────────────────────────────
    PaperOnlyBoundary(
        surface="PaperExecutionEngine",
        file_path="projects/polymarket/polyquantbot/server/execution/paper_execution.py",
        assumption="All order fills are simulated — no real CLOB order submission path exists in this layer. LiveExecutionGuard blocks live execution attempts at PaperBetaWorker level (P8-C).",
        capital_risk="CRITICAL",
        readiness_gate="P8-C",
        status="NEEDS_HARDENING",
    ),
    PaperOnlyBoundary(
        surface="PaperBetaWorker.price_updater",
        file_path="projects/polymarket/polyquantbot/server/workers/paper_beta_worker.py",
        assumption="price_updater() is a no-op stub in paper mode — raises LiveExecutionBlockedError in live mode (P8-C hardened). Real market data integration deferred. Surface actively blocked from capital mode until real data feed is implemented.",
        capital_risk="HIGH",
        readiness_gate="P8-C",
        status="BLOCKED",
    ),
    PaperOnlyBoundary(
        surface="LiveExecutionGuard",
        file_path="projects/polymarket/polyquantbot/server/core/live_execution_control.py",
        assumption="LiveExecutionGuard (P8-C) enforces all 5 capital gates + WalletFinancialProvider non-zero check before any live execution attempt. Blocks and logs deterministically.",
        capital_risk="CRITICAL",
        readiness_gate="P8-C",
        status="NEEDS_HARDENING",
    ),
    # ── Risk layer ────────────────────────────────────────────────────────────
    PaperOnlyBoundary(
        surface="PaperRiskGate",
        file_path="projects/polymarket/polyquantbot/server/risk/paper_risk_gate.py",
        assumption="PaperBetaWorker now accepts CapitalRiskGate via duck-typed AnyRiskGate (P8-C). PaperRiskGate remains the default for paper path. Runtime replacement with CapitalRiskGate is operator-controlled via injection.",
        capital_risk="CRITICAL",
        readiness_gate="P8-C",
        status="NEEDS_HARDENING",
    ),
    # ── Settlement layer ──────────────────────────────────────────────────────
    PaperOnlyBoundary(
        surface="SettlementWorkflow.allow_real_settlement",
        file_path="projects/polymarket/polyquantbot/server/settlement/settlement_workflow.py",
        assumption="allow_real_settlement=False blocks all real settlement paths; live settlement requires this flag plus ENABLE_LIVE_TRADING guard.",
        capital_risk="CRITICAL",
        readiness_gate="P8-C",
        status="BLOCKED",
    ),
    PaperOnlyBoundary(
        surface="SettlementBatchProcessor",
        file_path="projects/polymarket/polyquantbot/server/settlement/batch_processor.py",
        assumption="Batch processor is built and tested for settlement workflow correctness but has never processed real capital settlement events; latency and failure modes under live load are unvalidated.",
        capital_risk="HIGH",
        readiness_gate="P8-C",
        status="NEEDS_HARDENING",
    ),
    PaperOnlyBoundary(
        surface="get_failed_batches always returns empty",
        file_path="projects/polymarket/polyquantbot/server/services/settlement_operator_service.py",
        assumption="Batch result persistence is not implemented; failed batch visibility is unavailable for capital mode incident response.",
        capital_risk="MEDIUM",
        readiness_gate="P8-C",
        status="BLOCKED",
    ),
    # ── Portfolio layer ───────────────────────────────────────────────────────
    PaperOnlyBoundary(
        surface="PortfolioStore.unrealized_pnl",
        file_path="projects/polymarket/polyquantbot/server/storage/portfolio_store.py",
        assumption="Unrealized PnL relies on current_price in paper_positions — live mark-to-market via real market data feed is deferred.",
        capital_risk="HIGH",
        readiness_gate="P8-B",
        status="NEEDS_HARDENING",
    ),
    PaperOnlyBoundary(
        surface="PortfolioRoutes.hardcoded_tenant",
        file_path="projects/polymarket/polyquantbot/server/api/portfolio_routes.py",
        assumption="Routes hardcode tenant_id=system and user_id=paper_user — per-user capital isolation is not implemented.",
        capital_risk="HIGH",
        readiness_gate="P8-D",
        status="NEEDS_HARDENING",
    ),
    # ── Orchestration layer ───────────────────────────────────────────────────
    PaperOnlyBoundary(
        surface="WalletCandidate.financial_fields_zero",
        file_path="projects/polymarket/polyquantbot/server/orchestration/schemas.py",
        assumption="WalletFinancialProvider + enrich_candidate wiring built (P8-B); PortfolioFinancialProvider (P8-C) backed by PublicBetaState. Live-data market feed provider deferred; MissingRealFinancialDataError raised for zero-equity in live mode. Surface actively blocked from capital mode until real market data provider is integrated.",
        capital_risk="CRITICAL",
        readiness_gate="P8-C",
        status="BLOCKED",
    ),
    # ── Capital mode config ───────────────────────────────────────────────────
    PaperOnlyBoundary(
        surface="CapitalModeConfig.gates_all_off",
        file_path="projects/polymarket/polyquantbot/server/config/capital_mode_config.py",
        assumption="All five capital mode gates default to False — no LIVE activation is possible until each P8 gate is explicitly unlocked by WARP🔹CMD after SENTINEL MAJOR approval.",
        capital_risk="LOW",
        readiness_gate="P8-A",
        status="SAFE_AS_IS",
    ),
    # ── Persistence layer ─────────────────────────────────────────────────────
    PaperOnlyBoundary(
        surface="WalletLifecycle.live_postgres_validation_deferred",
        file_path="projects/polymarket/polyquantbot/server/workers/paper_beta_worker.py",
        assumption="Wallet lifecycle live PostgreSQL validation is deferred to pre-public sweep — not validated under real capital conditions.",
        capital_risk="MEDIUM",
        readiness_gate="P8-D",
        status="NEEDS_HARDENING",
    ),
    # ── Operator intervention ─────────────────────────────────────────────────
    PaperOnlyBoundary(
        surface="AdminIntervention.no_persistence",
        file_path="projects/polymarket/polyquantbot/server/settlement/operator_console.py",
        assumption="apply_admin_intervention() does not persist the intervention record — operator actions leave no audit trail for capital mode incident review.",
        capital_risk="MEDIUM",
        readiness_gate="P8-D",
        status="NEEDS_HARDENING",
    ),
    # ── Security layer ────────────────────────────────────────────────────────
    PaperOnlyBoundary(
        surface="AdminRoutes.single_token_auth",
        file_path="projects/polymarket/polyquantbot/server/api/settlement_operator_routes.py",
        assumption="Admin routes use a single SETTLEMENT_ADMIN_TOKEN — capital mode requires hardened permission model with per-action audit logging.",
        capital_risk="HIGH",
        readiness_gate="P8-D",
        status="NEEDS_HARDENING",
    ),
)


# ── Query helpers ─────────────────────────────────────────────────────────────


def get_boundaries_by_gate(gate: str) -> Sequence[PaperOnlyBoundary]:
    return tuple(b for b in PAPER_ONLY_BOUNDARIES if b.readiness_gate == gate)


def get_boundaries_by_status(status: str) -> Sequence[PaperOnlyBoundary]:
    return tuple(b for b in PAPER_ONLY_BOUNDARIES if b.status == status)


def get_critical_boundaries() -> Sequence[PaperOnlyBoundary]:
    return tuple(b for b in PAPER_ONLY_BOUNDARIES if b.capital_risk == "CRITICAL")


def get_capital_readiness_criteria() -> list[str]:
    """Return the ordered checklist that must be satisfied before any LIVE claim.

    This is the exact list WARP•SENTINEL uses during P8-B through P8-E sweeps.
    Each item must be verified before its corresponding gate env var is set.
    """
    return [
        # P8-A (this lane)
        "P8-A-1: CapitalModeConfig is in place with all 5 gates defaulting to OFF.",
        "P8-A-2: PAPER_ONLY_BOUNDARIES registry is complete and covers all CRITICAL surfaces.",
        "P8-A-3: No gate env var (CAPITAL_MODE_CONFIRMED etc.) is set to true in any environment.",
        # P8-B (risk controls hardening)
        "P8-B-1: PaperRiskGate replaced or hardened for capital mode — Kelly=0.25 enforced at order level.",
        "P8-B-2: WalletCandidate financial fields populated from live market data — risk thresholds trigger correctly.",
        "P8-B-3: Portfolio unrealized PnL wired to real market price feed, not stale paper_positions.current_price.",
        "P8-B-4: Drawdown circuit-breaker verified under live position load (>8% auto-halt confirmed).",
        "P8-B-5: Kill switch propagates to all execution surfaces immediately.",
        "P8-B-6: RISK_CONTROLS_VALIDATED=true set in environment only after SENTINEL P8-B APPROVED.",
        # P8-C (live execution readiness)
        "P8-C-1: Live execution path verified — real CLOB order submission path exists and is tested.",
        "P8-C-2: PaperBetaWorker.price_updater replaced with live market data polling.",
        "P8-C-3: SettlementWorkflow.allow_real_settlement path validated end-to-end.",
        "P8-C-4: SettlementBatchProcessor validated under live-equivalent load and failure modes.",
        "P8-C-5: Batch result persistence implemented — get_failed_batches() returns real data.",
        "P8-C-6: Rollback / disable path confirmed — LIVE execution can be halted without state corruption.",
        "P8-C-7: EXECUTION_PATH_VALIDATED=true set only after SENTINEL P8-C APPROVED.",
        # P8-D (security + observability hardening)
        "P8-D-1: Per-user capital isolation implemented — no hardcoded tenant_id/user_id in routes.",
        "P8-D-2: Admin routes hardened — per-action audit log for all operator interventions.",
        "P8-D-3: AdminIntervention persistence implemented — audit trail exists for every capital-mode action.",
        "P8-D-4: Wallet lifecycle live PostgreSQL validation completed under capital conditions.",
        "P8-D-5: Production-grade alerting confirmed — all capital risk events trigger Telegram + Sentry.",
        "P8-D-6: Incident runbooks reviewed and updated for capital mode failure modes.",
        "P8-D-7: SECURITY_HARDENING_VALIDATED=true set only after SENTINEL P8-D APPROVED.",
        # P8-E (final validation + claim review)
        "P8-E-1: Dry-run validation completed — no real capital deployed, all paths exercised.",
        "P8-E-2: Staged rollout plan defined — initial capital exposure capped.",
        "P8-E-3: All overclaim removed from docs, bot copy, and readiness surfaces.",
        "P8-E-4: CAPITAL_MODE_CONFIRMED=true set by WARP🔹CMD after reviewing P8-B/C/D SENTINEL reports.",
        "P8-E-5: ENABLE_LIVE_TRADING=true confirmed as intentional by WARP🔹CMD in deployment.",
        "P8-E-6: CapitalModeConfig.validate() passes in target environment before any live order.",
    ]
