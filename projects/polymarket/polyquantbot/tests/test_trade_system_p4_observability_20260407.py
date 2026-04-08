from __future__ import annotations

import asyncio
import random

import pytest

from projects.polymarket.polyquantbot.core.execution.executor import execute_trade, reset_state
from projects.polymarket.polyquantbot.core.portfolio.pnl import PnLTracker
from projects.polymarket.polyquantbot.core.portfolio.position_manager import PositionManager
from projects.polymarket.polyquantbot.core.signal.signal_engine import SignalResult
from projects.polymarket.polyquantbot.core.wallet_engine import WalletEngine
from projects.polymarket.polyquantbot.execution.event_logger import (
    CANONICAL_OUTCOMES,
    event_logger,
    reconstruct_lifecycle,
)
from projects.polymarket.polyquantbot.execution.trace_context import create_trace_id


@pytest.fixture(autouse=True)
def _clean_observability_state() -> None:
    event_logger.clear()
    reset_state()


def _build_signal(signal_id: str = "sig-1") -> SignalResult:
    return SignalResult(
        signal_id=signal_id,
        market_id="market-1",
        side="YES",
        p_market=0.52,
        p_model=0.61,
        edge=0.09,
        ev=0.04,
        kelly_f=0.03,
        size_usd=25.0,
        liquidity_usd=20_000.0,
        extra={},
    )


def test_trace_id_generated_and_propagated_across_major_lifecycle_stages() -> None:
    random.seed(7)
    trace_id = create_trace_id()

    event_logger.emit(
        event_type="signal_intent_created",
        component="trading_loop",
        outcome="attempted",
        trace_id=trace_id,
        payload={"signal_id": "sig-1", "market_id": "market-1"},
    )

    signal = _build_signal()
    result = asyncio.run(execute_trade(
        signal,
        mode="PAPER",
        min_edge=0.01,
        min_liquidity_usd=0.0,
        max_position_usd=500.0,
        max_concurrent=5,
        trace_id=trace_id,
    ))
    assert result.success is True

    position_manager = PositionManager()
    position_manager.open(
        market_id=result.market_id,
        side=result.side,
        fill_price=result.fill_price,
        fill_size=result.filled_size_usd,
        trade_id=result.trade_id,
        trace_id=trace_id,
    )

    pnl_tracker = PnLTracker()
    pnl_tracker.record_unrealized(result.market_id, 1.25, trace_id=trace_id)

    wallet = WalletEngine(initial_balance=1000.0)
    asyncio.run(wallet.lock_funds(25.0, result.trade_id, trace_id=trace_id))
    asyncio.run(wallet.unlock_funds(25.0, result.trade_id, trace_id=trace_id))
    asyncio.run(wallet.settle_trade(1.25, result.trade_id, trace_id=trace_id))

    lifecycle = reconstruct_lifecycle(trace_id, event_logger.list_events())
    assert lifecycle
    assert all(event.trace_id == trace_id for event in lifecycle)

    components = {event.component for event in lifecycle}
    assert {"trading_loop", "executor", "position_manager", "pnl_tracker", "wallet_engine"}.issubset(
        components
    )


def test_critical_lifecycle_stages_emit_structured_events() -> None:
    trace_id = create_trace_id()
    event_logger.emit(
        event_type="signal_intent_created",
        component="trading_loop",
        outcome="attempted",
        trace_id=trace_id,
        payload={"signal_id": "sig-critical"},
    )

    result = asyncio.run(execute_trade(_build_signal("sig-critical"), mode="PAPER", trace_id=trace_id))
    assert result.success is True

    PositionManager().open(
        "market-1",
        "YES",
        result.fill_price,
        result.filled_size_usd,
        result.trade_id,
        trace_id=trace_id,
    )
    PnLTracker().record_unrealized("market-1", 0.25, trace_id=trace_id)
    wallet = WalletEngine(initial_balance=100.0)
    asyncio.run(wallet.lock_funds(10.0, result.trade_id, trace_id=trace_id))

    lifecycle = reconstruct_lifecycle(trace_id, event_logger.list_events())
    event_types = {event.event_type for event in lifecycle}
    assert {
        "signal_intent_created",
        "risk_decision",
        "execution_attempt",
        "execution_outcome",
        "portfolio_update",
        "wallet_update",
    }.issubset(event_types)


def test_failure_path_emits_structured_failure_event() -> None:
    trace_id = create_trace_id()

    async def _broken_callback(**_: object) -> dict[str, object]:
        raise RuntimeError("executor down")

    signal = _build_signal("sig-failure")
    result = asyncio.run(execute_trade(
        signal,
        mode="LIVE",
        executor_callback=_broken_callback,
        trace_id=trace_id,
    ))

    assert result.success is False
    lifecycle = reconstruct_lifecycle(trace_id, event_logger.list_events())
    failure_events = [event for event in lifecycle if event.outcome == "failed"]
    assert failure_events
    assert any(event.component == "executor" for event in failure_events)


def test_canonical_outcome_taxonomy_enforced() -> None:
    trace_id = create_trace_id()
    with pytest.raises(ValueError):
        event_logger.emit(
            event_type="execution_outcome",
            component="executor",
            outcome="not_canonical",
            trace_id=trace_id,
            payload={},
        )

    assert "failed" in CANONICAL_OUTCOMES


def test_lifecycle_reconstruction_possible_from_emitted_events() -> None:
    trace_id = create_trace_id()
    event_logger.emit(
        event_type="signal_intent_created",
        component="trading_loop",
        outcome="attempted",
        trace_id=trace_id,
        payload={"signal_id": "sig-replay"},
    )

    signal = _build_signal("sig-replay")
    asyncio.run(execute_trade(signal, mode="PAPER", trace_id=trace_id))

    lifecycle = reconstruct_lifecycle(trace_id, event_logger.list_events())
    assert len(lifecycle) >= 4
    assert lifecycle[0].event_type == "signal_intent_created"
    assert lifecycle[-1].event_type in {"execution_outcome", "wallet_update", "portfolio_update"}


def test_touched_critical_paths_do_not_fallback_to_logs_only_observability() -> None:
    trace_id = create_trace_id()

    signal = _build_signal("sig-dup")
    asyncio.run(execute_trade(signal, mode="PAPER", trace_id=trace_id))
    asyncio.run(execute_trade(signal, mode="PAPER", trace_id=trace_id))

    lifecycle = reconstruct_lifecycle(trace_id, event_logger.list_events())
    assert lifecycle
    assert any(event.event_type == "risk_decision" and event.outcome == "skipped" for event in lifecycle)
