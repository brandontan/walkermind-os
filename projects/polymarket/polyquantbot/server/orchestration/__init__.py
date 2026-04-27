"""server.orchestration — Priority 6 Multi-Wallet Orchestration.

Phase A exports: orchestration domain types and wallet routing authority.
Phase B exports: cross-wallet aggregation, control store, and overlay types.
Phase C exports: decision log schema + store, DB-backed controls persistence.
"""
from projects.polymarket.polyquantbot.server.orchestration.cross_wallet_aggregator import CrossWalletStateAggregator
from projects.polymarket.polyquantbot.server.orchestration.decision_store import OrchestrationDecisionStore
from projects.polymarket.polyquantbot.server.orchestration.schemas import (
    RISK_STATE_AT_RISK,
    RISK_STATE_BREACHED,
    RISK_STATE_HEALTHY,
    CrossWalletState,
    OrchestrationDecision,
    OrchestrationResult,
    PortfolioControlOverlay,
    RoutingRequest,
    WalletCandidate,
    WalletControlResult,
    WalletHealthStatus,
    decision_from_result,
    new_decision_id,
    new_routing_id,
)
from projects.polymarket.polyquantbot.server.orchestration.wallet_controls import WalletControlsStore
from projects.polymarket.polyquantbot.server.orchestration.wallet_orchestrator import WalletOrchestrator
from projects.polymarket.polyquantbot.server.orchestration.wallet_selector import WalletSelectionPolicy


__all__ = [
    # Phase A
    "OrchestrationResult",
    "RoutingRequest",
    "WalletCandidate",
    "WalletOrchestrator",
    "WalletSelectionPolicy",
    "new_routing_id",
    # Phase B
    "CrossWalletState",
    "CrossWalletStateAggregator",
    "PortfolioControlOverlay",
    "RISK_STATE_AT_RISK",
    "RISK_STATE_BREACHED",
    "RISK_STATE_HEALTHY",
    "WalletControlResult",
    "WalletControlsStore",
    "WalletHealthStatus",
    # Phase C
    "OrchestrationDecision",
    "OrchestrationDecisionStore",
    "decision_from_result",
    "new_decision_id",
]
