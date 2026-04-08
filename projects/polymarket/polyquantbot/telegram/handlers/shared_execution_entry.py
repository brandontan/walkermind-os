from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from ...execution.engine import export_execution_payload, get_execution_engine
import uuid
from .portfolio_service import get_portfolio_service

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class UnifiedTradeRequest:
    market: str
    side: str
    size: float


@dataclass(frozen=True)
class UnifiedTradeResult:
    success: bool
    message: str
    payload: dict[str, Any]


def parse_trade_test_args(args: str) -> UnifiedTradeRequest:
    """Parse ``/trade test`` args into a validated request."""
    if not args:
        raise ValueError("Usage: /trade test [market] [side YES/NO] [size]")
    parts = args.split()
    if len(parts) < 3:
        raise ValueError("Usage: /trade test [market] [side YES/NO] [size]")

    market = str(parts[0]).strip()
    side = str(parts[1]).upper().strip()
    size_raw = str(parts[2]).strip()

    if not market:
        raise ValueError("Market is required.")
    if side not in ("YES", "NO"):
        raise ValueError("Side must be YES or NO.")

    try:
        size = float(size_raw)
    except ValueError as exc:
        raise ValueError("Size must be a number.") from exc

    if size <= 0:
        raise ValueError("Size must be greater than zero.")

    return UnifiedTradeRequest(market=market, side=side, size=size)


def parse_trade_payload(payload: dict[str, Any]) -> UnifiedTradeRequest:
    """Parse callback payload into the same unified trade contract."""
    market = str(payload.get("market", "")).strip()
    side = str(payload.get("side", "")).upper().strip()
    size_value = payload.get("size")

    if not market:
        raise ValueError("Invalid payload: market is required.")
    if side not in ("YES", "NO"):
        raise ValueError("Invalid payload: side must be YES or NO.")

    try:
        size = float(size_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid payload: size must be numeric.") from exc

    if size <= 0:
        raise ValueError("Invalid payload: size must be greater than zero.")

    return UnifiedTradeRequest(market=market, side=side, size=size)


async def execute_unified_trade_entry(request: UnifiedTradeRequest, source: str) -> UnifiedTradeResult:
    """Single execution entry used by both command and callback trade paths."""
    log.info(
        "unified_execution_entry_invoked",
        source=source,
        function="execute_unified_trade_entry",
        market=request.market,
        side=request.side,
        size=request.size,
    )

    engine = get_execution_engine()
    snapshot = await engine.snapshot()
    duplicate = next(
        (
            pos
            for pos in snapshot.positions
            if pos.market_id == request.market and str(pos.side).upper() == request.side
        ),
        None,
    )
    if duplicate is not None:
        log.warning(
            "unified_execution_duplicate_blocked",
            source=source,
            market=request.market,
            side=request.side,
        )
        payload = await export_execution_payload()
        return UnifiedTradeResult(
            success=False,
            message=f"Duplicate trade blocked for {request.market} {request.side}.",
            payload=payload,
        )

    try:
        position = await engine.open_position(
            market=request.market,
            side=request.side,
            price=0.42,
            size=request.size,
            position_id=f"{request.market}-{uuid.uuid4()}",
        )
        if position is None:
            payload = await export_execution_payload()
            return UnifiedTradeResult(
                success=False,
                message="Trade blocked by execution risk checks.",
                payload=payload,
            )

        await engine.update_mark_to_market({request.market: 0.46})
        payload = await export_execution_payload()
        get_portfolio_service().merge_execution_state(
            positions=payload.get("positions", []),
            cash=float(payload.get("cash", 0.0)),
            equity=float(payload.get("equity", 0.0)),
            realized_pnl=float(payload.get("realized", 0.0)),
        )
    except Exception as exc:  # noqa: BLE001
        log.error(
            "unified_execution_failed",
            source=source,
            market=request.market,
            side=request.side,
            error=str(exc),
            exc_info=True,
        )
        payload = await export_execution_payload()
        return UnifiedTradeResult(
            success=False,
            message=f"Trade execution failed: {exc}",
            payload=payload,
        )

    log.info(
        "unified_execution_entry_completed",
        source=source,
        function="execute_unified_trade_entry",
        market=request.market,
        side=request.side,
    )
    return UnifiedTradeResult(success=True, message="Paper trade executed.", payload=payload)
