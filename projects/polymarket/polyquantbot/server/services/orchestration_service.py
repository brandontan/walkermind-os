"""OrchestratorService — Priority 6 Phase C (sections 41–42).

Service layer that wires together:
  - WalletLifecycleStore      → fetches WalletCandidate objects from PostgreSQL
  - WalletControlsStore       → builds PortfolioControlOverlay; DB-backed persist/load
  - CrossWalletStateAggregator → produces CrossWalletState for admin visibility
  - WalletOrchestrator        → routes execution requests
  - OrchestrationDecisionStore → persists routing decisions
  - WalletFinancialProvider   → optional P8-B wiring for financial field enrichment

Financial fields (balance_usd, exposure_pct, drawdown_pct) on WalletCandidate
default to 0.0 when no provider is injected.  Inject a WalletFinancialProvider
via the constructor to enable live financial field enrichment.  A live-data
provider implementation is a P8-C deliverable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import structlog

from projects.polymarket.polyquantbot.infra.db import DatabaseClient
from projects.polymarket.polyquantbot.server.orchestration.cross_wallet_aggregator import (
    CrossWalletStateAggregator,
)
from projects.polymarket.polyquantbot.server.orchestration.decision_store import (
    OrchestrationDecisionStore,
)
from projects.polymarket.polyquantbot.server.orchestration.schemas import (
    CrossWalletState,
    OrchestrationResult,
    PortfolioControlOverlay,
    RoutingRequest,
    WalletCandidate,
    WalletControlResult,
    decision_from_result,
)
from projects.polymarket.polyquantbot.server.risk.capital_risk_gate import (
    WalletFinancialProvider,
    enrich_candidate,
)
from projects.polymarket.polyquantbot.server.orchestration.wallet_controls import (
    WalletControlsStore,
)
from projects.polymarket.polyquantbot.server.orchestration.wallet_orchestrator import (
    WalletOrchestrator,
)
from projects.polymarket.polyquantbot.server.schemas.wallet_lifecycle import (
    WalletLifecycleRecord,
    WalletLifecycleStatus,
)
from projects.polymarket.polyquantbot.server.storage.wallet_lifecycle_store import (
    WalletLifecycleStore,
)

log = structlog.get_logger(__name__)


@dataclass
class RouteResult:
    """Outcome of OrchestratorService.route()."""

    result: OrchestrationResult
    decision_persisted: bool


def _record_to_candidate(
    record: WalletLifecycleRecord,
    provider: Optional[WalletFinancialProvider] = None,
) -> WalletCandidate:
    """Convert a lifecycle record to a routing candidate.

    When provider is None financial fields default to 0.0 (paper mode safe).
    When provider is given the candidate is enriched with live financial data.
    """
    candidate = WalletCandidate(
        wallet_id=record.wallet_id,
        tenant_id=record.tenant_id,
        user_id=record.user_id,
        lifecycle_status=record.status.value if hasattr(record.status, "value") else str(record.status),
        balance_usd=0.0,
        exposure_pct=0.0,
        drawdown_pct=0.0,
        strategy_tags=frozenset(),
        is_primary=True,
    )
    if provider is not None:
        return enrich_candidate(candidate, provider)
    return candidate


class OrchestratorService:
    """Service layer for multi-wallet orchestration (Phase C).

    All state mutations (enable/disable/halt) are persisted to PostgreSQL
    immediately after the in-memory update.  Candidates are loaded from
    the wallet_lifecycle table on every route/aggregate call — no local cache.

    Args:
        lifecycle_store:  WalletLifecycleStore instance (DB must be connected).
        controls_store:   WalletControlsStore instance (in-memory + DB-backed).
        decision_store:   OrchestrationDecisionStore instance.
        aggregator:       CrossWalletStateAggregator instance.
        orchestrator:     WalletOrchestrator instance.
        db:               DatabaseClient for controls persistence.
    """

    def __init__(
        self,
        lifecycle_store: WalletLifecycleStore,
        controls_store: WalletControlsStore,
        decision_store: OrchestrationDecisionStore,
        aggregator: CrossWalletStateAggregator,
        orchestrator: WalletOrchestrator,
        db: DatabaseClient,
        financial_provider: Optional[WalletFinancialProvider] = None,
    ) -> None:
        self._lifecycle_store = lifecycle_store
        self._controls_store = controls_store
        self._decision_store = decision_store
        self._aggregator = aggregator
        self._orchestrator = orchestrator
        self._db = db
        self._financial_provider = financial_provider

    # ── Routing ───────────────────────────────────────────────────────────────

    async def route(self, request: RoutingRequest) -> RouteResult:
        """Route an execution request through the full orchestration stack.

        Fetches candidates from DB, builds overlay from controls store,
        calls WalletOrchestrator.route(), and persists the decision.

        Args:
            request: RoutingRequest with tenant/user scope, amount, strategy, mode.

        Returns:
            RouteResult with the OrchestrationResult and whether the decision was persisted.
        """
        candidates = await self._load_candidates(request.tenant_id, request.user_id)
        overlay = self._controls_store.build_overlay(
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            candidates=candidates,
        )
        result = await self._orchestrator.route(
            request=request,
            candidates=candidates,
            overlay=overlay,
        )
        decision = decision_from_result(
            result=result,
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            mode=request.mode,
            correlation_id=request.correlation_id,
        )
        persisted = await self._decision_store.append(decision)
        log.info(
            "orchestrator_service_route_done",
            outcome=result.outcome,
            selected_wallet_id=result.selected_wallet_id,
            decision_persisted=persisted,
        )
        return RouteResult(result=result, decision_persisted=persisted)

    # ── Cross-wallet state ────────────────────────────────────────────────────

    async def aggregate(self, tenant_id: str, user_id: str) -> CrossWalletState:
        """Return the current unified cross-wallet health snapshot.

        Args:
            tenant_id: Tenant scope.
            user_id:   User scope.

        Returns:
            CrossWalletState with per-wallet health status and portfolio metrics.
        """
        candidates = await self._load_candidates(tenant_id, user_id)
        overlay = self._controls_store.build_overlay(
            tenant_id=tenant_id,
            user_id=user_id,
            candidates=candidates,
        )
        return await self._aggregator.aggregate(
            tenant_id=tenant_id,
            user_id=user_id,
            candidates=candidates,
            enabled_wallet_ids=overlay.enabled_wallet_ids,
        )

    # ── Control mutations (persist on every change) ───────────────────────────

    async def enable_wallet(
        self,
        tenant_id: str,
        user_id: str,
        wallet_id: str,
    ) -> tuple[WalletControlResult, bool]:
        """Enable a wallet and persist the updated control state.

        Returns:
            (WalletControlResult, persist_ok) — persist_ok is False when the DB
            write failed; in-memory state is always updated regardless.
        """
        result = self._controls_store.enable_wallet(wallet_id)
        persist_ok = await self._controls_store.persist(self._db, tenant_id, user_id)
        if not persist_ok:
            log.warning("orchestrator_service_enable_wallet_persist_failed", wallet_id=wallet_id)
        return result, persist_ok

    async def disable_wallet(
        self,
        tenant_id: str,
        user_id: str,
        wallet_id: str,
        reason: str = "",
    ) -> tuple[WalletControlResult, bool]:
        """Disable a wallet and persist the updated control state.

        Returns:
            (WalletControlResult, persist_ok) — persist_ok is False when the DB
            write failed; in-memory state is always updated regardless.
        """
        result = self._controls_store.disable_wallet(wallet_id, reason=reason)
        persist_ok = await self._controls_store.persist(self._db, tenant_id, user_id)
        if not persist_ok:
            log.warning("orchestrator_service_disable_wallet_persist_failed", wallet_id=wallet_id)
        return result, persist_ok

    async def set_global_halt(
        self,
        tenant_id: str,
        user_id: str,
        reason: str,
    ) -> bool:
        """Set global halt and persist.

        Returns:
            True if persisted successfully, False if DB write failed.
        """
        self._controls_store.set_global_halt(reason)
        persist_ok = await self._controls_store.persist(self._db, tenant_id, user_id)
        if not persist_ok:
            log.warning("orchestrator_service_set_halt_persist_failed")
        return persist_ok

    async def clear_global_halt(self, tenant_id: str, user_id: str) -> bool:
        """Clear global halt and persist.

        Returns:
            True if persisted successfully, False if DB write failed.
        """
        self._controls_store.clear_global_halt()
        persist_ok = await self._controls_store.persist(self._db, tenant_id, user_id)
        if not persist_ok:
            log.warning("orchestrator_service_clear_halt_persist_failed")
        return persist_ok

    # ── Audit log ─────────────────────────────────────────────────────────────

    async def recent_decisions(
        self,
        tenant_id: str,
        user_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return recent routing decisions from the DB log."""
        return await self._decision_store.load_recent(tenant_id, user_id, limit)

    # ── Bootstrap ─────────────────────────────────────────────────────────────

    async def load_controls_from_db(self, tenant_id: str, user_id: str) -> None:
        """Restore persisted control state into the in-memory store.

        Should be called during server startup after DB connects.
        """
        await self._controls_store.load(self._db, tenant_id, user_id)
        log.info(
            "orchestrator_service_controls_loaded",
            tenant_id=tenant_id,
            user_id=user_id,
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _load_candidates(
        self,
        tenant_id: str,
        user_id: str,
    ) -> list[WalletCandidate]:
        """Fetch all wallets for (tenant_id, user_id) and convert to candidates.

        If a WalletFinancialProvider was injected at construction, each candidate
        is enriched with live financial data before routing evaluation.
        """
        records = await self._lifecycle_store.list_wallets_for_user(tenant_id, user_id)
        return [_record_to_candidate(r, self._financial_provider) for r in records]
