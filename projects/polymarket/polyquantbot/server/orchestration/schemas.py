"""Orchestration domain model — Priority 6 Phase A foundation.

Covers sections 37–38 of WORKTODO.md:
  37. Orchestration model (routing model, wallet selection, ownership-aware routing)
  38. Allocation across wallets (balance-aware, strategy-aware, risk-aware, failover)
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
        error                — unexpected failure during policy evaluation.
    """

    outcome: str
    selected_wallet_id: Optional[str]
    reason: str
    candidates_evaluated: int
    failover_used: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    routed_at: datetime = field(default_factory=_utc_now)
