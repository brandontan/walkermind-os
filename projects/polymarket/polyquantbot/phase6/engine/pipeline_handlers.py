"""Phase 6 pipeline handlers.

Wires CorrelationEngine + CapitalAllocator + ExecutionEngine into the
Phase 5 EventBus pipeline. Key changes from Phase 5:

  handle_market_data:
    1. Run all enabled strategies concurrently (asyncio.gather).
    2. Apply CorrelationEngine.adjust_all() to all signals in the cycle.
    3. Publish one SIGNAL per adjusted signal.

  handle_signal:
    1. Reject if circuit breaker is open.
    2. CapitalAllocator.allocate() → approved size (score-weighted + hard cap).
    3. ExecutionEngine.decide() → ExecutionDecision (TAKER/MAKER/HYBRID/REJECT).
    4. Publish POSITION_SIZED with decision payload.

  handle_position_sized:
    1. ExecutionEngine.execute() → OrderResult.
    2. Publish ORDER_FILLED.

  handle_order_filled:
    1. state.save_trade() → publish STATE_UPDATED(TRADE_OPENED).

Arbitrage signals: capital allocator and execution engine handle them the
same as other signals; the strategy tag "arbitrage" flows through intact.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

import structlog

from ..core.signal_model import SignalResult
from ..engine.capital_allocator import CapitalAllocator
from ..engine.circuit_breaker import CircuitBreaker
from ..engine.correlation_engine import CorrelationEngine
from ..engine.event_bus import (
    ORDER_FILLED,
    POSITION_SIZED,
    SIGNAL,
    STATE_UPDATED,
    SYSTEM_ERROR,
    EventBus,
    EventEnvelope,
)
from ..engine.execution_engine import ExecutionDecision, ExecutionEngine
from ..engine.state_manager import OpenTrade, StateManager
from ..engine.strategy_engine import BaseStrategy, run_all_strategies
from ..engine.strategy_manager import StrategyManager

log = structlog.get_logger()

_DEFAULT_SCORE = 0.1   # score floor for untracked strategies in allocator


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
        market_id=src.market_id,
        error=str(exc),
    )
    await bus.publish(
        EventEnvelope.create(
            event_type=SYSTEM_ERROR,
            source=handler_name,
            payload={"error": str(exc), "handler": handler_name},
            correlation_id=src.correlation_id,
            market_id=src.market_id,
        )
    )


def make_handlers(
    bus: EventBus,
    state: StateManager,
    strategies: list[BaseStrategy],
    strategy_mgr: StrategyManager,
    corr_engine: CorrelationEngine,
    capital_allocator: CapitalAllocator,
    exec_engine: ExecutionEngine,
    cb: CircuitBreaker,
    cfg: dict,
) -> dict[str, Any]:
    """Build and return all Phase 6 pipeline handler closures.

    All handlers share the injected dependencies via closure.

    Returns:
        Dict mapping handler names to async callables.
    """
    t_cfg = cfg["trading"]
    max_trades_per_cycle: int = t_cfg.get("max_trades_per_cycle", 2)
    max_total_exposure_pct: float = t_cfg.get("max_total_exposure_pct", 0.30)
    signal_budget_ms: int = cfg["latency_budgets"]["signal_ms"]
    exec_budget_ms: int = cfg["latency_budgets"]["execution_ms"]

    # Mutable cycle state (reset each cycle by runner)
    cycle_state: dict[str, Any] = {"trades_this_cycle": 0}

    # Correlation matrix — empty dict = no adjustments (Phase 6 foundation)
    # In a future phase this would be populated from real market data.
    correlation_matrix: dict[tuple[str, str], float] = {}

    # ── handle_market_data ────────────────────────────────────────────────────

    async def handle_market_data(envelope: EventEnvelope) -> None:
        """Run all strategies + CorrelationEngine → publish SIGNAL per result."""
        t0 = time.time()
        market_data = envelope.payload

        try:
            # 1. Run all enabled strategies concurrently
            raw_signals = await run_all_strategies(
                strategies, market_data, strategy_mgr
            )
            if not raw_signals:
                return

            # 2. Apply Bayesian correlation adjustment to all signals in cycle
            adjusted_signals = await corr_engine.adjust_all(
                signals=raw_signals,
                correlation_matrix=correlation_matrix,
                correlation_id=envelope.correlation_id,
            )

            # 3. Publish one SIGNAL per adjusted signal
            market_ctx = {
                "bid": market_data.get("bid"),
                "ask": market_data.get("ask"),
                "volume": market_data.get("volume"),
                "spread": market_data.get("spread"),
                "p_yes": market_data.get("p_yes"),
                "p_no": market_data.get("p_no"),
            }
            for sig in adjusted_signals:
                await bus.publish(
                    EventEnvelope.create(
                        event_type=SIGNAL,
                        source="pipeline:market_data",
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
                            "market_ctx": market_ctx,
                        },
                        correlation_id=envelope.correlation_id,
                        market_id=sig.market_id,
                    )
                )

            elapsed = (time.time() - t0) * 1000
            _check_latency(
                "handle_market_data", elapsed, signal_budget_ms,
                envelope.correlation_id, envelope.market_id,
            )
            log.debug(
                "market_data_handled",
                correlation_id=envelope.correlation_id,
                signals=len(adjusted_signals),
                elapsed_ms=int(elapsed),
            )

        except Exception as exc:
            await _publish_error(bus, envelope, exc, "handle_market_data")

    # ── handle_signal ─────────────────────────────────────────────────────────

    async def handle_signal(envelope: EventEnvelope) -> None:
        """CapitalAllocator + ExecutionEngine.decide() → POSITION_SIZED."""
        if cb.is_open():
            return

        if cycle_state["trades_this_cycle"] >= max_trades_per_cycle:
            return

        p = envelope.payload
        try:
            sig = SignalResult(
                market_id=p["market_id"],
                question=p["question"],
                outcome=p["outcome"],
                p_model=p["p_model"],
                p_market=p["p_market"],
                ev=p["ev"],
                zscore=p.get("zscore", 1.0),
                edge_score=p.get("edge_score", 0.0),
                strategy=p.get("strategy", "unknown"),
            )

            # Exposure guard
            open_positions = await state.get_open_positions()
            balance = await state.get_balance()
            total_exposure = sum(t.size for t in open_positions) / max(balance, 1e-9)
            if total_exposure >= max_total_exposure_pct:
                log.info(
                    "signal_rejected_exposure_cap",
                    correlation_id=envelope.correlation_id,
                    total_exposure=round(total_exposure, 4),
                )
                return

            # Build strategy scores for allocator (floor untracked at default)
            all_s = {s["name"]: s["score"] for s in strategy_mgr.all_stats()}
            for strat in strategies:
                if strat.name not in all_s:
                    all_s[strat.name] = _DEFAULT_SCORE

            # Capital allocation
            alloc = capital_allocator.allocate(
                strategy_name=sig.strategy,
                strategy_scores=all_s,
                balance=balance,
                open_positions=len(open_positions),
                correlation_id=envelope.correlation_id,
            )
            if not alloc.approved:
                return

            # Execution decision
            market_ctx = p.get("market_ctx", {})
            decision = exec_engine.decide(
                signal=sig,
                size=alloc.size,
                market_ctx=market_ctx,
                correlation_id=envelope.correlation_id,
            )
            if decision.mode == "REJECT":
                log.info(
                    "signal_rejected_by_execution_engine",
                    correlation_id=envelope.correlation_id,
                    market_id=sig.market_id,
                    strategy=sig.strategy,
                    reason=decision.reason,
                )
                return

            await bus.publish(
                EventEnvelope.create(
                    event_type=POSITION_SIZED,
                    source="pipeline:signal",
                    payload={
                        "market_id": sig.market_id,
                        "question": sig.question,
                        "outcome": sig.outcome,
                        "p_model": sig.p_model,
                        "p_market": sig.p_market,
                        "ev": sig.ev,
                        "strategy": sig.strategy,
                        "decision_mode": decision.mode,
                        "limit_price": decision.limit_price,
                        "adjusted_size": decision.adjusted_size,
                        "expected_cost": decision.expected_cost,
                        "fill_prob": decision.fill_prob,
                        "market_ctx": market_ctx,
                        "alloc_weight": alloc.weight,
                    },
                    correlation_id=envelope.correlation_id,
                    market_id=sig.market_id,
                )
            )

        except Exception as exc:
            await _publish_error(bus, envelope, exc, "handle_signal")

    # ── handle_position_sized ─────────────────────────────────────────────────

    async def handle_position_sized(envelope: EventEnvelope) -> None:
        """ExecutionEngine.execute() → ORDER_FILLED."""
        t0 = time.time()
        p = envelope.payload
        try:
            sig = SignalResult(
                market_id=p["market_id"],
                question=p["question"],
                outcome=p["outcome"],
                p_model=p["p_model"],
                p_market=p["p_market"],
                ev=p["ev"],
                strategy=p.get("strategy", "unknown"),
            )

            decision = ExecutionDecision(
                mode=p["decision_mode"],
                limit_price=p["limit_price"],
                adjusted_size=p["adjusted_size"],
                expected_cost=p["expected_cost"],
                fill_prob=p["fill_prob"],
                reason="from_pipeline",
                correlation_id=envelope.correlation_id,
                market_id=p["market_id"],
                outcome=p["outcome"],
            )

            result = await exec_engine.execute(
                decision=decision,
                signal=sig,
                market_ctx=p.get("market_ctx", {}),
                cfg_paper=cfg.get("paper", {}),
            )

            elapsed_ms = int((time.time() - t0) * 1000)
            _check_latency(
                "handle_position_sized", elapsed_ms, exec_budget_ms,
                envelope.correlation_id, envelope.market_id,
            )

            if result.filled_size <= 0:
                log.info(
                    "order_not_filled",
                    correlation_id=envelope.correlation_id,
                    status=result.status,
                )
                return

            cycle_state["trades_this_cycle"] += 1

            await bus.publish(
                EventEnvelope.create(
                    event_type=ORDER_FILLED,
                    source="pipeline:position_sized",
                    payload={
                        "order_id": result.order_id,
                        "market_id": result.market_id,
                        "question": p["question"],
                        "outcome": result.outcome,
                        "entry_price": result.filled_price,
                        "size": result.filled_size,
                        "fee": result.fee,
                        "ev": sig.ev,
                        "strategy": sig.strategy,
                        "fill_status": result.status,
                        "execution_ms": elapsed_ms,
                        "decision_mode": decision.mode,
                        "expected_cost": decision.expected_cost,
                        "fill_prob": decision.fill_prob,
                    },
                    correlation_id=envelope.correlation_id,
                    market_id=result.market_id,
                )
            )

        except Exception as exc:
            await _publish_error(bus, envelope, exc, "handle_position_sized")

    # ── handle_order_filled ───────────────────────────────────────────────────

    async def handle_order_filled(envelope: EventEnvelope) -> None:
        """Persist open trade and publish STATE_UPDATED(TRADE_OPENED)."""
        p = envelope.payload
        try:
            balance = await state.get_balance()
            trade = OpenTrade(
                trade_id=p["order_id"],
                market_id=p["market_id"],
                question=p["question"],
                outcome=p["outcome"],
                entry_price=p["entry_price"],
                size=p["size"],
                ev=p["ev"],
                fee=p["fee"],
                opened_at=time.time(),
                correlation_id=envelope.correlation_id,
                strategy=p.get("strategy", "unknown"),
            )
            await state.save_trade(trade)

            await bus.publish(
                EventEnvelope.create(
                    event_type=STATE_UPDATED,
                    source="pipeline:order_filled",
                    payload={
                        "action": "TRADE_OPENED",
                        "trade_id": trade.trade_id,
                        "market_id": trade.market_id,
                        "question": trade.question,
                        "outcome": trade.outcome,
                        "entry_price": trade.entry_price,
                        "size": trade.size,
                        "fee": trade.fee,
                        "ev": trade.ev,
                        "balance": balance,
                        "strategy": trade.strategy,
                        "fill_status": p.get("fill_status", "FILLED"),
                        "execution_ms": p.get("execution_ms", 0),
                        "decision_mode": p.get("decision_mode", "UNKNOWN"),
                    },
                    correlation_id=envelope.correlation_id,
                    market_id=trade.market_id,
                )
            )

        except Exception as exc:
            await _publish_error(bus, envelope, exc, "handle_order_filled")

    return {
        "handle_market_data": handle_market_data,
        "handle_signal": handle_signal,
        "handle_position_sized": handle_position_sized,
        "handle_order_filled": handle_order_filled,
        "cycle_state": cycle_state,
    }
