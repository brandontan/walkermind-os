from __future__ import annotations

import asyncio
from types import SimpleNamespace

from projects.polymarket.polyquantbot.core.execution.executor import execute_trade
from projects.polymarket.polyquantbot.core.portfolio.position_manager import PositionManager
from projects.polymarket.polyquantbot.execution.engine_router import EngineContainer
from projects.polymarket.polyquantbot.execution.event_logger import get_event_logger
from projects.polymarket.polyquantbot.execution.trace_context import create_trace_id


def _signal(signal_id: str = "sig-1") -> SimpleNamespace:
    return SimpleNamespace(
        signal_id=signal_id,
        market_id="market-1",
        side="YES",
        p_market=0.55,
        p_model=0.62,
        edge=0.07,
        ev=0.1,
        kelly_f=0.1,
        size_usd=25.0,
        liquidity_usd=50000.0,
        force_mode=False,
        extra={},
    )


def test_trace_id_propagation_and_lifecycle_replay() -> None:
    event_logger = get_event_logger()
    event_logger.clear()
    trace_id = create_trace_id()

    async def _run() -> object:
        async def _ok_callback(**_: object) -> dict[str, float]:
            return {"filled_size": 25.0, "fill_price": 0.56}

        return await execute_trade(
            _signal(),
            mode="LIVE",
            executor_callback=_ok_callback,
            trace_id=trace_id,
        )

    result = asyncio.run(_run())
    assert result.success is True
    assert result.extra["trace_id"] == trace_id

    PositionManager().open(
        market_id=result.market_id,
        side=result.side,
        fill_price=result.fill_price,
        fill_size=result.filled_size_usd,
        trade_id=result.trade_id,
        trace_id=trace_id,
    )

    replay = event_logger.replay(trace_id)
    event_types = {event["event_type"] for event in replay}
    components = {event["component"] for event in replay}

    assert {"signal", "execution", "outcome", "portfolio"}.issubset(event_types)
    assert {"executor", "position_manager"}.issubset(components)


def test_engine_router_emits_traceable_risk_event() -> None:
    event_logger = get_event_logger()
    event_logger.clear()
    trace_id = create_trace_id()

    container = EngineContainer()
    order = {
        "trade_id": "trade-1",
        "trace_id": trace_id,
        "market_id": "market-guard",
        "side": "YES",
        "price": 0.5,
        "size": 1_000_000.0,
    }
    result = asyncio.run(container.paper_engine.execute_order(order))

    assert result.status.value.lower() == "rejected"
    replay = event_logger.replay(trace_id)
    assert any(
        event["component"] == "engine_router"
        and event["event_type"] == "risk"
        and event["payload"].get("outcome") == "blocked"
        for event in replay
    )


def test_failure_logging_is_structured_and_non_silent() -> None:
    event_logger = get_event_logger()
    event_logger.clear()
    trace_id = create_trace_id()

    async def _failing_callback(**_: object) -> dict[str, object]:
        raise RuntimeError("broker down")

    async def _run() -> object:
        return await execute_trade(
            _signal("sig-fail"),
            mode="LIVE",
            executor_callback=_failing_callback,
            trace_id=trace_id,
        )

    result = asyncio.run(_run())

    assert result.success is False
    replay = event_logger.replay(trace_id)
    failure_events = [e for e in replay if e["event_type"] == "failure"]
    assert failure_events
    assert failure_events[0]["payload"]["error_type"] == "RuntimeError"


def test_outcome_taxonomy_enforced() -> None:
    event_logger = get_event_logger()
    event_logger.clear()
    trace_id = create_trace_id()

    event_logger.emit(
        trace_id=trace_id,
        event_type="outcome",
        component="test",
        payload={"outcome": "executed"},
    )

    replay = event_logger.replay(trace_id)
    assert replay and replay[0]["payload"]["outcome"] == "executed"
