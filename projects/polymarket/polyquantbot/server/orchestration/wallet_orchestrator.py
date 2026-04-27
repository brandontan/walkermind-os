"""WalletOrchestrator — Priority 6 Phase A + Phase B + Phase C central routing authority.

Phase A: stateless routing via WalletSelectionPolicy (6-filter chain).
Phase B: optional PortfolioControlOverlay pre-hook — global halt and per-wallet
         disable checks run BEFORE the Phase A filter chain. overlay=None preserves
         100% backward-compatible Phase A behavior.
Phase C: "degraded" outcome distinguishes all-breached wallets (no wallet explicitly
         disabled by operator) from "no_candidate" (empty or fully unowned list).

The orchestrator remains stateless: the service layer fetches WalletCandidate
objects and PortfolioControlOverlay from their respective stores.
"""
from __future__ import annotations

from typing import Optional, Sequence

import structlog

from projects.polymarket.polyquantbot.server.orchestration.schemas import (
    RISK_STATE_BREACHED,
    OrchestrationResult,
    PortfolioControlOverlay,
    RoutingRequest,
    WalletCandidate,
)
from projects.polymarket.polyquantbot.server.orchestration.wallet_selector import WalletSelectionPolicy

log = structlog.get_logger(__name__)


class WalletOrchestrator:
    """Central routing authority for multi-wallet execution requests."""

    def __init__(self, policy: Optional[WalletSelectionPolicy] = None) -> None:
        self._policy = policy or WalletSelectionPolicy()

    async def route(
        self,
        request: RoutingRequest,
        candidates: Sequence[WalletCandidate],
        overlay: Optional[PortfolioControlOverlay] = None,
    ) -> OrchestrationResult:
        """Route an execution request to the best available wallet.

        Phase B pre-hook (runs before Phase A filter chain when overlay is provided):
          1. global_halt=True  → immediately return outcome="halted".
          2. Filter candidates: remove wallet_ids absent from overlay.enabled_wallet_ids.
          3. Pass remaining candidates to Phase A WalletSelectionPolicy unchanged.

        overlay=None skips the pre-hook entirely — Phase A behavior is unchanged.

        Args:
            request:    Routing requirements (ownership scope, amount, strategy, mode).
            candidates: Pre-fetched wallet candidates from the service layer.
            overlay:    Optional portfolio control overlay from WalletControlsStore.

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
            overlay_present=overlay is not None,
            correlation_id=request.correlation_id,
        )

        # ── Phase B pre-hook ──────────────────────────────────────────────────
        if overlay is not None:
            if overlay.global_halt:
                log.warning(
                    "orchestrator_route_halted",
                    halt_reason=overlay.halt_reason,
                    correlation_id=request.correlation_id,
                )
                return OrchestrationResult(
                    outcome="halted",
                    selected_wallet_id=None,
                    reason=f"global halt active: {overlay.halt_reason}",
                    candidates_evaluated=len(candidates),
                )

            original_count = len(candidates)
            candidates = [
                c for c in candidates if c.wallet_id in overlay.enabled_wallet_ids
            ]
            if len(candidates) < original_count:
                log.info(
                    "orchestrator_candidates_filtered_by_overlay",
                    original_count=original_count,
                    remaining_count=len(candidates),
                    correlation_id=request.correlation_id,
                )

        # ── Phase C: degraded-mode detection ─────────────────────────────────
        # When all active candidates have breached the drawdown ceiling, surface
        # "degraded" so operators can distinguish system-wide risk breach from
        # individual wallet policy blocks (risk_blocked).
        from projects.polymarket.polyquantbot.server.schemas.portfolio import MAX_DRAWDOWN  # local import avoids circular dep at module level
        active_candidates = [c for c in candidates if c.lifecycle_status == "active"]
        if active_candidates and all(c.drawdown_pct > MAX_DRAWDOWN for c in active_candidates):
            log.warning(
                "orchestrator_route_degraded",
                active_count=len(active_candidates),
                max_drawdown_threshold=MAX_DRAWDOWN,
                correlation_id=request.correlation_id,
            )
            return OrchestrationResult(
                outcome="degraded",
                selected_wallet_id=None,
                reason=f"all {len(active_candidates)} active wallet(s) have breached drawdown ceiling ({MAX_DRAWDOWN})",
                candidates_evaluated=len(candidates),
            )

        # ── Phase A filter chain ──────────────────────────────────────────────
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
