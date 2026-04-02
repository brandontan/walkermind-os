"""PolyQuantBot — Production entrypoint.

Starts the full trading pipeline with an optional dashboard control panel.

Environment variables:
    TRADING_MODE          — "PAPER" | "LIVE"  (default: "PAPER")
    ENABLE_LIVE_TRADING   — "true" required for LIVE mode
    DASHBOARD_ENABLED     — "true" to start the dashboard server
    DASHBOARD_API_KEY     — Bearer token for dashboard auth
    PORT                  — TCP port for dashboard (Railway injects this)
    REDIS_URL             — Redis connection URL
    DB_DSN                — PostgreSQL DSN
    TELEGRAM_BOT_TOKEN    — Telegram bot token (optional)
    TELEGRAM_CHAT_ID      — Telegram chat ID (optional)

Startup sequence:
    1. Load LiveConfig from environment
    2. Initialise core components (state manager, config manager, risk guard)
    3. Initialise metrics exporter
    4. Initialise command handler
    5. Start dashboard server as background task (if DASHBOARD_ENABLED=true)
    6. Run trading pipeline

Design:
    - asyncio only — no blocking calls
    - Structured logging on every lifecycle event
    - Graceful shutdown on SIGTERM / SIGINT
    - Fail-fast on invalid env config with clear error log
    - No silent failure
"""
from __future__ import annotations

import asyncio
import os
import signal
import sys
import time
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

# ── Startup log (emitted before any imports so Railway sees it early) ──────────
print("🚀 PolyQuantBot starting (Railway)")


# ── Main ───────────────────────────────────────────────────────────────────────


async def main() -> None:
    """Async entrypoint — initialise all components and run the pipeline."""
    start_ts = time.time()

    log.info("polyquantbot_startup", ts=start_ts)

    # ── Load live config from environment ──────────────────────────────────────
    try:
        from .infra.live_config import LiveConfig
        config = LiveConfig.from_env()
        config.validate()
    except Exception as exc:
        log.error(
            "polyquantbot_config_error",
            error=str(exc),
            hint="Check TRADING_MODE and ENABLE_LIVE_TRADING env vars",
        )
        sys.exit(1)

    mode: str = config.trading_mode.value  # "PAPER" | "LIVE"
    log.info("polyquantbot_mode", mode=mode)

    # ── Core components ────────────────────────────────────────────────────────
    from .core.system_state import SystemStateManager
    from .config.runtime_config import ConfigManager

    state_manager = SystemStateManager()
    config_manager = ConfigManager()

    # ── Risk guard (lightweight stub for startup) ──────────────────────────────
    from .risk.risk_guard import RiskGuard
    risk_guard = RiskGuard(
        daily_loss_limit=config.daily_loss_limit,
        max_drawdown_pct=config.drawdown_limit,
    )

    # ── Fill tracker ───────────────────────────────────────────────────────────
    from .execution.fill_tracker import FillTracker
    fill_tracker = FillTracker()

    # ── Metrics exporter ───────────────────────────────────────────────────────
    from .monitoring.metrics_exporter import MetricsExporter
    metrics_exporter = MetricsExporter(
        risk_guard=risk_guard,
        fill_tracker=fill_tracker,
    )
    await metrics_exporter.start_logging_loop()

    # ── Telegram (optional) ────────────────────────────────────────────────────
    from .telegram.telegram_live import TelegramLive
    tg = TelegramLive.from_env()
    await tg.start()
    chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    telegram_sender = tg.alert_error if tg.enabled else None

    # ── Startup Telegram notification ─────────────────────────────────────────
    await tg.alert_startup(mode=mode, market_count=0)

    # ── System activation monitor ──────────────────────────────────────────────
    from .monitoring.system_activation import SystemActivationMonitor
    activation_monitor = SystemActivationMonitor()
    await activation_monitor.start()

    # ── Command handler ────────────────────────────────────────────────────────
    from .telegram.command_handler import CommandHandler
    cmd_handler = CommandHandler(
        state_manager=state_manager,
        config_manager=config_manager,
        metrics_source=metrics_exporter,
        telegram_sender=telegram_sender,
        chat_id=chat_id,
        mode=mode,
    )

    # ── Dashboard server (optional) ────────────────────────────────────────────
    dashboard_enabled = os.getenv("DASHBOARD_ENABLED", "false").strip().lower() == "true"
    if dashboard_enabled:
        try:
            from .api.dashboard_server import DashboardServer
            dashboard = DashboardServer(
                command_handler=cmd_handler,
                state_manager=state_manager,
                metrics_exporter=metrics_exporter,
                fill_tracker=fill_tracker,
                mode=mode,
            )
            asyncio.create_task(dashboard.start(), name="dashboard_server")
            log.info("dashboard_server_task_created")
        except Exception as exc:
            log.error(
                "dashboard_server_init_failed",
                error=str(exc),
                hint="Dashboard disabled — trading pipeline continues",
            )
    else:
        log.info("dashboard_disabled", hint="Set DASHBOARD_ENABLED=true to enable")

    # ── Metrics HTTP server (lightweight /health + /metrics) ───────────────────
    from .monitoring.server import MetricsServer
    metrics_server = MetricsServer(exporter=metrics_exporter)
    asyncio.create_task(metrics_server.start(), name="metrics_server")

    # ── Heartbeat task (configurable, smart — only sends on activity change) ──
    _heartbeat_interval_s = int(os.environ.get("HEARTBEAT_INTERVAL_MIN", "30")) * 60
    _heartbeat_enabled = os.environ.get("HEARTBEAT_ENABLED", "true").lower() != "false"

    async def _heartbeat_loop() -> None:
        """Send Telegram ALIVE only when something changed, or at forced interval."""
        _last_events = 0
        _last_signals = 0
        _last_trades = 0
        _last_ws = False
        _last_sent_ts = 0.0
        poll_s = 60.0  # internal poll — check every 60s but only send at interval

        while True:
            await asyncio.sleep(poll_s)
            if not _heartbeat_enabled:
                continue

            now = time.time()
            cur_events = activation_monitor.event_count
            cur_signals = activation_monitor.signal_count
            cur_trades = activation_monitor.trade_count
            cur_ws = activation_monitor.ws_connected

            changed = (
                cur_events != _last_events
                or cur_signals != _last_signals
                or cur_trades != _last_trades
                or cur_ws != _last_ws
            )
            interval_elapsed = (now - _last_sent_ts) >= _heartbeat_interval_s

            # Only send if: activity changed OR forced interval elapsed
            if changed or interval_elapsed:
                await tg.alert_heartbeat(
                    ws_connected=cur_ws,
                    event_count=cur_events,
                    signal_count=cur_signals,
                    trade_count=cur_trades,
                )
                _last_events = cur_events
                _last_signals = cur_signals
                _last_trades = cur_trades
                _last_ws = cur_ws
                _last_sent_ts = now

    asyncio.create_task(_heartbeat_loop(), name="telegram_heartbeat")

    # ── Graceful shutdown handler ──────────────────────────────────────────────
    stop_event = asyncio.Event()

    def _handle_signal(signum: int, frame: object) -> None:
        log.info("polyquantbot_shutdown_signal", signum=signum)
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _handle_signal)
        except (OSError, ValueError):
            pass

    log.info(
        "polyquantbot_running",
        mode=mode,
        dashboard_enabled=dashboard_enabled,
        startup_s=round(time.time() - start_ts, 3),
    )

    # ── Keep running until stop signal ────────────────────────────────────────
    await stop_event.wait()

    log.info("polyquantbot_shutdown_started")
    await activation_monitor.stop()
    await tg.stop()
    await metrics_exporter.stop_logging_loop()
    try:
        await metrics_server.stop()
    except Exception as exc:
        log.warning("metrics_server_stop_error", error=str(exc))
    log.info("polyquantbot_shutdown_complete")


# ── Module-level runner ────────────────────────────────────────────────────────


def run() -> None:
    """Synchronous wrapper — called by the root main.py and Procfile."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("polyquantbot_keyboard_interrupt")
    except Exception as exc:
        log.error("polyquantbot_fatal_error", error=str(exc), exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    run()
