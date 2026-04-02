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
    telegram_sender = None  # polling loop handles all command replies directly

    # ── System activation monitor ──────────────────────────────────────────────
    from .monitoring.system_activation import SystemActivationMonitor
    activation_monitor = SystemActivationMonitor()
    await activation_monitor.start()

    # ── WebSocket client (data feed) ──────────────────────────────────────────
    from .data.websocket.ws_client import PolymarketWSClient
    _raw_market_ids = os.getenv("MARKET_IDS", "").strip()
    market_ids: list[str] = (
        [mid.strip() for mid in _raw_market_ids.split(",") if mid.strip()]
        if _raw_market_ids and _raw_market_ids.lower() != "auto"
        else []
    )
    ws_client: Optional[PolymarketWSClient] = None
    if market_ids:
        ws_client = PolymarketWSClient.from_env(market_ids=market_ids)
        await ws_client.connect()
        log.info("polyquantbot_ws_started", market_count=len(market_ids))

        async def _ws_event_loop() -> None:
            async for event in ws_client.events():  # type: ignore[union-attr]
                activation_monitor.record_event()

        asyncio.create_task(_ws_event_loop(), name="ws_event_loop")
    else:
        log.warning(
            "polyquantbot_no_market_ids",
            hint="Set MARKET_IDS env var (comma-separated condition IDs) to enable WS feed",
        )

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
    _heartbeat_enabled = False  # disabled — use /status command instead

    async def _heartbeat_loop() -> None:
        """Send Telegram ALIVE only when something changed, or at forced interval."""
        _last_events = 0
        _last_signals = 0
        _last_trades = 0
        _last_ws = False
        _last_sent_ts = time.time()  # start from now — avoid immediate first send
        poll_s = 60.0  # internal poll — check every 60s but only send at interval

        while True:
            await asyncio.sleep(poll_s)
            if not _heartbeat_enabled:
                continue

            now = time.time()
            # Pull live stats from runner snapshot if available, else zeros
            if runner is not None:
                try:
                    snap = runner.snapshot()
                    cur_events = snap.event_count
                    cur_signals = snap.signal_count
                    cur_trades = snap.fill_count
                    cur_ws = runner._ws._stats.connected
                except Exception:
                    cur_events = activation_monitor.event_count
                    cur_signals = activation_monitor.signal_count
                    cur_trades = activation_monitor.trade_count
                    cur_ws = False
            else:
                cur_events = activation_monitor.event_count
                cur_signals = activation_monitor.signal_count
                cur_trades = activation_monitor.trade_count
                cur_ws = False

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

    # ── Telegram command polling loop ──────────────────────────────────────────
    _tg_token = os.environ.get("TELEGRAM_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    _tg_api = f"https://api.telegram.org/bot{_tg_token}"

    async def _polling_loop() -> None:
        """Long-poll Telegram getUpdates and route commands + callback_query."""
        import aiohttp as _aio
        from .telegram.command_router import CommandRouter
        from .telegram.command_handler import CommandResult as _CR
        CommandResult = _CR
        router = CommandRouter(handler=cmd_handler)
        offset = 0
        log.info("telegram_polling_started")

        async def _send_result(session, chat_id, result, callback_query_id=None):
            if callback_query_id:
                await session.post(f"{_tg_api}/answerCallbackQuery",
                                   json={"callback_query_id": callback_query_id})
            if not result or not result.message:
                return
            payload = {"chat_id": chat_id, "text": result.message, "parse_mode": "Markdown"}
            keyboard = (result.payload or {}).get("_keyboard")
            if keyboard:
                payload["reply_markup"] = {"inline_keyboard": keyboard}
            await session.post(f"{_tg_api}/sendMessage", json=payload)

        async with _aio.ClientSession() as session:
            while True:
                try:
                    async with session.get(
                        f"{_tg_api}/getUpdates",
                        params={"offset": offset, "timeout": 10, "limit": 10},
                        timeout=_aio.ClientTimeout(total=15),
                    ) as resp:
                        data = await resp.json()

                    for update in data.get("result", []):
                        offset = update["update_id"] + 1

                        # ── Inline button press ────────────────────────────
                        cq = update.get("callback_query")
                        if cq:
                            cb_data = (cq.get("data") or "").strip()
                            cb_chat = cq.get("message", {}).get("chat", {}).get("id")
                            cb_user = cq.get("from", {}).get("id", 0)
                            if cb_data and cb_chat:
                                if cb_data.endswith("_prompt"):
                                    cmd_key = cb_data.replace("_prompt", "")
                                    await _send_result(session, cb_chat, CommandResult(
                                        success=True,
                                        message=f"Type: `/{cmd_key} <value>`"
                                    ), callback_query_id=cq["id"])
                                    continue
                                fake = {"update_id": update["update_id"],
                                        "message": {"text": f"/{cb_data}",
                                                    "chat": {"id": cb_chat},
                                                    "from": {"id": cb_user}}}
                                result = await router.route_update(fake)
                                await _send_result(session, cb_chat, result,
                                                   callback_query_id=cq["id"])
                            continue

                        # ── Regular text command ───────────────────────────
                        msg = update.get("message") or update.get("edited_message")
                        if not msg:
                            continue
                        text = (msg.get("text") or "").strip()
                        if not text.startswith("/"):
                            continue
                        text = text.split("@")[0]
                        msg["text"] = text
                        result = await router.route_update(update)
                        reply_chat = msg.get("chat", {}).get("id")
                        if reply_chat:
                            await _send_result(session, reply_chat, result)

                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.warning("telegram_polling_error", error=str(exc))
                    await asyncio.sleep(5)

    if _tg_token:
        asyncio.create_task(_polling_loop(), name="telegram_polling")

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

    # ── Bootstrap: market discovery + pipeline startup ─────────────────────────
    from .core.bootstrap import run_bootstrap
    from .core.pipeline.live_paper_runner import LivePaperRunner

    runner: Optional["LivePaperRunner"] = None
    pipeline_task = None
    try:
        cfg, market_ids, market_meta = await run_bootstrap()

        # ── Send STARTUP alert with real market count ──────────────────────────
        await tg.alert_startup(mode=mode, market_count=len(market_ids))

        runner = LivePaperRunner.from_config(cfg=cfg, market_ids=market_ids)
        await runner.start()

        # Sync discovered market IDs + metadata into config_manager
        config_manager.update_market_ids(market_ids, market_meta)

        # Wire runner into command handler for live /status data
        if hasattr(cmd_handler, "set_runner"):
            cmd_handler.set_runner(runner)

        pipeline_task = asyncio.create_task(runner.run(), name="trading_pipeline")
        log.info(
            "polyquantbot_pipeline_started",
            market_count=len(market_ids),
            market_ids=market_ids[:5],
        )
    except Exception as exc:
        log.error(
            "polyquantbot_pipeline_start_failed",
            error=str(exc),
            hint="Check market IDs, CLOB credentials, and Gamma API connectivity",
        )
        await tg.alert_error(str(exc), context="pipeline_startup")

    # ── Keep running until stop signal ────────────────────────────────────────
    await stop_event.wait()

    log.info("polyquantbot_shutdown_started")
    if pipeline_task is not None and not pipeline_task.done():
        try:
            await runner.stop()
        except Exception:
            pass
        pipeline_task.cancel()
        try:
            await pipeline_task
        except asyncio.CancelledError:
            pass
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
