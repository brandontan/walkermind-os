"""Phase 6 runner — EV-aware event-driven main loop.

Wires all Phase 6 components:
  CorrelationEngine  → Bayesian log-odds signal adjustment
  CapitalAllocator   → Score-weighted capital sizing
  ExecutionEngine    → EV decision tree (TAKER/MAKER/HYBRID)
  MarketMaker        → Toxicity-aware quote placement (optional)

Pipeline: MARKET_DATA → SIGNAL → POSITION_SIZED → ORDER_FILLED → STATE_UPDATED
"""
from __future__ import annotations

import asyncio
import os
import random
import time
import uuid

import structlog
import yaml
from dotenv import load_dotenv

from ..config.execution_config import ExecutionConfig
from ..engine.capital_allocator import CapitalAllocator
from ..engine.circuit_breaker import CircuitBreaker
from ..engine.correlation_engine import CorrelationEngine
from ..engine.event_bus import (
    CIRCUIT_BREAKER_OPEN,
    MARKET_DATA,
    STATE_UPDATED,
    EventBus,
    EventEnvelope,
)
from ..engine.execution_engine import ExecutionEngine
from ..engine.health_server import start_health_server
from ..engine.market_maker import MarketMaker
from ..engine.performance_tracker import PerformanceTracker
from ..engine.pipeline_handlers import make_handlers
from ..engine.state_manager import StateManager
from ..engine.strategy_engine import build_strategies
from ..engine.strategy_manager import StrategyManager
from ..infra.polymarket_client import fetch_markets
from ..infra.telegram_service import handle_state_updated

load_dotenv()
log = structlog.get_logger()


def _load_config(path: str = "config.yaml") -> dict:
    """Load YAML config file."""
    with open(path) as f:
        return yaml.safe_load(f)


async def exit_monitor_loop(
    state: StateManager,
    bus: EventBus,
    tracker: PerformanceTracker,
    strategy_mgr: StrategyManager,
    cb: CircuitBreaker,
    cfg: dict,
) -> None:
    """Continuously poll open positions and evaluate TP / SL / TIMEOUT exits."""
    tp_pct = cfg["position"]["tp_pct"]
    sl_pct = cfg["position"]["sl_pct"]
    timeout_min = cfg["position"]["timeout_minutes"]
    poll = cfg["trading"]["poll_interval_seconds"]

    while True:
        try:
            positions = await state.get_open_positions()
            now = time.time()
            for pos in positions:
                drift = random.uniform(-0.04, 0.06)
                current_price = max(0.01, min(0.99, pos.entry_price + drift))
                gain_pct = (current_price - pos.entry_price) / max(pos.entry_price, 1e-9)
                elapsed_min = (now - pos.opened_at) / 60.0

                reason: str | None = None
                if gain_pct >= tp_pct:
                    reason = "TP"
                elif gain_pct <= -sl_pct:
                    reason = "SL"
                elif elapsed_min >= timeout_min:
                    reason = "TIMEOUT"

                if reason:
                    pnl = round(
                        (current_price - pos.entry_price) * pos.size - pos.fee, 4
                    )
                    await state.close_trade(pos.trade_id, current_price, pnl)
                    balance = await state.get_balance()
                    new_balance = balance + pnl
                    await state.update_balance(new_balance)
                    await tracker.record(pnl=pnl, ev=pos.ev)
                    strategy_mgr.record_trade(
                        strategy=pos.strategy, pnl=pnl, ev=pos.ev
                    )

                    if pnl > 0:
                        await cb.record_win()
                    else:
                        await cb.record_loss()

                    pnl_pct = (pnl / max(pos.entry_price * pos.size, 1e-9)) * 100

                    await bus.publish(
                        EventEnvelope.create(
                            event_type=STATE_UPDATED,
                            source="exit_monitor",
                            payload={
                                "action": "TRADE_CLOSED",
                                "trade_id": pos.trade_id,
                                "market_id": pos.market_id,
                                "question": pos.question,
                                "outcome": pos.outcome,
                                "entry_price": pos.entry_price,
                                "exit_price": current_price,
                                "size": pos.size,
                                "fee": pos.fee,
                                "pnl": pnl,
                                "pnl_pct": round(pnl_pct, 2),
                                "reason": reason,
                                "duration_minutes": round(elapsed_min, 2),
                                "balance": new_balance,
                                "strategy": pos.strategy,
                            },
                            correlation_id=pos.correlation_id,
                            market_id=pos.market_id,
                        )
                    )
        except Exception as exc:
            log.error("exit_monitor_error", error=str(exc))
        await asyncio.sleep(poll)


async def mm_loop(
    market_maker: MarketMaker,
    cfg: dict,
    poll_interval: float,
) -> None:
    """Background market-maker loop. Runs only if mm.enabled = true."""
    while True:
        try:
            markets = await fetch_markets(limit=5)
            for market in markets:
                correlation_id = str(uuid.uuid4())
                await market_maker.place_quotes(
                    market_id=market.market_id,
                    mid_price=market.p_market,
                    buy_vol=market.volume * 0.5,
                    sell_vol=market.volume * 0.5,
                    correlation_id=correlation_id,
                )
        except Exception as exc:
            log.error("mm_loop_error", error=str(exc))
        await asyncio.sleep(poll_interval)


async def main() -> None:
    """Entry point for Phase 6 event-driven bot."""
    import structlog as _sl
    _sl.configure(
        processors=[
            _sl.processors.TimeStamper(fmt="iso"),
            _sl.processors.JSONRenderer(),
        ]
    )

    config_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
    cfg = _load_config(config_path)

    t_cfg = cfg["trading"]
    p_cfg = cfg["paper"]
    e_cfg = cfg["execution"]
    s_cfg = cfg["strategy"]
    cb_cfg = cfg["circuit_breaker"]
    mm_cfg = cfg["market_maker"]
    ca_cfg = cfg["capital_allocator"]
    corr_cfg = cfg["correlation"]
    health_port = cfg["health"]["port"]
    poll_interval = t_cfg["poll_interval_seconds"]
    summary_every = t_cfg["summary_every_n_cycles"]
    initial_balance = p_cfg["initial_balance"]

    db_path = os.getenv("DATABASE_PATH", "./data/phase6.db")
    state = StateManager(db_path=db_path, initial_balance=initial_balance)
    await state.init()

    bus = EventBus()

    cb = CircuitBreaker(
        bus=bus,
        max_consecutive_losses=cb_cfg["max_consecutive_losses"],
        max_api_failures=cb_cfg["max_api_failures"],
        latency_breach_threshold_ms=cb_cfg["latency_breach_threshold_ms"],
        cooldown_seconds=cb_cfg["cooldown_seconds"],
    )

    strategy_mgr = StrategyManager(
        disable_threshold=s_cfg["disable_threshold"],
        min_trades=s_cfg["min_trades"],
    )
    strategies = build_strategies(cfg)

    corr_engine = CorrelationEngine(
        max_corr_adjustment=corr_cfg.get("max_corr_adjustment", 0.3)
    )

    capital_allocator = CapitalAllocator(
        max_position_pct=ca_cfg["max_position_pct"],
        max_open_positions=ca_cfg["max_open_positions"],
        min_order_size=ca_cfg["min_order_size"],
    )

    exec_cfg = ExecutionConfig.from_dict(e_cfg)
    exec_engine = ExecutionEngine(cfg=exec_cfg)

    market_maker = MarketMaker(
        spread_pct=mm_cfg.get("spread_pct", 0.02),
        size=mm_cfg.get("size", 10.0),
        min_order_size=ca_cfg["min_order_size"],
        cooldown_seconds=mm_cfg.get("cooldown_seconds", 60.0),
    )

    tracker = PerformanceTracker(state)
    pipeline_state: dict = {"status": "starting", "cycle": 0}

    handlers = make_handlers(
        bus=bus,
        state=state,
        strategies=strategies,
        strategy_mgr=strategy_mgr,
        corr_engine=corr_engine,
        capital_allocator=capital_allocator,
        exec_engine=exec_engine,
        cb=cb,
        cfg=cfg,
    )

    # Wire event pipeline
    bus.subscribe(MARKET_DATA, handlers["handle_market_data"])
    bus.subscribe("SIGNAL", handlers["handle_signal"])
    bus.subscribe("POSITION_SIZED", handlers["handle_position_sized"])
    bus.subscribe("ORDER_FILLED", handlers["handle_order_filled"])
    bus.subscribe(STATE_UPDATED, handle_state_updated)

    async def handle_circuit_breaker_event(envelope: EventEnvelope) -> None:
        """Relay circuit breaker open event to Telegram via STATE_UPDATED."""
        await bus.publish(
            EventEnvelope.create(
                event_type=STATE_UPDATED,
                source="circuit_breaker_relay",
                payload={
                    "action": "CIRCUIT_OPEN",
                    "reason": envelope.payload.get("reason"),
                    "cooldown_seconds": envelope.payload.get("cooldown_seconds"),
                },
                correlation_id=envelope.correlation_id,
            )
        )

    bus.subscribe(CIRCUIT_BREAKER_OPEN, handle_circuit_breaker_event)

    log.info(
        "phase6_event_bus_wired",
        strategies=[s.name for s in strategies],
        strategy_count=len(strategies),
    )

    # Start background tasks
    await start_health_server(
        state=state, pipeline_state=pipeline_state, port=health_port
    )
    asyncio.create_task(
        exit_monitor_loop(state, bus, tracker, strategy_mgr, cb, cfg)
    )

    # Start market maker background task (opt-in via config)
    if mm_cfg.get("enabled", False):
        asyncio.create_task(mm_loop(market_maker, cfg, poll_interval))
        log.info("market_maker_started")

    pipeline_state["status"] = "running"
    log.info(
        "phase6_runner_started",
        initial_balance=initial_balance,
        poll_interval=poll_interval,
    )

    cycle = 0
    try:
        while True:
            cycle_start = time.time()
            cycle += 1
            pipeline_state["cycle"] = cycle
            handlers["cycle_state"]["trades_this_cycle"] = 0  # reset per cycle

            if not cb.is_open():
                markets = await fetch_markets(limit=10)
                if not markets:
                    await cb.record_api_failure()
                    log.warning("no_markets_fetched", cycle=cycle)
                else:
                    for market in markets:
                        correlation_id = str(uuid.uuid4())
                        p_market = market.p_market
                        await bus.publish(
                            EventEnvelope.create(
                                event_type=MARKET_DATA,
                                source="runner",
                                payload={
                                    "market_id": market.market_id,
                                    "question": market.question,
                                    "p_market": p_market,
                                    "p_market_prev": max(
                                        0.01,
                                        min(0.99, p_market - random.uniform(-0.01, 0.01)),
                                    ),
                                    "volume": market.volume,
                                    "spread": market.spread,
                                    "bid": p_market - market.spread / 2,
                                    "ask": p_market + market.spread / 2,
                                    "p_yes": p_market,
                                    "p_no": round(
                                        max(0.01, 1.0 - p_market
                                            - random.uniform(0.0, 0.03)), 4
                                    ),
                                },
                                correlation_id=correlation_id,
                                market_id=market.market_id,
                            )
                        )
                    log.info("market_data_published", count=len(markets), cycle=cycle)
            else:
                log.warning("circuit_open_skipping_cycle", cycle=cycle)

            # Periodic summary + strategy status
            if cycle % summary_every == 0:
                balance = await state.get_balance()
                open_positions = await state.get_open_positions()
                stats = await tracker.snapshot()
                total_pnl = balance - initial_balance

                await bus.publish(
                    EventEnvelope.create(
                        event_type=STATE_UPDATED,
                        source="runner_summary",
                        payload={
                            "action": "SUMMARY",
                            "balance": balance,
                            "total_pnl": round(total_pnl, 2),
                            "open_count": len(open_positions),
                            "stats": stats,
                        },
                    )
                )
                await bus.publish(
                    EventEnvelope.create(
                        event_type=STATE_UPDATED,
                        source="runner_strategy_status",
                        payload={
                            "action": "STRATEGY_STATUS",
                            "strategies": strategy_mgr.all_stats(),
                        },
                    )
                )

            elapsed_cycle = (time.time() - cycle_start) * 1000
            if elapsed_cycle > cfg["latency_budgets"]["total_ms"]:
                log.warning(
                    "latency_budget_exceeded",
                    stage="total_cycle",
                    elapsed_ms=int(elapsed_cycle),
                    budget_ms=cfg["latency_budgets"]["total_ms"],
                )

            sleep_s = max(0.0, poll_interval - (time.time() - cycle_start))
            await asyncio.sleep(sleep_s)

    except asyncio.CancelledError:
        log.info("runner_cancelled")
    finally:
        await market_maker.cleanup()
        await bus.shutdown()
        await state.close()
        log.info("phase6_runner_stopped")


if __name__ == "__main__":
    asyncio.run(main())
