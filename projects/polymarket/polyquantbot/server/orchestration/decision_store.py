"""OrchestrationDecisionStore — Priority 6 Phase C (section 42).

Thin async persistence layer for orchestration routing decisions.
Follows the same fail-safe pattern as WalletLifecycleStore and
SettlementPersistence: exceptions are caught and logged; callers
must not assume writes succeed.
"""
from __future__ import annotations

from datetime import timezone
from typing import TYPE_CHECKING, Any

import structlog

from projects.polymarket.polyquantbot.server.orchestration.schemas import OrchestrationDecision

if TYPE_CHECKING:
    from projects.polymarket.polyquantbot.infra.db import DatabaseClient

log = structlog.get_logger(__name__)

_INSERT_SQL = """
    INSERT INTO orchestration_decisions (
        decision_id, tenant_id, user_id, outcome,
        selected_wallet_id, reason, candidates_evaluated,
        failover_used, mode, correlation_id, decided_at
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
    ON CONFLICT (decision_id) DO NOTHING
"""

_SELECT_RECENT_SQL = """
    SELECT decision_id, tenant_id, user_id, outcome,
           selected_wallet_id, reason, candidates_evaluated,
           failover_used, mode, correlation_id, decided_at
    FROM orchestration_decisions
    WHERE tenant_id = $1 AND user_id = $2
    ORDER BY decided_at DESC
    LIMIT $3
"""


class OrchestrationDecisionStore:
    """PostgreSQL-backed append-only log for orchestration decisions.

    Args:
        db: DatabaseClient instance (pool must already be connected).
    """

    def __init__(self, db: "DatabaseClient") -> None:
        self._db = db

    async def append(self, decision: OrchestrationDecision) -> bool:
        """Persist a routing decision.  Idempotent: ON CONFLICT DO NOTHING.

        Returns:
            True on success or duplicate skip, False on DB error.
        """
        decided_at = decision.decided_at
        if decided_at.tzinfo is None:
            decided_at = decided_at.replace(tzinfo=timezone.utc)

        ok = await self._db._execute(
            _INSERT_SQL,
            decision.decision_id,
            decision.tenant_id,
            decision.user_id,
            decision.outcome,
            decision.selected_wallet_id,
            decision.reason,
            decision.candidates_evaluated,
            decision.failover_used,
            decision.mode,
            decision.correlation_id,
            decided_at,
            op_label="orchestration_decision_append",
        )
        if ok:
            log.debug(
                "orchestration_decision_persisted",
                decision_id=decision.decision_id,
                outcome=decision.outcome,
            )
        return ok

    async def load_recent(
        self,
        tenant_id: str,
        user_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Load recent routing decisions for a user.

        Returns:
            List of decision dicts ordered by decided_at DESC.
            Empty list on DB error (fail-safe).
        """
        rows = await self._db._fetch(
            _SELECT_RECENT_SQL,
            tenant_id,
            user_id,
            limit,
            op_label="orchestration_decision_load_recent",
        )
        result = []
        for row in rows:
            d = dict(row)
            if hasattr(d.get("decided_at"), "isoformat"):
                d["decided_at"] = d["decided_at"].isoformat()
            result.append(d)
        return result
