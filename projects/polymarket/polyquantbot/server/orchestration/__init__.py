"""server.orchestration — Priority 6 Multi-Wallet Orchestration.

Phase A exports: orchestration domain types and wallet routing authority.
Phase B exports: cross-wallet aggregation, control store, and overlay types.
"""
from server.orchestration.cross_wallet_aggregator import CrossWalletStateAggregator
from server.orchestration.schemas import (
    RISK_STATE_AT_RISK,
    RISK_STATE_BREACHED,
    RISK_STATE_HEALTHY,
    CrossWalletState,
    OrchestrationResult,
    PortfolioControlOverlay,
    RoutingRequest,
    WalletCandidate,
    WalletControlResult,
    WalletHealthStatus,
    new_routing_id,
)
from server.orchestration.wallet_controls import WalletControlsStore
from server.orchestration.wallet_orchestrator import WalletOrchestrator
from server.orchestration.wallet_selector import WalletSelectionPolicy

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
]
