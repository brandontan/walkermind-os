"""Event pipeline handlers — one per stage of the trading flow."""
from __future__ import annotations

import time
from typing import Any

import structlog

from ..core.risk_manager import RiskManager
from ..core.signal_model import BayesianSignalModel
from ..core.execution.paper_executor import PaperExecutor
from .circuit_breaker import CircuitBreaker
from .event_bus import (
    FILTERED_SIGNAL,
    MARKET_DATA,
    ORDER_FILLED,
    POSITION_SIZED,
    SIGNAL,
    STATE_UPDATED,
    SYSTEM_ERROR,
    EventBus,
    EventEnvelope,
)
from .state_manager import OpenTrade, StateManager

log = structlog.get_logger()


def _check_latency(
    start_ms: int,
    budget_ms: int,
    stage: str,
    correlation_id: str,
) -> None:
    """Log warning if stage exceeded its latency budget."""
    elapsed = int(time.time() * 1000) - start_ms
    if elapsed > budget_ms:
        log.warning(
            "latency_budget_exceeded",
            stage=stage,
            elapsed_ms=elapsed,
            budget_ms=budget_ms,
            correlation_id=correlation_id,
        )


async def _publish_system_error(
    bus: EventBus,
    envelope: EventEnvelope,
    error: str,
    stage: str,
) -> None:
    """Publish SYSTEM_ERROR event and log the failure."""
    log.error("pipeline_stage_error", stage=stage, error=error,
              correlation_id=envelope.correlation_id)
    await bus.publish(
        EventEnvelope(
            event_type=SYSTEM_ERROR,
            source=stage,
            correlation_id=envelope.correlation_id,
            market_id=envelope.market_id,
            payload={"error": error, "stage": stage},
        )
    )


def make_handlers(
    bus: EventBus,
    state: StateManager,
    model: BayesianSignalModel,
    cb: CircuitBreaker,
    cfg: dict[str, Any],
) -> None:
    """Wire all pipeline stage handlers to the event bus."""
    executor = PaperExecutor(cfg)
    risk = RiskManager(cfg)
    latency = cfg.get("latency_budgets", {})
    signal_budget = latency.get("signal_ms", 200)
    exec_budget = latency.get("execution_ms", 500)

    # ------------------------------------------------------------------
    # Stage 1: MARKET_DATA → SIGNAL
    # ------------------------------------------------------------------
    async def handle_market_data(envelope: EventEnvelope) -> None:
        """Generate trading signal from raw market data."""
        if cb.is_open():
            return
        start = envelope.timestamp_ms
        try:
            market = envelope.payload["market"]
            signal = model.generate_signal(market)
            if signal is None:
                return
            await bus.publish(
                EventEnvelope(
                    event_type=SIGNAL,
                    source="signal_model",
                    correlation_id=envelope.correlation_id,
                    market_id=envelope.market_id,
                    payload={"signal": signal.__dict__},
                )
            )
            _check_latency(start, signal_budget, "handle_market_data",
                           envelope.correlation_id)
        except Exception as exc:
            await _publish_system_error(bus, envelope, str(exc), "handle_market_data")
            await state.save_failed_event(envelope, str(exc))

    # ------------------------------------------------------------------
    # Stage 2: SIGNAL → FILTERED_SIGNAL
    # ------------------------------------------------------------------
    async def handle_signal(envelope: EventEnvelope) -> None:
        """Filter signal against open position limits and EV threshold."""
        if cb.is_open():
            return
        try:
            signal = envelope.payload["signal"]
            open_positions = await state.get_open_positions()
            open_ids = {t.market_id for t in open_positions}
            max_concurrent = cfg.get("trading", {}).get("max_concurrent_positions", 3)
            min_ev = cfg.get("trading", {}).get("min_ev_threshold", 0.02)

            if signal["market_id"] in open_ids:
                return
            if len(open_positions) >= max_concurrent:
                return
            if signal["ev"] < min_ev:
                return

            await bus.publish(
                EventEnvelope(
                    event_type=FILTERED_SIGNAL,
                    source="signal_filter",
                    correlation_id=envelope.correlation_id,
                    market_id=envelope.market_id,
                    payload={"signal": signal},
                )
            )
        except Exception as exc:
            await _publish_system_error(bus, envelope, str(exc), "handle_signal")
            await state.save_failed_event(envelope, str(exc))

    # ------------------------------------------------------------------
    # Stage 3: FILTERED_SIGNAL → POSITION_SIZED
    # ------------------------------------------------------------------
    async def handle_filtered_signal(envelope: EventEnvelope) -> None:
        """Apply Kelly criterion to size the position."""
        if cb.is_open():
            return
        try:
            signal = envelope.payload["signal"]
            open_positions = await state.get_open_positions()
            initial_balance = cfg.get("paper", {}).get("initial_balance", 1000.0)
            realized_pnl = await state.get_balance()
            balance = initial_balance + realized_pnl

            size = risk.get_position_size(
                ev=signal["ev"],
                p_model=signal["p_model"],
                p_market=signal["p_market"],
                balance=balance,
            )
            if size <= 0:
                return

            await bus.publish(
                EventEnvelope(
                    event_type=POSITION_SIZED,
                    source="risk_manager",
                    correlation_id=envelope.correlation_id,
                    market_id=envelope.market_id,
                    payload={
                        "signal": signal,
                        "size": size,
                        "balance": balance,
                    },
                )
            )
        except Exception as exc:
            await _publish_system_error(bus, envelope, str(exc), "handle_filtered_signal")
            await state.save_failed_event(envelope, str(exc))

    # ------------------------------------------------------------------
    # Stage 4: POSITION_SIZED → ORDER_FILLED
    # ------------------------------------------------------------------
    async def handle_position_sized(envelope: EventEnvelope) -> None:
        """Execute paper order and emit fill result."""
        if cb.is_open():
            return
        start = int(time.time() * 1000)
        try:
            signal = envelope.payload["signal"]
            size = envelope.payload["size"]
            result = await executor.execute_paper_order(
                market_id=signal["market_id"],
                price=signal["p_market"],
                size=size,
            )
            elapsed = int(time.time() * 1000) - start
            cb.record_latency_breach(elapsed)
            _check_latency(start, exec_budget, "handle_position_sized",
                           envelope.correlation_id)

            await bus.publish(
                EventEnvelope(
                    event_type=ORDER_FILLED,
                    source="paper_executor",
                    correlation_id=envelope.correlation_id,
                    market_id=envelope.market_id,
                    payload={
                        "signal": signal,
                        "result": result.__dict__,
                        "balance": envelope.payload["balance"],
                    },
                )
            )
        except Exception as exc:
            cb.record_api_failure()
            await _publish_system_error(bus, envelope, str(exc), "handle_position_sized")
            await state.save_failed_event(envelope, str(exc))

    # ------------------------------------------------------------------
    # Stage 5: ORDER_FILLED → STATE_UPDATED
    # ------------------------------------------------------------------
    async def handle_order_filled(envelope: EventEnvelope) -> None:
        """Persist trade to state and emit STATE_UPDATED for Telegram."""
        try:
            signal = envelope.payload["signal"]
            result = envelope.payload["result"]
            if not result.get("success"):
                return

            trade = OpenTrade(
                market_id=signal["market_id"],
                question=signal.get("question", ""),
                entry_price=result["fill_price"],
                size=result["filled_size"],
                kelly_f=signal.get("kelly_f", 0.0),
                ev=signal["ev"],
                fee=result.get("fee", 0.0),
                entry_time=time.time(),
                correlation_id=envelope.correlation_id,
            )
            await state.save_trade(trade)
            await state.log_event(envelope)

            await bus.publish(
                EventEnvelope(
                    event_type=STATE_UPDATED,
                    source="order_handler",
                    correlation_id=envelope.correlation_id,
                    market_id=envelope.market_id,
                    payload={
                        "action": "TRADE_OPENED",
                        "trade": {
                            "market_id": trade.market_id,
                            "question": trade.question,
                            "entry_price": trade.entry_price,
                            "size": trade.size,
                            "ev": trade.ev,
                            "fee": trade.fee,
                        },
                        "balance": envelope.payload["balance"],
                    },
                )
            )
        except Exception as exc:
            await _publish_system_error(bus, envelope, str(exc), "handle_order_filled")
            await state.save_failed_event(envelope, str(exc))

    # Wire all handlers
    bus.subscribe(MARKET_DATA, handle_market_data)
    bus.subscribe(SIGNAL, handle_signal)
    bus.subscribe(FILTERED_SIGNAL, handle_filtered_signal)
    bus.subscribe(POSITION_SIZED, handle_position_sized)
    bus.subscribe(ORDER_FILLED, handle_order_filled)
