from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import structlog

from .engine import ExecutionEngine, Position, ValidationProof, get_execution_engine

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ExecutionIsolationOutcome:
    allowed: bool
    reason: str
    source_path: str
    position: Position | None = None
    realized_pnl: float | None = None
    details: dict[str, Any] | None = None


class ExecutionIsolationGateway:
    """Single authoritative mutation boundary for execution runtime state."""

    def __init__(self, engine: ExecutionEngine) -> None:
        self._engine = engine
        self._open_lock = asyncio.Lock()

    @property
    def engine(self) -> ExecutionEngine:
        return self._engine

    async def open_position(
        self,
        *,
        source_path: str,
        market: str,
        market_title: str,
        side: str,
        price: float,
        size: float,
        position_id: str | None,
        position_context: dict[str, Any],
        execution_market_data: dict[str, Any],
        validation_proof: ValidationProof | None,
        risk_decision: str,
        risk_reason: str,
    ) -> ExecutionIsolationOutcome:
        if risk_decision != "ALLOW":
            return self._block(
                source_path=source_path,
                reason="risk_decision_not_allow",
                details={"risk_decision": risk_decision, "risk_reason": risk_reason},
            )
        if not isinstance(validation_proof, ValidationProof):
            return self._block(
                source_path=source_path,
                reason="validation_proof_required",
                details={"risk_decision": risk_decision},
            )

        async with self._open_lock:
            opened = await self._engine.open_position(
                market=market,
                market_title=market_title,
                side=side,
                price=price,
                size=size,
                position_id=position_id,
                position_context=position_context,
                validation_proof=validation_proof,
                execution_market_data=execution_market_data,
            )
            rejection = self._engine.get_last_open_rejection() or {}
            if opened is None:
                return self._block(
                    source_path=source_path,
                    reason=str(rejection.get("reason", "execution_open_rejected")),
                    details={"engine_rejection": rejection},
                )

        log.info(
            "execution_isolation_decision",
            source_path=source_path,
            action="open",
            outcome="allow",
            reason="opened",
            market=market,
            position_id=opened.position_id,
        )
        return ExecutionIsolationOutcome(
            allowed=True,
            reason="opened",
            source_path=source_path,
            position=opened,
            details={"market": market, "position_id": opened.position_id},
        )

    async def close_position(
        self,
        *,
        source_path: str,
        position: Position,
        close_price: float,
        close_context: dict[str, Any],
        terminal_reason: str,
    ) -> ExecutionIsolationOutcome:
        resolved_terminal_reason = terminal_reason.strip()
        if not resolved_terminal_reason:
            return self._block(
                source_path=source_path,
                reason="terminal_reason_required",
                details={"action": "close"},
            )

        enriched_close_context = dict(close_context)
        enriched_close_context.setdefault("terminal_reason", resolved_terminal_reason)
        realized = await self._engine.close_position(
            position,
            close_price,
            close_context=enriched_close_context,
        )
        log.info(
            "execution_isolation_decision",
            source_path=source_path,
            action="close",
            outcome="allow",
            reason=resolved_terminal_reason,
            market=position.market_id,
            position_id=position.position_id,
            realized_pnl=realized,
        )
        return ExecutionIsolationOutcome(
            allowed=True,
            reason=resolved_terminal_reason,
            source_path=source_path,
            realized_pnl=realized,
            details={"market": position.market_id, "position_id": position.position_id},
        )

    def _block(self, *, source_path: str, reason: str, details: dict[str, Any]) -> ExecutionIsolationOutcome:
        log.warning(
            "execution_isolation_decision",
            source_path=source_path,
            action="mutate",
            outcome="block",
            reason=reason,
            details=details,
        )
        return ExecutionIsolationOutcome(
            allowed=False,
            reason=reason,
            source_path=source_path,
            details=details,
        )


_gateway_singleton: ExecutionIsolationGateway | None = None


def get_execution_isolation_gateway(engine: ExecutionEngine | None = None) -> ExecutionIsolationGateway:
    global _gateway_singleton  # noqa: PLW0603
    resolved_engine = engine or get_execution_engine()
    if _gateway_singleton is None or _gateway_singleton.engine is not resolved_engine:
        _gateway_singleton = ExecutionIsolationGateway(engine=resolved_engine)
    return _gateway_singleton
