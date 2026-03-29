"""Phase 4 runner — event-driven main loop."""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import Any

import structlog
import yaml
from dotenv import load_dotenv

from ..core.signal_model import BayesianSignalModel
from ..infra.polymarket_client import PolymarketClient
from ..infra.telegram_service import TelegramService
from ..engine.circuit_breaker import CircuitBreaker
from ..engine.event_bus import (
    CIRCUIT_BREAKER_OPEN,
    MARKET_DATA,
    STATE_UPDATED,
    EventBus,
    EventEnvelope,
)
from ..engine.health_server import start_health_server
from ..engine.pipeline_handlers import make_handlers
from ..engine.state_manager import StateManager
from ..engine.performance_tracker import PerformanceTracker

log = structlog.get_logger()


def _load_config(path: str = "config.yaml") -> dict[str, Any]:
    """Load YAML config file."""
    with open(path) as f:
        return yaml.safe_load(f)


async def exit_monitor_loop(
    state: StateManager,
    bus: EventBus,
    cb: CircuitBreaker,
    cfg: dict[str, Any],
) -> None:
    """Continuously monitor open positions for exit conditions."""
    exit_cfg = cfg.get("exit", {})
    take_profit = exit_cfg.get("take_profit_pct", 0.10)
    stop_loss = exit_cfg.get("stop_loss_pct", 0.05)
    timeout_min = exit_cfg.get("timeout_minutes", 30)
    poll = cfg.get("trading", {}).get("poll_interval_seconds", 20)

    while True:
        try:
            positions = await state.get_open_positions()
            for trade in positions:
                elapsed_min = (time.time() - trade.entry_time) / 60
                exit_price: float | None = None
                reason = ""

                # Simulated exit price drift (paper trading)
                simulated_price = trade.entry_price * (1 + 0.001 * elapsed_min)

                gain_pct = (simulated_price - trade.entry_price) / trade.entry_price
                if gain_pct >= take_profit:
                    exit_price = simulated_price
                    reason = "take_profit"
                elif gain_pct <= -stop_loss:
                    exit_price = simulated_price
                    reason = "stop_loss"
                elif elapsed_min >= timeout_min:
                    exit_price = simulated_price
                    reason = "timeout"

                if exit_price is not None:
                    pnl = (exit_price - trade.entry_price) * trade.size - trade.fee
                    await state.close_trade(trade.market_id, exit_price, pnl)

                    if pnl >= 0:
                        cb.record_win()
                    else:
                        cb.record_loss()

                    await bus.publish(
                        EventEnvelope(
                            event_type=STATE_UPDATED,
                            source="exit_monitor",
                            correlation_id=trade.correlation_id,
                            market_id=trade.market_id,
                            payload={
                                "action": "TRADE_CLOSED",
                                "trade": {
                                    "market_id": trade.market_id,
                                    "question": trade.question,
                                    "entry_price": trade.entry_price,
                                    "exit_price": exit_price,
                                    "size": trade.size,
                                    "pnl": round(pnl, 4),
                                    "reason": reason,
                                },
                            },
                        )
                    )
        except Exception as exc:
            log.error("exit_monitor_error", error=str(exc))

        await asyncio.sleep(poll)


async def main() -> None:
    """Entry point for Phase 4 event-driven bot."""
    load_dotenv()
    import structlog
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )

    config_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
    cfg = _load_config(config_path)

    trading_cfg = cfg.get("trading", {})
    paper_cfg = cfg.get("paper", {})
    cb_cfg = cfg.get("circuit_breaker", {})
    health_port = cfg.get("health", {}).get("port", 8080)
    initial_balance = paper_cfg.get("initial_balance", 1000.0)
    poll_interval = trading_cfg.get("poll_interval_seconds", 20)
    summary_every = trading_cfg.get("summary_every_n_cycles", 5)

    # Infrastructure
    state = StateManager(os.getenv("DB_PATH", "polyquantbot_phase4.db"))
    await state.init()

    bus = EventBus()
    cb = CircuitBreaker(
        bus=bus,
        max_consecutive_losses=cb_cfg.get("max_consecutive_losses", 3),
        max_api_failures=cb_cfg.get("max_api_failures", 5),
        latency_breach_threshold_ms=cb_cfg.get("latency_breach_threshold_ms", 1000),
        cooldown_seconds=cb_cfg.get("cooldown_seconds", 120),
    )

    model = BayesianSignalModel(cfg)
    client = PolymarketClient()
    tracker = PerformanceTracker()
    telegram = TelegramService(
        token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
    )

    # Wire pipeline handlers (stages 1–5)
    make_handlers(bus, state, model, cb, cfg)

    # Wire Telegram as pure STATE_UPDATED subscriber
    bus.subscribe(STATE_UPDATED, telegram.handle_state_updated)

    # Wire circuit breaker relay
    async def handle_circuit_breaker_event(envelope: EventEnvelope) -> None:
        """Relay CB open event to Telegram via STATE_UPDATED."""
        await bus.publish(
            EventEnvelope(
                event_type=STATE_UPDATED,
                source="circuit_breaker_relay",
                correlation_id=envelope.correlation_id,
                payload={
                    "action": "CIRCUIT_OPEN",
                    "reason": envelope.payload.get("reason", "unknown"),
                    "cooldown_seconds": envelope.payload.get("cooldown_seconds", 120),
                },
            )
        )

    bus.subscribe(CIRCUIT_BREAKER_OPEN, handle_circuit_breaker_event)

    # Pipeline state shared with health server
    pipeline_state: dict[str, Any] = {
        "state": "running",
        "cycle": 0,
        "initial_balance": initial_balance,
    }

    # Start background tasks
    health_runner = await start_health_server(state, pipeline_state, port=health_port)
    exit_task = asyncio.create_task(
        exit_monitor_loop(state, bus, cb, cfg)
    )

    log.info("phase4_runner_started", initial_balance=initial_balance)

    cycle = 0
    try:
        while True:
            cycle += 1
            pipeline_state["cycle"] = cycle

            if not cb.is_open():
                try:
                    markets = await client.fetch_markets(limit=20)
                    for market in markets:
                        correlation_id = str(uuid.uuid4())
                        await bus.publish(
                            EventEnvelope(
                                event_type=MARKET_DATA,
                                source="polymarket_client",
                                correlation_id=correlation_id,
                                market_id=market.market_id,
                                payload={"market": market.__dict__},
                            )
                        )
                    cb._api_failures = 0  # reset on success
                except Exception as exc:
                    log.error("market_fetch_error", error=str(exc))
                    cb.record_api_failure()
            else:
                log.warning("circuit_breaker_open_skip_cycle", cycle=cycle)

            # Periodic summary
            if cycle % summary_every == 0:
                realized_pnl = await state.get_balance()
                balance = initial_balance + realized_pnl
                open_positions = await state.get_open_positions()
                stats = tracker.snapshot()
                await bus.publish(
                    EventEnvelope(
                        event_type=STATE_UPDATED,
                        source="runner",
                        payload={
                            "action": "SUMMARY",
                            "balance": balance,
                            "initial_balance": initial_balance,
                            "open_count": len(open_positions),
                            "stats": stats,
                        },
                    )
                )

            await asyncio.sleep(poll_interval)

    except asyncio.CancelledError:
        log.info("runner_cancelled")
    finally:
        exit_task.cancel()
        await bus.shutdown()
        await state.close()
        await health_runner.cleanup()
        log.info("phase4_runner_stopped")


if __name__ == "__main__":
    asyncio.run(main())
