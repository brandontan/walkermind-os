"""PolyQuantBot — Production entrypoint.

Starts the full trading pipeline with an optional dashboard control panel.

Environment variables:
    TRADING_MODE          — "PAPER" | "LIVE"  (default: "PAPER")
    ENABLE_LIVE_TRADING   — "true" required for LIVE mode
    DASHBOARD_ENABLED     — "true" to start the dashboard server
    DASHBOARD_API_KEY     — Bearer token for dashboard auth
    PORT                  — TCP port for dashboard (Railway injects this)
    REDIS_URL             — Redis connection URL
    DATABASE_URL          — PostgreSQL DSN (canonical)
    DB_DSN                — Compatibility fallback only
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
from pathlib import Path
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[3]))

# ── Startup log (emitted before any imports so Railway sees it early) ──────────
print("🚀 PolyQuantBot starting (Railway)")


# ── Main ───────────────────────────────────────────────────────────────────────


async def main() -> None:
    """Async entrypoint — initialise all components and run the pipeline."""
    start_ts = time.time()

    log.info("polyquantbot_startup", ts=start_ts)

    from projects.polymarket.polyquantbot.core.startup_phase import (
        StartupPhase,
        StartupStateTracker,
    )
    startup_state = StartupStateTracker()

    # ── Entrypoint assertion — confirms correct runtime path ───────────────────
    print("🚀 NEW TELEGRAM SYSTEM ACTIVE")
    print("ENTRYPOINT: main.py")
    log.info(
        "entrypoint_active",
        entrypoint="projects/polymarket/polyquantbot/main.py",
        system="NEW_TELEGRAM_SYSTEM",
        status="ACTIVE",
        legacy_menu="DISABLED",
    )

    # ── Load live config from environment ──────────────────────────────────────
    try:
        from projects.polymarket.polyquantbot.infra.live_config import LiveConfig
        from projects.polymarket.polyquantbot.config.startup_validation import (
            validate_startup_environment,
        )

        config = LiveConfig.from_env()
        config.validate()
        mode: str = config.trading_mode.value  # "PAPER" | "LIVE"
        startup_cfg = validate_startup_environment(mode=mode)
        log.info(
            "startup_config_validated",
            mode=mode,
            db_host=startup_cfg.db_host,
            db_port=startup_cfg.db_port,
            db_name=startup_cfg.db_name,
            db_user=startup_cfg.db_user,
        )
    except Exception as exc:
        startup_state.set_phase(
            StartupPhase.BLOCKED,
            reason=f"config_validation_failed: {exc}",
        )
        log.error(
            "polyquantbot_config_error",
            error=str(exc),
            hint="Validate DATABASE_URL, required secrets, and paper/live mode consistency",
            **startup_state.snapshot(),
        )
        sys.exit(1)

    log.info("polyquantbot_mode", mode=mode, **startup_state.snapshot())

    # ── Core components ────────────────────────────────────────────────────────
    from projects.polymarket.polyquantbot.core.system_state import SystemStateManager
    from projects.polymarket.polyquantbot.config.runtime_config import ConfigManager

    state_manager = SystemStateManager()
    config_manager = ConfigManager()

    # ── Risk guard (lightweight stub for startup) ──────────────────────────────
    from projects.polymarket.polyquantbot.risk.risk_guard import RiskGuard
    risk_guard = RiskGuard(
        daily_loss_limit=config.daily_loss_limit,
        max_drawdown_pct=config.drawdown_limit,
    )

    # ── Fill tracker ───────────────────────────────────────────────────────────
    from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker
    fill_tracker = FillTracker()

    # ── Metrics exporter ───────────────────────────────────────────────────────
    from projects.polymarket.polyquantbot.monitoring.metrics_exporter import MetricsExporter
    metrics_exporter = MetricsExporter(
        risk_guard=risk_guard,
        fill_tracker=fill_tracker,
    )
    await metrics_exporter.start_logging_loop()

    # ── Telegram (optional) ────────────────────────────────────────────────────
    from projects.polymarket.polyquantbot.telegram.telegram_live import TelegramLive
    from projects.polymarket.polyquantbot.telegram.utils import telegram_sender as _telegram_sender
    tg = TelegramLive.from_env()
    await tg.start()
    chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    telegram_sender = None  # polling loop handles all command replies directly

    # ── System activation monitor ──────────────────────────────────────────────
    from projects.polymarket.polyquantbot.monitoring.system_activation import SystemActivationMonitor
    activation_monitor = SystemActivationMonitor()
    await activation_monitor.start()

    # ── WebSocket client (data feed) ──────────────────────────────────────────
    from projects.polymarket.polyquantbot.data.websocket.ws_client import PolymarketWSClient
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

    # ── Strategy state manager ─────────────────────────────────────────────────
    from projects.polymarket.polyquantbot.strategy.strategy_manager import StrategyStateManager
    strategy_mgr = StrategyStateManager()

    # ── Multi-strategy metrics ─────────────────────────────────────────────────
    from projects.polymarket.polyquantbot.monitoring.multi_strategy_metrics import MultiStrategyMetrics
    multi_metrics = MultiStrategyMetrics(["ev_momentum", "mean_reversion", "liquidity_edge"])
    log.info("metrics_initialized", initialized=True)

    # ── Command handler ────────────────────────────────────────────────────────
    from projects.polymarket.polyquantbot.telegram.command_handler import CommandHandler
    cmd_handler = CommandHandler(
        state_manager=state_manager,
        config_manager=config_manager,
        metrics_source=metrics_exporter,
        telegram_sender=telegram_sender,
        chat_id=chat_id,
        mode=mode,
        multi_metrics=multi_metrics,
    )

    # ── Dashboard server (optional) ────────────────────────────────────────────
    dashboard_enabled = os.getenv("DASHBOARD_ENABLED", "false").strip().lower() == "true"
    if dashboard_enabled:
        try:
            from projects.polymarket.polyquantbot.api.dashboard_server import DashboardServer
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
            startup_state.set_phase(
                StartupPhase.DEGRADED,
                reason=f"dashboard_init_failed: {exc}",
            )
            log.error(
                "dashboard_server_init_failed",
                error=str(exc),
                hint="Dashboard disabled — trading pipeline continues",
                **startup_state.snapshot(),
            )
    else:
        log.info("dashboard_disabled", hint="Set DASHBOARD_ENABLED=true to enable")

    # ── Metrics HTTP server (lightweight /health + /metrics) ───────────────────
    from projects.polymarket.polyquantbot.monitoring.server import MetricsServer
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

    # ── Centralized callback router (action: prefix → editMessageText) ─────────
    from projects.polymarket.polyquantbot.telegram.handlers.callback_router import CallbackRouter as _CallbackRouter
    _callback_router = _CallbackRouter(
        tg_api=_tg_api,
        cmd_handler=cmd_handler,
        state_manager=state_manager,
        config_manager=config_manager,
        mode=mode,
        strategy_state=strategy_mgr,
    )

    _telegram_sender.load_user_chat_id()

    async def _polling_loop() -> None:
        """Long-poll Telegram getUpdates and route commands + callback_query.

        Routing:
            callback_query with ``action:*`` data → CallbackRouter
                (uses editMessageText — single active message, no duplicates)
            Reply keyboard text (e.g. "📊 Trade") → on_text_message()
                (maps to action:* and routes via CallbackRouter)
            Text commands (``/status``, ``/kill``, etc.) → CommandRouter
                (uses sendMessage — always creates new message)
        """
        import aiohttp as _aio
        from projects.polymarket.polyquantbot.telegram.command_router import CommandRouter
        from projects.polymarket.polyquantbot.telegram.command_handler import CommandResult as _CR
        from projects.polymarket.polyquantbot.telegram.ui.reply_keyboard import (
            get_main_reply_keyboard,
            REPLY_MENU_MAP,
            _REPLY_KB_READY_MSG,
        )
        from projects.polymarket.polyquantbot.telegram.handlers.text_handler import schedule_user_message_delete
        CommandResult = _CR
        router = CommandRouter(handler=cmd_handler)
        offset = 0
        # chat_id → message_id of the active inline message (used for editMessageText
        # when reply keyboard buttons are pressed without an existing callback_query)
        _inline_msg_ids: dict[int, int] = {}
        log.info("telegram_polling_started")

        async def _send_result(session, reply_chat_id, result, callback_query_id=None):
            """Send a new message for text command responses."""
            if callback_query_id:
                # Answer legacy callback (non-action: format) to clear spinner
                try:
                    await session.post(
                        f"{_tg_api}/answerCallbackQuery",
                        json={"callback_query_id": callback_query_id},
                    )
                except Exception:
                    pass
            if not result or not result.message:
                return
            payload = {
                "chat_id": reply_chat_id,
                "text": result.message,
                "parse_mode": "Markdown",
            }
            keyboard = (result.payload or {}).get("_keyboard")
            if keyboard:
                payload["reply_markup"] = {"inline_keyboard": keyboard}
            try:
                resp = await session.post(f"{_tg_api}/sendMessage", json=payload)
                resp_data = await resp.json()
                sent_msg_id = (
                    resp_data.get("result", {}).get("message_id")
                    if resp_data.get("ok")
                    else None
                )
                if sent_msg_id:
                    _inline_msg_ids[reply_chat_id] = sent_msg_id
            except Exception as exc:
                log.warning("polling_send_message_failed", error=str(exc))

        async def _on_text_message(session, chat_id: int, text: str) -> None:
            """Handle reply keyboard button presses.

            Maps button label → action and dispatches through CallbackRouter
            so the single active inline message is edited in-place.
            If no active inline message exists for this chat, sends a new one
            and tracks its message_id.
            """
            action = REPLY_MENU_MAP.get(text)
            if not action:
                return
            log.info("reply_menu_click", action=action, text=text)
            inline_msg_id = _inline_msg_ids.get(chat_id)
            if inline_msg_id:
                # Synthesise a minimal callback_query so CallbackRouter can
                # editMessageText on the active inline message.
                synthetic_cq: dict = {
                    "id": "reply_kb",
                    "data": f"action:{action}",
                    "from": {"id": chat_id},
                    "message": {
                        "message_id": inline_msg_id,
                        "chat": {"id": chat_id},
                    },
                }
                await _callback_router.route(session, synthetic_cq)
            else:
                # No active inline message yet — create one (same as /start inline
                # portion) and track its message_id for future edits.
                from projects.polymarket.polyquantbot.telegram.ui.keyboard import build_main_menu
                from projects.polymarket.polyquantbot.telegram.ui.screens import main_screen
                snap_state = state_manager.snapshot()
                result_obj = CommandResult(
                    success=True,
                    message=main_screen(
                        mode=mode,
                        state=snap_state.get("state", "UNKNOWN"),
                    ),
                    payload={"_keyboard": build_main_menu()},
                )
                await _send_result(session, chat_id, result_obj)

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
                                if cb_data.startswith("action:"):
                                    # ── New system: edit in-place ──────────
                                    await _callback_router.route(session, cq)
                                elif cb_data.endswith("_prompt"):
                                    # ── Legacy prompt helper ───────────────
                                    cmd_key = cb_data.replace("_prompt", "")
                                    await _send_result(
                                        session, cb_chat,
                                        CommandResult(
                                            success=True,
                                            message=f"Type: `/{cmd_key} <value>`",
                                        ),
                                        callback_query_id=cq["id"],
                                    )
                                else:
                                    # ── Legacy fallback: route via text ───
                                    fake = {
                                        "update_id": update["update_id"],
                                        "message": {
                                            "text": f"/{cb_data}",
                                            "chat": {"id": cb_chat},
                                            "from": {"id": cb_user},
                                        },
                                    }
                                    result = await router.route_update(fake)
                                    await _send_result(
                                        session, cb_chat, result,
                                        callback_query_id=cq["id"],
                                    )
                            continue

                        # ── Regular text / reply-keyboard click ───────────
                        msg = update.get("message") or update.get("edited_message")
                        if not msg:
                            continue
                        text = (msg.get("text") or "").strip()
                        reply_chat = msg.get("chat", {}).get("id")

                        if not text.startswith("/"):
                            # ── Reply keyboard menu click ──────────────────
                            if reply_chat and text in REPLY_MENU_MAP:
                                msg_id = msg.get("message_id")
                                if msg_id:
                                    await schedule_user_message_delete(
                                        tg_api=_tg_api,
                                        chat_id=reply_chat,
                                        message_id=msg_id,
                                    )
                                await _on_text_message(session, reply_chat, text)
                            continue

                        text = text.split("@")[0]
                        msg["text"] = text
                        cmd_name = text.lstrip("/").split()[0].lower()
                        result = await router.route_update(update)
                        if reply_chat:
                            # ── /start: send reply keyboard first ─────────
                            if cmd_name in ("start", "help", "menu", "main_menu"):
                                if cmd_name == "start":
                                    _telegram_sender.set_user_chat_id(reply_chat)
                                try:
                                    await session.post(
                                        f"{_tg_api}/sendMessage",
                                        json={
                                            "chat_id": reply_chat,
                                            "text": _REPLY_KB_READY_MSG,
                                            "reply_markup": get_main_reply_keyboard(),
                                        },
                                    )
                                except Exception as exc:
                                    log.warning(
                                        "reply_keyboard_send_failed",
                                        error=str(exc),
                                    )
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
        **startup_state.snapshot(),
    )

    # ── Database initialisation (required — no silent fallback) ───────────────
    from projects.polymarket.polyquantbot.infra.db import DatabaseClient
    db = DatabaseClient()
    try:
        await db.connect_with_retry(max_attempts=4, base_backoff_s=1.0)
        log.info("db_enabled", status=True)
    except Exception as db_exc:
        startup_state.set_phase(
            StartupPhase.BLOCKED,
            reason=f"database_unavailable: {db_exc}",
        )
        log.error(
            "db_init_failed",
            error=str(db_exc),
            hint="Check DATABASE_URL and PostgreSQL network reachability; execution remains blocked",
            final_reason="database_required_for_audit_and_trade_safety",
            **startup_state.snapshot(),
        )
        await tg.alert_error(
            f"Startup blocked: database unavailable ({db_exc})",
            context="startup_database",
        )
        raise RuntimeError(f"Database required — startup aborted: {db_exc}") from db_exc

    startup_state.set_phase(StartupPhase.RUNNING, reason="database_ready")

    # ── Load strategy state from DB and wire DB into callback router ──────────
    await strategy_mgr.load(db=db)
    _callback_router.set_db(db)
    log.info("strategy_state_loaded_from_db", state=strategy_mgr.get_state())

    # ── Market metadata cache ──────────────────────────────────────────────────
    from projects.polymarket.polyquantbot.core.market.market_cache import MarketMetadataCache
    market_cache = MarketMetadataCache()
    await market_cache.start()
    log.info("market_cache_started", size=market_cache.size())

    # ── Position manager (in-memory position tracker) ─────────────────────────
    from projects.polymarket.polyquantbot.core.portfolio.position_manager import PositionManager
    position_manager = PositionManager()
    log.info("position_manager_initialized")

    # ── PnL tracker ───────────────────────────────────────────────────────────
    from projects.polymarket.polyquantbot.core.portfolio.pnl import PnLTracker
    pnl_tracker = PnLTracker(db=db)
    log.info("pnl_tracker_initialized")

    # ── Wire trade-visibility handlers ────────────────────────────────────────
    from projects.polymarket.polyquantbot.telegram.handlers.performance import (
        set_multi_metrics as _set_perf_metrics,
        set_pnl_tracker as _set_perf_pnl,
    )
    from projects.polymarket.polyquantbot.telegram.handlers.positions import (
        set_position_manager as _set_pos_pm,
        set_market_cache as _set_pos_mc,
        set_pnl_tracker as _set_pos_pnl,
    )
    from projects.polymarket.polyquantbot.telegram.handlers.pnl import set_pnl_tracker as _set_pnl_handler
    from projects.polymarket.polyquantbot.telegram.handlers.portfolio_service import get_portfolio_service as _get_portfolio_service
    _set_perf_metrics(multi_metrics)
    _set_perf_pnl(pnl_tracker)
    _set_pos_pm(position_manager)
    _set_pos_mc(market_cache)
    _set_pos_pnl(pnl_tracker)
    _set_pnl_handler(pnl_tracker)
    _portfolio_service = _get_portfolio_service()
    _portfolio_service.set_pnl_tracker(pnl_tracker)
    log.info("trade_visibility_handlers_wired")

    # ── Paper trading engine container (wallet, positions, ledger, exposure) ───
    from projects.polymarket.polyquantbot.execution.engine_router import get_engine_container as _get_engines
    engine_container = _get_engines()

    # Restore persisted wallet / positions / ledger from DB on startup
    try:
        await engine_container.restore_from_db(db)
        log.info("engine_container_state_restored", mode=mode)
    except Exception as _restore_exc:
        log.warning("engine_container_restore_failed", error=str(_restore_exc))

    # Inject paper engines into Telegram handlers (wallet, trade, exposure)
    engine_container.inject_into_handlers()

    # Also inject PnLTracker into trade handler (realized PnL display)
    from projects.polymarket.polyquantbot.telegram.handlers.trade import set_pnl_tracker as _set_trade_pnl
    _set_trade_pnl(pnl_tracker)
    log.info("paper_engine_handlers_wired", mode=mode)

    # Inject paper engine references into callback router
    _callback_router.set_paper_wallet_engine(engine_container.wallet)
    _callback_router.set_paper_engine(engine_container.paper_engine)
    _callback_router.set_paper_position_manager(engine_container.positions)
    _callback_router.set_exposure_calculator(engine_container.exposure)
    _portfolio_service.set_wallet_engine(engine_container.wallet)
    _portfolio_service.set_position_manager(engine_container.positions)
    log.info("callback_router_engines_injected", mode=mode)

    # ── Telegram callback — accepts a pre-formatted string ────────────────────
    from projects.polymarket.polyquantbot.telegram.telegram_live import AlertType as _AlertType

    async def _tg_send(message: str) -> None:
        """Forward a pre-formatted string to Telegram (2-retry wrapper)."""
        if not tg.enabled:
            return
        for attempt in range(2):
            try:
                await tg._enqueue(_AlertType.TRADE, message, None)
                return
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "telegram_callback_retry",
                    attempt=attempt + 1,
                    error=str(exc),
                )
        log.error("telegram_callback_failed", retries=2, message_preview=message[:80])

    async def _tg_send_private(chat_id: int, message: str) -> None:
        """Send message to explicit private chat_id using Telegram Bot API."""
        import aiohttp

        if not tg.enabled:
            return
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{_tg_api}/sendMessage",
                    json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        log.warning(
                            "telegram_private_send_non_200",
                            status=resp.status,
                            body=body[:200],
                            chat_id=chat_id,
                        )
        except Exception as exc:  # noqa: BLE001
            log.warning("telegram_private_send_failed", error=str(exc), chat_id=chat_id)

    _telegram_sender.set_sender(_tg_send_private)

    # ── Bootstrap: market discovery + pipeline startup ─────────────────────────
    from projects.polymarket.polyquantbot.core.bootstrap import run_bootstrap
    from projects.polymarket.polyquantbot.core.pipeline.live_paper_runner import LivePaperRunner
    from projects.polymarket.polyquantbot.core.pipeline.trading_loop import run_trading_loop

    runner: Optional["LivePaperRunner"] = None
    pipeline_task = None
    trading_loop_task = None
    try:
        log.info("pipeline_started")
        cfg, market_ids, market_meta = await run_bootstrap()

        # Validate condition_ids (market_ids) before proceeding
        condition_ids: list[str] = market_ids if market_ids else []
        if not condition_ids:
            log.warning("no_condition_ids_found")
        else:
            log.info("condition_ids_loaded", count=len(condition_ids))

        # ── Send STARTUP alert with real market count ──────────────────────────
        await tg.alert_startup(mode=mode, market_count=len(condition_ids))

        runner = LivePaperRunner.from_config(cfg=cfg, market_ids=condition_ids)
        await runner.start()

        # Sync discovered market IDs + metadata into config_manager
        config_manager.update_market_ids(condition_ids, market_meta)

        # Wire runner into command handler for live /status data
        if hasattr(cmd_handler, "set_runner"):
            cmd_handler.set_runner(runner)

        pipeline_task = asyncio.create_task(runner.run(), name="trading_pipeline")
        log.info(
            "polyquantbot_pipeline_started",
            market_count=len(condition_ids),
            market_ids=condition_ids[:5],
        )

        # ── Signal→execution trading loop (runs alongside WS pipeline) ────────
        trading_loop_task = asyncio.create_task(
            run_trading_loop(
                mode=mode,
                telegram_callback=_tg_send if tg.enabled else None,
                db=db,
                user_id="default",
                market_cache=market_cache,
                position_manager=position_manager,
                pnl_tracker=pnl_tracker,
                paper_engine=engine_container.paper_engine,
            ),
            name="trading_loop",
        )
        log.info("trading_loop_task_started", mode=mode)
    except Exception as exc:
        log.error(
            "pipeline_crash",
            error=str(exc),
            hint="Check market IDs, CLOB credentials, and Gamma API connectivity",
        )
        await tg.alert_error(str(exc), context="pipeline_startup")

    # ── Keep running until stop signal ────────────────────────────────────────
    await stop_event.wait()

    log.info("polyquantbot_shutdown_started")
    if trading_loop_task is not None and not trading_loop_task.done():
        trading_loop_task.cancel()
        try:
            await trading_loop_task
        except asyncio.CancelledError:
            pass
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
    await market_cache.stop()
    await tg.stop()
    await metrics_exporter.stop_logging_loop()
    try:
        await metrics_server.stop()
    except Exception as exc:
        log.warning("metrics_server_stop_error", error=str(exc))
    await db.close()
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
