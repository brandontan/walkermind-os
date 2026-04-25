"""WalletOrchestrator — Priority 6 Phase A central routing authority.

The orchestrator is intentionally stateless: it receives a pre-built list of
WalletCandidate objects and delegates selection to WalletSelectionPolicy.
The service layer (built in Phase B/C) is responsible for fetching candidates
from the DB and converting them to WalletCandidate domain objects.

This separation keeps the orchestrator fully unit-testable without DB fixtures.
"""
from __future__ import annotations

from typing import Optional, Sequence

import structlog

from server.orchestration.schemas import OrchestrationResult, RoutingRequest, WalletCandidate
from server.orchestration.wallet_selector import WalletSelectionPolicy

log = structlog.get_logger(__name__)


class WalletOrchestrator:
    """Central routing authority for multi-wallet execution requests."""

    def __init__(self, policy: Optional[WalletSelectionPolicy] = None) -> None:
        self._policy = policy or WalletSelectionPolicy()

    async def route(
        self,
        request: RoutingRequest,
        candidates: Sequence[WalletCandidate],
    ) -> OrchestrationResult:
        """Route an execution request to the best available wallet.

        Args:
            request:    Routing requirements (ownership scope, amount, strategy, mode).
            candidates: Pre-fetched wallet candidates from the service layer.

        Returns:
            OrchestrationResult with outcome, selected_wallet_id, and diagnostics.
        """
        log.info(
            "orchestrator_route_start",
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            required_usd=request.required_usd,
            strategy_tag=request.strategy_tag,
            mode=request.mode,
            candidate_count=len(candidates),
            correlation_id=request.correlation_id,
        )

        try:
            result = self._policy.select(request, candidates)
        except Exception as exc:
            log.error(
                "orchestrator_route_error",
                error=str(exc),
                correlation_id=request.correlation_id,
            )
            return OrchestrationResult(
                outcome="error",
                selected_wallet_id=None,
                reason=f"policy raised unexpected error: {exc}",
                candidates_evaluated=len(candidates),
            )

        log.info(
            "orchestrator_route_done",
            outcome=result.outcome,
            selected_wallet_id=result.selected_wallet_id,
            failover_used=result.failover_used,
            correlation_id=request.correlation_id,
        )
        return result
