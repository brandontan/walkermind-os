"""Dashboard API server — minimal real-time monitoring & control interface.

Exposes a lightweight aiohttp HTTP + WebSocket server that powers the React
dashboard.  All control operations are routed through the existing
CommandHandler so behaviour is identical to Telegram commands.

Endpoints:

    GET  /api/status      → {"system_state": ..., "mode": ..., ...}
    GET  /api/portfolio   → {"balance": ..., "pnl_today": ..., ...}
    GET  /api/trades      → [{"market": ..., "side": ..., ...}, ...]
    POST /api/pause       → {"success": bool, "message": str}
    POST /api/resume      → {"success": bool, "message": str}
    POST /api/kill        → {"success": bool, "message": str}

    WS   /ws/dashboard    → streams JSON update payloads every ≤1 s

WebSocket payload::

    {
        "type": "update",
        "status": {...},
        "portfolio": {...},
        "trades": [...],
        "signals": [...]
    }

Design:
    - Server failure MUST NOT affect the trading pipeline.
    - Server runs in its own asyncio Task.
    - Only localhost connections are accepted (security default).
    - All control POSTs delegate to CommandHandler (no duplicate logic).
    - WebSocket uses auto-reconnect logic on the client side; the server
      simply broadcasts to all connected clients.
    - max_signals ring-buffer of 20 most-recent signal events.
    - update_interval is ≤1 s (default 1.0 s).
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from collections import deque
from typing import Any, Deque, Optional, Set

import structlog
from aiohttp import WSMsgType, web

log = structlog.get_logger()

_DEFAULT_PORT: int = 8766
_ENV_PORT_KEY: str = "DASHBOARD_SERVER_PORT"
_UPDATE_INTERVAL_S: float = 1.0
_MAX_SIGNAL_EVENTS: int = 20
_LOCALHOST: str = "127.0.0.1"


class DashboardServer:
    """Async HTTP + WebSocket server for the trading dashboard.

    Args:
        command_handler: Existing :class:`~telegram.command_handler.CommandHandler`
            instance — all control requests are routed through it.
        state_manager: :class:`~core.system_state.SystemStateManager` for
            real-time state reads.
        metrics_exporter: Optional :class:`~monitoring.metrics_exporter.MetricsExporter`
            for portfolio / metrics snapshots.
        fill_tracker: Optional fill tracker for open trades data.
        mode: Trading mode string ("PAPER" | "LIVE").
        host: Interface to bind on (default ``"127.0.0.1"``).
        port: TCP port to listen on.  Overridden by
            ``DASHBOARD_SERVER_PORT`` env var if set.
        update_interval_s: WebSocket broadcast interval in seconds.
    """

    def __init__(
        self,
        command_handler: Any,
        state_manager: Any,
        metrics_exporter: Optional[Any] = None,
        fill_tracker: Optional[Any] = None,
        mode: str = "PAPER",
        host: str = _LOCALHOST,
        port: int = _DEFAULT_PORT,
        update_interval_s: float = _UPDATE_INTERVAL_S,
    ) -> None:
        env_port = os.environ.get(_ENV_PORT_KEY)
        self._port: int = int(env_port) if env_port else port
        self._host = host
        self._command_handler = command_handler
        self._state_manager = state_manager
        self._metrics_exporter = metrics_exporter
        self._fill_tracker = fill_tracker
        self._mode = mode
        self._update_interval_s = update_interval_s

        self._ws_clients: Set[web.WebSocketResponse] = set()
        self._signal_buffer: Deque[dict] = deque(maxlen=_MAX_SIGNAL_EVENTS)

        self._app: web.Application = self._build_app()
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._broadcast_task: Optional[asyncio.Task] = None  # type: ignore[type-arg]

        log.info(
            "dashboard_server_initialized",
            host=host,
            port=self._port,
            mode=mode,
        )

    # ── Public lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the HTTP+WebSocket server (non-blocking)."""
        if self._runner is not None:
            log.warning("dashboard_server_already_running", port=self._port)
            return
        try:
            self._runner = web.AppRunner(self._app)
            await self._runner.setup()
            self._site = web.TCPSite(self._runner, self._host, self._port)
            await self._site.start()
            self._broadcast_task = asyncio.create_task(
                self._broadcast_loop(), name="dashboard_broadcast"
            )
            log.info(
                "dashboard_server_started",
                host=self._host,
                port=self._port,
            )
        except Exception as exc:  # noqa: BLE001
            log.error(
                "dashboard_server_start_failed",
                host=self._host,
                port=self._port,
                error=str(exc),
            )
            await self._cleanup()

    async def stop(self) -> None:
        """Gracefully stop the server and all WebSocket connections."""
        if self._broadcast_task and not self._broadcast_task.done():
            self._broadcast_task.cancel()
            try:
                await self._broadcast_task
            except asyncio.CancelledError:
                pass
        for ws in list(self._ws_clients):
            await ws.close()
        await self._cleanup()
        log.info("dashboard_server_stopped")

    def push_signal_event(self, event: dict) -> None:
        """Append a signal event to the live ring-buffer.

        Call this from the trading pipeline to surface real-time signal logs
        in the dashboard without polling.

        Args:
            event: Arbitrary dict describing the signal event.
        """
        timestamped = {**event, "ts": time.time()}
        self._signal_buffer.append(timestamped)

    # ── Route builder ───────────────────────────────────────────────────────────

    def _build_app(self) -> web.Application:
        app = web.Application()
        # REST endpoints
        app.router.add_get("/api/status", self._handle_status)
        app.router.add_get("/api/portfolio", self._handle_portfolio)
        app.router.add_get("/api/trades", self._handle_trades)
        app.router.add_post("/api/pause", self._handle_pause)
        app.router.add_post("/api/resume", self._handle_resume)
        app.router.add_post("/api/kill", self._handle_kill)
        # WebSocket
        app.router.add_get("/ws/dashboard", self._handle_ws)
        # CORS middleware for local dev
        app.middlewares.append(_cors_middleware)
        return app

    # ── REST handlers ───────────────────────────────────────────────────────────

    async def _handle_status(self, request: web.Request) -> web.Response:
        """GET /api/status."""
        try:
            payload = self._build_status()
            return _json_response(payload)
        except Exception as exc:  # noqa: BLE001
            log.error("dashboard_status_error", error=str(exc))
            return _json_response({"error": "status_unavailable"}, status=500)

    async def _handle_portfolio(self, request: web.Request) -> web.Response:
        """GET /api/portfolio."""
        try:
            payload = self._build_portfolio()
            return _json_response(payload)
        except Exception as exc:  # noqa: BLE001
            log.error("dashboard_portfolio_error", error=str(exc))
            return _json_response({"error": "portfolio_unavailable"}, status=500)

    async def _handle_trades(self, request: web.Request) -> web.Response:
        """GET /api/trades."""
        try:
            payload = self._build_trades()
            return _json_response({"trades": payload})
        except Exception as exc:  # noqa: BLE001
            log.error("dashboard_trades_error", error=str(exc))
            return _json_response({"trades": []})

    async def _handle_pause(self, request: web.Request) -> web.Response:
        """POST /api/pause — delegate to CommandHandler."""
        return await self._dispatch_control("pause")

    async def _handle_resume(self, request: web.Request) -> web.Response:
        """POST /api/resume — delegate to CommandHandler."""
        return await self._dispatch_control("resume")

    async def _handle_kill(self, request: web.Request) -> web.Response:
        """POST /api/kill — delegate to CommandHandler."""
        return await self._dispatch_control("kill")

    # ── WebSocket handler ───────────────────────────────────────────────────────

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        """GET /ws/dashboard — persistent WebSocket connection."""
        ws = web.WebSocketResponse(heartbeat=15.0)
        await ws.prepare(request)
        self._ws_clients.add(ws)
        log.info("dashboard_ws_client_connected", total=len(self._ws_clients))

        try:
            # Send initial snapshot immediately on connect
            snapshot = self._build_full_snapshot()
            await ws.send_str(json.dumps(snapshot))

            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    # Client messages are ignored; dashboard is read-only over WS
                    pass
                elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    break
        except Exception as exc:  # noqa: BLE001
            log.warning("dashboard_ws_error", error=str(exc))
        finally:
            self._ws_clients.discard(ws)
            log.info("dashboard_ws_client_disconnected", total=len(self._ws_clients))

        return ws

    # ── Broadcast loop ──────────────────────────────────────────────────────────

    async def _broadcast_loop(self) -> None:
        """Broadcast a full snapshot to all connected WS clients every interval."""
        while True:
            await asyncio.sleep(self._update_interval_s)
            if not self._ws_clients:
                continue
            try:
                snapshot = self._build_full_snapshot()
                payload = json.dumps(snapshot)
                dead: list[web.WebSocketResponse] = []
                for ws in list(self._ws_clients):
                    try:
                        if not ws.closed:
                            await ws.send_str(payload)
                    except Exception:  # noqa: BLE001
                        dead.append(ws)
                for ws in dead:
                    self._ws_clients.discard(ws)
            except Exception as exc:  # noqa: BLE001
                log.warning("dashboard_broadcast_error", error=str(exc))

    # ── Data builders ───────────────────────────────────────────────────────────

    def _build_status(self) -> dict:
        """Build /api/status payload."""
        sm = self._state_manager
        state_value = "RUNNING"
        reason = ""
        state_changed_at: Optional[float] = None
        if sm is not None:
            try:
                snap = sm.snapshot()
                state_value = snap.get("state", "RUNNING")
                reason = snap.get("reason", "")
                state_changed_at = snap.get("state_changed_at")
            except Exception:  # noqa: BLE001
                pass
        return {
            "system_state": state_value,
            "mode": self._mode,
            "reason": reason,
            "state_changed_at": state_changed_at,
            "ts": time.time(),
        }

    def _build_portfolio(self) -> dict:
        """Build /api/portfolio payload from MetricsExporter."""
        portfolio: dict = {
            "balance": None,
            "pnl_today": None,
            "pnl_all_time": None,
            "exposure": None,
            "active_trades": None,
        }
        me = self._metrics_exporter
        if me is not None:
            try:
                snap = me.snapshot()
                d = snap.to_dict()
                # balance and pnl fields are not tracked by MetricsExporter;
                # they remain None until a dedicated PnL tracker is wired in.
                portfolio["balance"] = None
                portfolio["pnl_today"] = None
                portfolio["pnl_all_time"] = None
                # drawdown_pct is surfaced as a separate informational metric
                portfolio["drawdown_pct"] = d.get("drawdown_pct")
                # fill_rate represents the fraction of orders filled (0–1)
                portfolio["fill_rate"] = d.get("fill_rate")
                portfolio["active_trades"] = self._count_active_trades()
            except Exception as exc:  # noqa: BLE001
                log.warning("dashboard_portfolio_build_error", error=str(exc))
        else:
            portfolio["active_trades"] = self._count_active_trades()
        return portfolio

    def _build_trades(self) -> list:
        """Build /api/trades list from FillTracker."""
        ft = self._fill_tracker
        if ft is None:
            return []
        try:
            records = getattr(ft, "_records", {})
            trades = []
            for order_id, record in list(records.items()):
                trades.append({
                    "order_id": str(order_id),
                    "market": getattr(record, "market_id", None),
                    "side": getattr(record, "side", None),
                    "price": getattr(record, "fill_price", None),
                    "size": getattr(record, "fill_size", None),
                    "pnl": getattr(record, "pnl", None),
                    "ts": getattr(record, "fill_ts", None),
                })
            return trades[:50]  # cap at 50
        except Exception as exc:  # noqa: BLE001
            log.warning("dashboard_trades_build_error", error=str(exc))
            return []

    def _count_active_trades(self) -> int:
        ft = self._fill_tracker
        if ft is None:
            return 0
        try:
            return len(getattr(ft, "_records", {}))
        except Exception:  # noqa: BLE001
            return 0

    def _build_full_snapshot(self) -> dict:
        """Build the full WebSocket update payload."""
        return {
            "type": "update",
            "status": self._build_status(),
            "portfolio": self._build_portfolio(),
            "trades": self._build_trades(),
            "signals": list(self._signal_buffer),
        }

    # ── Control dispatch ────────────────────────────────────────────────────────

    async def _dispatch_control(self, command: str) -> web.Response:
        """Route pause/resume/kill to the CommandHandler."""
        ch = self._command_handler
        if ch is None:
            return _json_response(
                {"success": False, "message": "command_handler_unavailable"},
                status=503,
            )
        try:
            result = await ch.handle(
                command=command,
                correlation_id=f"dashboard_{command}_{int(time.time())}",
            )
            return _json_response({
                "success": result.success,
                "message": result.message,
                "payload": result.payload,
            })
        except Exception as exc:  # noqa: BLE001
            log.error("dashboard_control_error", command=command, error=str(exc))
            return _json_response(
                {"success": False, "message": "internal_error"}, status=500
            )

    # ── Cleanup ─────────────────────────────────────────────────────────────────

    async def _cleanup(self) -> None:
        if self._runner is not None:
            try:
                await self._runner.cleanup()
            except Exception as exc:  # noqa: BLE001
                log.warning("dashboard_cleanup_error", error=str(exc))
            finally:
                self._runner = None
                self._site = None


# ── Helpers ─────────────────────────────────────────────────────────────────────


def _json_response(data: dict, status: int = 200) -> web.Response:
    return web.Response(
        text=json.dumps(data, default=str),
        content_type="application/json",
        status=status,
    )


@web.middleware
async def _cors_middleware(request: web.Request, handler) -> web.Response:  # type: ignore[type-arg]
    """Add CORS headers so the local dev frontend can reach the API."""
    if request.method == "OPTIONS":
        return web.Response(
            headers={
                "Access-Control-Allow-Origin": "http://localhost:3000",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            }
        )
    response = await handler(request)
    response.headers["Access-Control-Allow-Origin"] = "http://localhost:3000"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response
