from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from ..core.risk.pre_trade_validator import PreTradeValidator
from ..core.risk.risk_engine import RiskEngine
from .engine import ExecutionEngine, execution_gateway_context
from .models import Position

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class GatewayExecutionResult:
    position: Position | None
    validation_decision: str
    validation_reason: str
    validation_checks: dict[str, bool]


class ExecutionGateway:
    """Centralized execution entry gateway for opening new positions."""

    def __init__(
        self,
        *,
        engine: ExecutionEngine,
        pre_trade_validator: PreTradeValidator,
        risk_engine: RiskEngine,
    ) -> None:
        self._engine = engine
        self._pre_trade_validator = pre_trade_validator
        self._risk_engine = risk_engine

    async def open_validated_position(
        self,
        *,
        market: str,
        market_title: str,
        side: str,
        price: float,
        size: float,
        signal_data: dict[str, Any],
        decision_data: dict[str, Any],
        position_id: str | None = None,
        position_context: dict[str, Any] | None = None,
    ) -> GatewayExecutionResult:
        validation = self._pre_trade_validator.validate(
            signal_data=signal_data,
            decision_data=decision_data,
            risk_state=self._risk_engine.as_dict(),
        )
        if validation.decision != "ALLOW":
            log.info(
                "execution_gateway_blocked",
                decision=validation.decision,
                reason=validation.reason,
                market=market,
            )
            return GatewayExecutionResult(
                position=None,
                validation_decision=validation.decision,
                validation_reason=validation.reason,
                validation_checks=validation.checks,
            )

        with execution_gateway_context():
            created = await self._engine.open_position(
                market=market,
                market_title=market_title,
                side=side,
                price=price,
                size=size,
                position_id=position_id,
                position_context=position_context,
            )
        return GatewayExecutionResult(
            position=created,
            validation_decision=validation.decision,
            validation_reason=validation.reason,
            validation_checks=validation.checks,
        )
