"""Phase 5 pipeline handlers.

handle_market_data runs ALL enabled strategies concurrently via asyncio.gather,
computes edge_score per signal, publishes one SIGNAL per result.
Arbitrage signals bypass EV threshold filter.
All other stages match Phase 4 contract.
"""
from __future__ import annotations

import time
from typing import Any

import structlog

from ..core.risk_manager import get_position_size
from ..core.execution.execution_engine import ExecutionEngine
from ..engine.circuit_breaker import CircuitBreaker
from ..engine.event_bus import (
    FILTERED_SIGNAL,
    ORDER_FILLED,
    POSITION_SIZED,
    SIGNAL,
    STATE_UPDATED,
    SYSTEM_ERROR,
    EventBus,
    EventEnvelope,
)
from ..engine.state_manager import OpenTrade, StateManager
from ..engine.strategy_engine import BaseStrategy, run_all_strategies
from ..engine.strategy_manager import StrategyManager

log = structlog.get_logger()


def _check_latency(
    stage: str,
    elapsed_ms: float,
    budget_ms: int,
    correlation_id: str,
    market_id: str | None,
) -> None:
    """Log warning if stage exceeded its latency budget."""
    if elapsed_ms > budget_ms:
        log.warning(
            "latency_budget_exceeded",
            stage=stage,
            elapsed_ms=int(elapsed_ms),
            budget_ms=budget_ms,
            correlation_id=correlation_id,
            market_id=market_id,
        )


async def _publish_error(
    bus: EventBus,
    src: EventEnvelope,
    exc: Exception,
    handler_name: str,
) -> None:
    """Publish SYSTEM_ERROR and log the exception."""
    log.error(
        "pipeline_handler_error",
        handler=handler_name,
        correlation_id=src.correlation_id,
        error=str(exc),
    )
    await bus.publish(
        EventEnvelope.create(
            event_type=SYSTEM_ERROR,
            source=handler_name,
            payload={"error": str(exc), "origin_event": src.event_type},
            correlation_id=src.correlation_id,
            market_id=src.market_id,
        )
    )


def make_handlers(
    bus: EventBus,
    state: StateManager,
    strategies: list[BaseStrategy],
    strategy_mgr: StrategyManager,
    exec_engine: ExecutionEngine,
    cb: CircuitBreaker,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """Wire all pipeline stage handlers and return them keyed by name."""
    min_ev: float = cfg["trading"]["min_ev_threshold"]
    max_pos_pct: float = cfg["trading"]["max_position_pct"]
    max_concurrent: int = cfg["trading"]["max_concurrent_positions"]
    signal_budget: int = cfg["latency_budgets"]["signal_ms"]
    exec_budget: int = cfg["latency_budgets"]["execution_ms"]

    # ── Stage 1: MARKET_DATA → SIGNAL(s) ─────────────────────────────────────

    async def handle_market_data(envelope: EventEnvelope) -> None:
        """Run all enabled strategies concurrently; publish one SIGNAL per result."""
        bound = log.bind(correlation_id=envelope.correlation_id,
                         market_id=envelope.market_id)
        t0 = time.time()
        try:
            signals = await run_all_strategies(
                strategies, envelope.payload, strategy_mgr
            )
            elapsed = (time.time() - t0) * 1000
            _check_latency("signal_generation", elapsed, signal_budget,
                           envelope.correlation_id, envelope.market_id)

            if not signals:
                return

            for sig in signals:
                weight = strategy_mgr.weight(sig.strategy)
                sig.edge_score = round(sig.ev * sig.zscore * weight, 6)
                await bus.publish(
                    EventEnvelope.create(
                        event_type=SIGNAL,
                        source="handle_market_data",
                        payload={
                            "market_id": sig.market_id,
                            "question": sig.question,
                            "outcome": sig.outcome,
                            "p_model": sig.p_model,
                            "p_market": sig.p_market,
                            "ev": sig.ev,
                            "zscore": sig.zscore,
                            "edge_score": sig.edge_score,
                            "strategy": sig.strategy,
                            "signal_generation_ms": int(elapsed),
                        },
                        correlation_id=envelope.correlation_id,
                        market_id=envelope.market_id,
                    )
                )

            bound.info("signals_published", count=len(signals),
                       elapsed_ms=int(elapsed))

        except Exception as exc:
            await _publish_error(bus, envelope, exc, "handle_market_data")

    # ── Stage 2: SIGNAL → FILTERED_SIGNAL ──────────────────────────────────

    async def handle_signal(envelope: EventEnvelope) -> None:
        """Filter signal: EV threshold, circuit check. Arbitrage bypasses EV filter."""
        bound = log.bind(correlation_id=envelope.correlation_id,
                         market_id=envelope.market_id)
        t0 = time.time()
        try:
            p = envelope.payload
            strategy = p.get("strategy", "unknown")

            if strategy != "arbitrage" and p["ev"] < min_ev:
                bound.debug("signal_filtered_ev", ev=p["ev"], threshold=min_ev)
                return

            if cb.is_open():
                bound.warning("signal_filtered_circuit_open")
                return

            elapsed = (time.time() - t0) * 1000
            await bus.publish(
                EventEnvelope.create(
                    event_type=FILTERED_SIGNAL,
                    source="handle_signal",
                    payload={**p, "filter_ms": int(elapsed)},
                    correlation_id=envelope.correlation_id,
                    market_id=envelope.market_id,
                )
            )
            bound.info("signal_passed_filter", strategy=strategy,
                       ev=round(p["ev"], 4), elapsed_ms=int(elapsed))

        except Exception as exc:
            await _publish_error(bus, envelope, exc, "handle_signal")

    # ── Stage 3: FILTERED_SIGNAL → POSITION_SIZED ───────────────────────────

    async def handle_filtered_signal(envelope: EventEnvelope) -> None:
        """Apply Kelly criterion, check position limits, emit POSITION_SIZED."""
        bound = log.bind(correlation_id=envelope.correlation_id,
                         market_id=envelope.market_id)
        t0 = time.time()
        try:
            open_positions = await state.get_open_positions()
            if len(open_positions) >= max_concurrent:
                bound.info("position_limit_reached", count=len(open_positions))
                return

            open_market_ids = {pos.market_id for pos in open_positions}
            p = envelope.payload
            # Arbitrage: allow both YES and NO for same market_id
            if p.get("strategy") != "arbitrage" and envelope.market_id in open_market_ids:
                bound.debug("duplicate_market_skipped")
                return

            balance = await state.get_balance()
            size = get_position_size(
                balance=balance,
                ev=p["ev"],
                p_model=p["p_model"],
                p_market=p["p_market"],
                max_position_pct=max_pos_pct,
            )
            if size <= 0:
                bound.warning("position_size_zero")
                return

            elapsed = (time.time() - t0) * 1000
            await bus.publish(
                EventEnvelope.create(
                    event_type=POSITION_SIZED,
                    source="handle_filtered_signal",
                    payload={**p, "size": size, "balance": balance,
                             "risk_ms": int(elapsed)},
                    correlation_id=envelope.correlation_id,
                    market_id=envelope.market_id,
                )
            )
            bound.info("position_sized", size=size,
                       strategy=p.get("strategy"), balance=round(balance, 2),
                       elapsed_ms=int(elapsed))

        except Exception as exc:
            await _publish_error(bus, envelope, exc, "handle_filtered_signal")

    # ── Stage 4: POSITION_SIZED → ORDER_FILLED ─────────────────────────────

    async def handle_position_sized(envelope: EventEnvelope) -> None:
        """Execute paper order; abort on slippage; trip CB on latency breach."""
        bound = log.bind(correlation_id=envelope.correlation_id,
                         market_id=envelope.market_id)
        t0 = time.time()
        try:
            p = envelope.payload
            market_ctx = {
                "bid": p["p_market"] - 0.005,
                "ask": p["p_market"] + 0.005,
            }
            order = await exec_engine.execute(
                market_id=p["market_id"],
                outcome=p["outcome"],
                price=p["p_market"],
                size=p["size"],
                market_ctx=market_ctx,
                correlation_id=envelope.correlation_id,
            )

            if order.status == "ABORTED_SLIPPAGE" or order.filled_size <= 0:
                bound.warning("order_aborted", status=order.status)
                return

            elapsed = (time.time() - t0) * 1000
            _check_latency("execution", elapsed, exec_budget,
                           envelope.correlation_id, envelope.market_id)
            await cb.record_latency_breach(int(elapsed))

            await bus.publish(
                EventEnvelope.create(
                    event_type=ORDER_FILLED,
                    source="handle_position_sized",
                    payload={
                        **p,
                        "order_id": order.order_id,
                        "filled_price": order.filled_price,
                        "filled_size": order.filled_size,
                        "fee": order.fee,
                        "fill_status": order.status,
                        "execution_ms": int(elapsed),
                        "strategy": p.get("strategy", "unknown"),
                    },
                    correlation_id=envelope.correlation_id,
                    market_id=envelope.market_id,
                )
            )
            bound.info("order_filled", order_id=order.order_id,
                       strategy=p.get("strategy"), elapsed_ms=int(elapsed))

        except Exception as exc:
            await cb.record_api_failure()
            await _publish_error(bus, envelope, exc, "handle_position_sized")

    # ── Stage 5: ORDER_FILLED → STATE_UPDATED ──────────────────────────────

    async def handle_order_filled(envelope: EventEnvelope) -> None:
        """Persist trade to DB, emit STATE_UPDATED(TRADE_OPENED) for Telegram."""
        import time as _time
        bound = log.bind(correlation_id=envelope.correlation_id,
                         market_id=envelope.market_id)
        try:
            p = envelope.payload
            trade = OpenTrade(
                trade_id=p["order_id"],
                market_id=p["market_id"],
                question=p["question"],
                outcome=p["outcome"],
                entry_price=p["filled_price"],
                size=p["filled_size"],
                ev=p["ev"],
                fee=p["fee"],
                opened_at=_time.time(),
                correlation_id=envelope.correlation_id,
                strategy=p.get("strategy", "bayesian"),
            )
            await state.save_trade(trade)
            await state.log_event(envelope)

            balance = await state.get_balance()
            await bus.publish(
                EventEnvelope.create(
                    event_type=STATE_UPDATED,
                    source="handle_order_filled",
                    payload={
                        "action": "TRADE_OPENED",
                        "trade_id": trade.trade_id,
                        "market_id": trade.market_id,
                        "question": trade.question,
                        "outcome": trade.outcome,
                        "entry_price": trade.entry_price,
                        "size": trade.size,
                        "ev": trade.ev,
                        "fee": trade.fee,
                        "balance": balance,
                        "strategy": trade.strategy,
                        "fill_status": p.get("fill_status", "FILLED"),
                        "execution_ms": p.get("execution_ms", 0),
                    },
                    correlation_id=envelope.correlation_id,
                    market_id=envelope.market_id,
                )
            )
            bound.info("state_updated_trade_opened", trade_id=trade.trade_id,
                       strategy=trade.strategy, balance=round(balance, 2))

        except Exception as exc:
            await state.save_failed_event(
                envelope.event_type, envelope.correlation_id,
                str(envelope.payload), str(exc),
            )
            await _publish_error(bus, envelope, exc, "handle_order_filled")

    return {
        "handle_market_data": handle_market_data,
        "handle_signal": handle_signal,
        "handle_filtered_signal": handle_filtered_signal,
        "handle_position_sized": handle_position_sized,
        "handle_order_filled": handle_order_filled,
    }
