"""
Centralized execution entry gateway for all trade requests.

This module enforces that all execution requests (strategy-trigger, manual, retry, scheduler)
must pass through a single validated path before reaching the execution engine.
"""

from __future__ import annotations

import structlog
from typing import Any, Optional

from .engine import ExecutionEngine
from ..core.risk.pre_trade_validator import PreTradeValidator

log = structlog.get_logger(__name__)


class ExecutionGateway:
    """
    Centralized gateway for all execution requests.
    
    Attributes:
        _engine: The execution engine instance.
        _validator: The pre-trade validator instance.
    """

    def __init__(self, engine: ExecutionEngine) -> None:
        self._engine = engine
        self._validator = PreTradeValidator()

    async def submit_execution_request(
        self,
        market: str,
        market_title: str,
        side: str,
        price: float,
        size: float,
        position_id: Optional[str] = None,
        position_context: Optional[dict[str, Any]] = None,
        source: str = "strategy_trigger",
    ) -> Optional[Any]:
        """
        Submit an execution request through the centralized gateway.
        
        Args:
            market: The market ID.
            market_title: The market title.
            side: The trade side (YES/NO).
            price: The execution price.
            size: The position size.
            position_id: Optional position ID.
            position_context: Optional context for the position.
            source: The source of the request.

        Returns:
            The result of the execution request, or None if blocked.
        """
        log.info("execution_gateway_request_received", source=source, market=market, side=side)

        # Step 1: Validate the request with the pre-trade validator
        validation_result = self._validator.validate(
            market=market,
            side=side,
            price=price,
            size=size,
            source=source,
        )

        if not validation_result.is_valid:
            log.warning(
                "execution_gateway_request_blocked",
                reason=validation_result.reason,
                source=source,
                market=market,
                side=side,
            )
            return None

        # Step 2: Forward the validated request to the execution engine
        log.info("execution_gateway_request_forwarded", source=source, market=market, side=side)
        return await self._engine.open_position(
            market=market,
            market_title=market_title,
            side=side,
            price=price,
            size=size,
            position_id=position_id,
            position_context=position_context,
        )

    async def close_position(
        self,
        position: Any,
        price: float,
        close_context: Optional[dict[str, Any]] = None,
    ) -> float:
        """
        Close a position through the gateway.
        
        Args:
            position: The position to close.
            price: The closing price.
            close_context: Optional context for the close.

        Returns:
            The realized PnL.
        """
        log.info("execution_gateway_close_request", market=position.market_id, side=position.side)
        return await self._engine.close_position(
            position=position,
            price=price,
            close_context=close_context,
        )


def get_execution_gateway() -> ExecutionGateway:
    """
    Get the singleton instance of the execution gateway.
    
    Returns:
        The singleton ExecutionGateway instance.
    """
    from .engine import get_execution_engine
    engine = get_execution_engine()
    if not hasattr(engine, "_gateway"):
        engine._gateway = ExecutionGateway(engine)  # type: ignore
    return engine._gateway  # type: ignore