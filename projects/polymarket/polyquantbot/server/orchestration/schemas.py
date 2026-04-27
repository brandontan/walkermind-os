"""Orchestration domain model — Priority 6 Phase A + Phase B + Phase C.

Covers sections 37–42 of WORKTODO.md:
  37. Orchestration model (routing model, wallet selection, ownership-aware routing)
  38. Allocation across wallets (balance-aware, strategy-aware, risk-aware, failover)
  39. Cross-wallet state truth (unified view, conflict detection, shared exposure guard)
  40. Cross-wallet controls (per-wallet enable/disable, health status, risk state, portfolio overlay)
  41–42. UX/API, recovery, persistence (OrchestrationDecision log)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def new_routing_id() -> str:
    return "rtr_" + uuid4().hex


@dataclass(frozen=True)
class WalletCandidate:
    """A wallet evaluated for routing by the orchestration layer.

    lifecycle_status is stored as a plain string so this schema has no
    hard import dependency on WalletLifecycleStatus — callers pass
    the .value of WalletLifecycleStatus.ACTIVE etc. directly.

    Attributes:
        wallet_id:        Unique wallet identifier (wlc_ prefix).
        tenant_id:        Tenant ownership scope.
        user_id:          User ownership scope.
        lifecycle_status: FSM state string — must be "active" to be eligible.
        balance_usd:      Available liquid balance in USD.
        exposure_pct:     Current exposure as fraction of equity (0.0–1.0).
        drawdown_pct:     Current drawdown as fraction of peak equity (0.0–1.0).
        strategy_tags:    Strategy identifiers this wallet permits (empty = all).
        is_primary:       Whether this is the user's designated primary wallet.
    """

    wallet_id: str
    tenant_id: str
    user_id: str
    lifecycle_status: str
    balance_usd: float
    exposure_pct: float
    drawdown_pct: float
    strategy_tags: frozenset[str] = field(default_factory=frozenset)
    is_primary: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RoutingRequest:
    """Routing request describing what the caller needs.

    Attributes:
        tenant_id:       Tenant scope for ownership check.
        user_id:         User scope for ownership check.
        required_usd:    Minimum balance the selected wallet must hold.
        strategy_tag:    Optional strategy identifier for strategy-aware selection.
        mode:            Execution mode ('paper' | 'live').
        correlation_id:  Caller trace ID for log correlation (auto-generated if omitted).
    """

    tenant_id: str
    user_id: str
    required_usd: float
    strategy_tag: Optional[str] = None
    mode: str = "paper"
    correlation_id: str = field(default_factory=new_routing_id)


@dataclass(frozen=True)
class OrchestrationResult:
    """Result of a wallet routing decision.

    outcome values:
        routed               — a wallet was selected.
        no_candidate         — candidate list was empty or no ownership match.
        no_active_wallet     — all ownership-matched candidates failed lifecycle check.
        insufficient_balance — active wallets exist but none has enough balance.
        risk_blocked         — all funded candidates failed the hard risk gate.
        degraded             — all active candidates have breached the drawdown ceiling
                               (system-wide breach, distinct from per-wallet risk_blocked).
        halted               — routing blocked by PortfolioControlOverlay.global_halt.
        error                — unexpected failure during policy evaluation.
    """

    outcome: str
    selected_wallet_id: Optional[str]
    reason: str
    candidates_evaluated: int
    failover_used: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    routed_at: datetime = field(default_factory=_utc_now)


# ── Phase B domain models (sections 39–40) ───────────────────────────────────

# Risk-state thresholds (derived from portfolio constants — not duplicated here).
# at_risk  : drawdown_pct > MAX_DRAWDOWN * 0.75  (early warning)
# breached : drawdown_pct > MAX_DRAWDOWN          (hard ceiling exceeded)
RISK_STATE_HEALTHY: str = "healthy"
RISK_STATE_AT_RISK: str = "at_risk"
RISK_STATE_BREACHED: str = "breached"


@dataclass(frozen=True)
class WalletHealthStatus:
    """Per-wallet health snapshot produced by CrossWalletStateAggregator.

    Attributes:
        wallet_id:        Wallet identifier.
        lifecycle_status: FSM state string from WalletCandidate.
        is_enabled:       Operator control toggle — False means disabled via WalletControlsStore.
        risk_state:       "healthy" | "at_risk" | "breached" — derived from drawdown_pct.
        drawdown_pct:     Current drawdown fraction at snapshot time.
        exposure_pct:     Current exposure fraction at snapshot time.
        last_updated:     UTC timestamp of this snapshot.
    """

    wallet_id: str
    lifecycle_status: str
    is_enabled: bool
    risk_state: str
    drawdown_pct: float
    exposure_pct: float
    last_updated: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True)
class CrossWalletState:
    """Unified cross-wallet view for a single user produced by CrossWalletStateAggregator.

    Attributes:
        tenant_id:           Tenant ownership scope.
        user_id:             User ownership scope.
        wallet_count:        Total wallets evaluated.
        active_count:        Wallets with lifecycle_status == "active".
        total_exposure_pct:  Sum of (exposure_pct * balance_usd) / total_balance_usd across active wallets.
                             Zero when no active wallets exist.
        max_drawdown_pct:    Highest drawdown_pct across all wallets.
        wallets:             Per-wallet health snapshots (all candidates, not just active).
        has_conflict:        True when total_exposure_pct >= MAX_TOTAL_EXPOSURE_PCT.
        conflict_reasons:    Human-readable conflict descriptions.
        aggregated_at:       UTC timestamp of this aggregation.
    """

    tenant_id: str
    user_id: str
    wallet_count: int
    active_count: int
    total_exposure_pct: float
    max_drawdown_pct: float
    wallets: tuple[WalletHealthStatus, ...]
    has_conflict: bool
    conflict_reasons: tuple[str, ...]
    aggregated_at: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True)
class WalletControlResult:
    """Result of a per-wallet enable/disable action from WalletControlsStore.

    Attributes:
        wallet_id: Target wallet.
        action:    "enable" | "disable".
        success:   Always True for in-memory store (reserved for future DB-backed store).
        reason:    Human-readable outcome description.
    """

    wallet_id: str
    action: str
    success: bool
    reason: str


def new_decision_id() -> str:
    return "dec_" + uuid4().hex


@dataclass(frozen=True)
class OrchestrationDecision:
    """Immutable log record for a completed routing decision.

    Created from OrchestrationResult by the service layer and persisted
    via OrchestrationDecisionStore.

    Attributes:
        decision_id:          Unique identifier for this decision record.
        tenant_id:            Tenant ownership scope.
        user_id:              User ownership scope.
        outcome:              Same outcome string as OrchestrationResult.outcome.
        selected_wallet_id:   Wallet chosen, or None.
        reason:               Human-readable routing reason.
        candidates_evaluated: Number of candidates passed to the policy chain.
        failover_used:        Whether the strategy-only failover path was taken.
        mode:                 Execution mode ('paper' | 'live').
        correlation_id:       Caller trace ID from RoutingRequest.
        decided_at:           UTC timestamp of this decision.
    """

    decision_id: str
    tenant_id: str
    user_id: str
    outcome: str
    selected_wallet_id: Optional[str]
    reason: str
    candidates_evaluated: int
    failover_used: bool
    mode: str
    correlation_id: str
    decided_at: datetime = field(default_factory=_utc_now)


def decision_from_result(
    result: "OrchestrationResult",
    tenant_id: str,
    user_id: str,
    mode: str,
    correlation_id: str,
) -> "OrchestrationDecision":
    """Build an OrchestrationDecision from a completed OrchestrationResult."""
    return OrchestrationDecision(
        decision_id=new_decision_id(),
        tenant_id=tenant_id,
        user_id=user_id,
        outcome=result.outcome,
        selected_wallet_id=result.selected_wallet_id,
        reason=result.reason,
        candidates_evaluated=result.candidates_evaluated,
        failover_used=result.failover_used,
        mode=mode,
        correlation_id=correlation_id,
    )


@dataclass(frozen=True)
class PortfolioControlOverlay:
    """Portfolio-wide control snapshot built by WalletControlsStore.build_overlay().

    Used by WalletOrchestrator as a pre-route hook:
      - global_halt=True  → routing immediately returns outcome="halted" (no policy evaluation).
      - enabled_wallet_ids → candidates not in this set are filtered before policy evaluation.

    Attributes:
        tenant_id:           Tenant ownership scope.
        user_id:             User ownership scope.
        global_halt:         When True, all routing is blocked until cleared.
        halt_reason:         Operator-provided reason for the halt (empty string when not halted).
        enabled_wallet_ids:  Set of wallet_ids currently enabled (per-wallet toggle applied).
    """

    tenant_id: str
    user_id: str
    global_halt: bool
    halt_reason: str
    enabled_wallet_ids: frozenset[str]
