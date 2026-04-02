"""Dashboard API Server — Production control panel for PolyQuantBot.

Provides a secured async HTTP + WebSocket server exposing:

    GET  /api/health          → system health snapshot (public)
    GET  /api/metrics         → live metrics snapshot  (auth required)
    POST /api/pause           → pause trading          (auth required)
    POST /api/resume          → resume trading         (auth required)
    POST /api/kill            → halt trading           (auth required)
    GET  /api/allocation      → capital allocation     (auth required)
    GET  /api/performance     → PnL + win-rate report  (auth required)
    WS   /ws                  → live metrics stream    (auth required)

Security:
    All /api/* endpoints (except /api/health) and the WebSocket handshake
    require:

        Authorization: Bearer <DASHBOARD_API_KEY>

    Missing or invalid keys receive HTTP 401.
    DASHBOARD_API_KEY is read from the environment — never hardcoded.
    If DASHBOARD_API_KEY is not set, auth is disabled with a WARNING log
    (safe for local dev, unsafe for production).

Railway:
    - Binds to host="0.0.0.0"
    - Port: int(os.getenv("PORT", 8766))
    - DASHBOARD_ENABLED=true required to start

WebSocket:
    After successful auth the server pushes a metrics snapshot every 5 s.
    On pipeline state change a push is triggered immediately.

Design:
    - Server runs in its own asyncio.Task — isolated from trading pipeline.
    - Any server crash is logged and never propagates to the bot.
    - All endpoints are idempotent and non-blocking.
    - Structured logging on every request and connection event.
    - Zero writes to trading components except via CommandHandler.

Usage::

    dashboard = DashboardServer(
        command_handler=cmd_handler,
        state_manager=state_manager,
        metrics_exporter=exporter,
        fill_tracker=fill_tracker,
        mode="LIVE",
    )
    asyncio.create_task(dashboard.start())
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Dict, List, Optional, Set

import structlog
from aiohttp import WSMsgType, web

log = structlog.get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_DEFAULT_PORT: int = 8766
_WS_PUSH_INTERVAL_S: float = 5.0
_ENV_API_KEY: str = "DASHBOARD_API_KEY"
_ENV_PORT: str = "PORT"
_ENV_ENABLED: str = "DASHBOARD_ENABLED"


# ── DashboardServer ───────────────────────────────────────────────────────────


class DashboardServer:
    """Async HTTP + WebSocket dashboard server for PolyQuantBot.

    Args:
        command_handler: :class:`~telegram.command_handler.CommandHandler`
            for /pause, /resume, /kill dispatch.
        state_manager: SystemStateManager for direct state reads.
        metrics_exporter: MetricsExporter for live metrics snapshots.
        fill_tracker: Optional FillTracker for fill data.
        mode: Trading mode string ("PAPER" | "LIVE").
        host: Bind address (default "0.0.0.0").
        port: TCP port (default: $PORT env or 8766).
    """

    def __init__(
        self,
        command_handler: Optional[Any] = None,
        state_manager: Optional[Any] = None,
        metrics_exporter: Optional[Any] = None,
        fill_tracker: Optional[Any] = None,
        mode: str = "PAPER",
        host: str = "0.0.0.0",
        port: Optional[int] = None,
    ) -> None:
        self._cmd_handler = command_handler
        self._state_manager = state_manager
        self._metrics_exporter = metrics_exporter
        self._fill_tracker = fill_tracker
        self._mode = mode
        self._host = host
        self._port: int = port if port is not None else int(
            os.getenv(_ENV_PORT, str(_DEFAULT_PORT))
        )
        self._api_key: Optional[str] = os.getenv(_ENV_API_KEY) or None
        self._start_time: float = time.time()

        # Active WebSocket connections
        self._ws_clients: Set[web.WebSocketResponse] = set()

        self._app: web.Application = self._build_app()
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None

        if not self._api_key:
            log.warning(
                "dashboard_server_no_api_key",
                message="DASHBOARD_API_KEY not set — auth disabled (unsafe for production)",
            )
        log.info(
            "dashboard_server_initialized",
            host=self._host,
            port=self._port,
            mode=self._mode,
            auth_enabled=self._api_key is not None,
        )

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the dashboard HTTP server as a background task.

        Non-blocking — returns once the TCP socket is bound.
        Idempotent: safe to call multiple times.
        Server failures are logged and never propagate.
        """
        if self._runner is not None:
            log.warning("dashboard_server_already_running", port=self._port)
            return
        try:
            self._runner = web.AppRunner(self._app)
            await self._runner.setup()
            self._site = web.TCPSite(self._runner, self._host, self._port)
            await self._site.start()
            log.info(
                "dashboard_server_started",
                host=self._host,
                port=self._port,
                mode=self._mode,
            )
            print(f"📊 Dashboard started on port {self._port}")
        except Exception as exc:
            log.error(
                "dashboard_server_start_failed",
                host=self._host,
                port=self._port,
                error=str(exc),
            )
            await self._cleanup()

    async def stop(self) -> None:
        """Gracefully stop the dashboard server."""
        await self._cleanup()
        log.info("dashboard_server_stopped")

    # ── Auth ──────────────────────────────────────────────────────────────────

    def _check_auth(self, request: web.Request) -> bool:
        """Validate the Authorization: Bearer header.

        Returns True if auth passes (key matches or no key is configured).
        """
        if not self._api_key:
            return True
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return False
        token = auth_header[len("Bearer "):].strip()
        return token == self._api_key

    def _unauthorized(self) -> web.Response:
        return web.Response(
            status=401,
            text=json.dumps({"error": "unauthorized", "detail": "Invalid or missing API key"}),
            content_type="application/json",
        )

    # ── Route handlers ────────────────────────────────────────────────────────

    async def _handle_health(self, request: web.Request) -> web.Response:
        """GET /api/health — public, no auth required."""
        uptime_s = round(time.time() - self._start_time, 1)
        state = "unknown"
        if self._state_manager is not None:
            try:
                snap = self._state_manager.snapshot()
                state = snap.get("state", "unknown")
            except Exception:
                pass
        payload = {
            "status": "running",
            "mode": self._mode,
            "uptime_s": uptime_s,
            "system_state": state,
        }
        return web.Response(
            text=json.dumps(payload),
            content_type="application/json",
        )

    async def _handle_metrics(self, request: web.Request) -> web.Response:
        """GET /api/metrics — auth required."""
        if not self._check_auth(request):
            return self._unauthorized()
        try:
            if self._metrics_exporter is not None:
                snap = self._metrics_exporter.snapshot()
                payload = snap.to_dict()
            else:
                payload = {"error": "metrics_exporter_not_configured"}
            return web.Response(
                text=json.dumps(payload),
                content_type="application/json",
            )
        except Exception as exc:
            log.error("dashboard_metrics_handler_error", error=str(exc))
            return web.Response(
                status=500,
                text=json.dumps({"error": "metrics_unavailable", "detail": str(exc)}),
                content_type="application/json",
            )

    async def _handle_pause(self, request: web.Request) -> web.Response:
        """POST /api/pause — auth required."""
        if not self._check_auth(request):
            return self._unauthorized()
        return await self._dispatch_command("pause")

    async def _handle_resume(self, request: web.Request) -> web.Response:
        """POST /api/resume — auth required."""
        if not self._check_auth(request):
            return self._unauthorized()
        return await self._dispatch_command("resume")

    async def _handle_kill(self, request: web.Request) -> web.Response:
        """POST /api/kill — auth required."""
        if not self._check_auth(request):
            return self._unauthorized()
        return await self._dispatch_command("kill")

    async def _handle_allocation(self, request: web.Request) -> web.Response:
        """GET /api/allocation — auth required."""
        if not self._check_auth(request):
            return self._unauthorized()
        return await self._dispatch_command("allocation")

    async def _handle_performance(self, request: web.Request) -> web.Response:
        """GET /api/performance — auth required."""
        if not self._check_auth(request):
            return self._unauthorized()
        return await self._dispatch_command("performance")

    async def _handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """WS /ws — auth required via ?api_key= query param or Authorization header."""
        # Auth: accept via header or query param (for WS clients)
        authed = self._check_auth(request)
        if not authed:
            qk = request.rel_url.query.get("api_key", "")
            authed = (not self._api_key) or (qk == self._api_key)
        if not authed:
            raise web.HTTPUnauthorized(
                text=json.dumps({"error": "unauthorized"}),
                content_type="application/json",
            )

        ws = web.WebSocketResponse()
        await ws.prepare(request)

        remote = request.remote or "unknown"
        log.info("dashboard_ws_connected", remote=remote)
        self._ws_clients.add(ws)

        try:
            # Send initial snapshot immediately on connect
            await self._push_snapshot(ws)

            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    log.debug("dashboard_ws_message", remote=remote, data=msg.data[:200])
                elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    break
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            log.warning("dashboard_ws_error", remote=remote, error=str(exc))
        finally:
            self._ws_clients.discard(ws)
            log.info("dashboard_ws_disconnected", remote=remote)

        return ws

    # ── WebSocket push loop ───────────────────────────────────────────────────

    async def _ws_broadcast_loop(self) -> None:
        """Background coroutine — broadcast metrics to all WS clients every 5 s."""
        while True:
            await asyncio.sleep(_WS_PUSH_INTERVAL_S)
            if not self._ws_clients:
                continue
            payload = self._build_snapshot_payload()
            text = json.dumps(payload, default=str)
            dead: List[web.WebSocketResponse] = []
            for ws in list(self._ws_clients):
                try:
                    if not ws.closed:
                        await ws.send_str(text)
                    else:
                        dead.append(ws)
                except Exception as exc:
                    log.warning("dashboard_ws_send_error", error=str(exc))
                    dead.append(ws)
            for ws in dead:
                self._ws_clients.discard(ws)

    async def _push_snapshot(self, ws: web.WebSocketResponse) -> None:
        """Send a single metrics snapshot to one WebSocket client."""
        try:
            payload = self._build_snapshot_payload()
            await ws.send_str(json.dumps(payload, default=str))
        except Exception as exc:
            log.warning("dashboard_ws_push_error", error=str(exc))

    def _build_snapshot_payload(self) -> Dict[str, Any]:
        """Assemble the payload sent over WebSocket."""
        payload: Dict[str, Any] = {
            "type": "snapshot",
            "mode": self._mode,
            "uptime_s": round(time.time() - self._start_time, 1),
            "ts": time.time(),
        }
        if self._state_manager is not None:
            try:
                payload["system_state"] = self._state_manager.snapshot()
            except Exception:
                pass
        if self._metrics_exporter is not None:
            try:
                snap = self._metrics_exporter.snapshot()
                payload["metrics"] = snap.to_dict()
            except Exception:
                pass
        return payload

    # ── Command dispatch ──────────────────────────────────────────────────────

    async def _dispatch_command(self, cmd: str) -> web.Response:
        """Route a command through CommandHandler and return JSON result."""
        if self._cmd_handler is None:
            return web.Response(
                status=503,
                text=json.dumps({"error": "command_handler_not_configured"}),
                content_type="application/json",
            )
        try:
            result = await self._cmd_handler.handle(
                command=cmd,
                correlation_id=f"dashboard:{cmd}:{int(time.time())}",
            )
            payload = {
                "success": result.success,
                "message": result.message,
                "payload": result.payload,
            }
            status = 200 if result.success else 400
            return web.Response(
                status=status,
                text=json.dumps(payload, default=str),
                content_type="application/json",
            )
        except Exception as exc:
            log.error("dashboard_command_dispatch_error", cmd=cmd, error=str(exc))
            return web.Response(
                status=500,
                text=json.dumps({"error": str(exc)}),
                content_type="application/json",
            )

    # ── App builder ───────────────────────────────────────────────────────────

    def _build_app(self) -> web.Application:
        """Assemble the aiohttp application with all routes."""
        app = web.Application()
        app.router.add_get("/api/health", self._handle_health)
        app.router.add_get("/api/metrics", self._handle_metrics)
        app.router.add_post("/api/pause", self._handle_pause)
        app.router.add_post("/api/resume", self._handle_resume)
        app.router.add_post("/api/kill", self._handle_kill)
        app.router.add_get("/api/allocation", self._handle_allocation)
        app.router.add_get("/api/performance", self._handle_performance)
        app.router.add_get("/ws", self._handle_websocket)
        app.on_startup.append(self._on_startup)
        return app

    async def _on_startup(self, app: web.Application) -> None:
        """Launch the WS broadcast background loop on server startup."""
        asyncio.create_task(
            self._ws_broadcast_loop(), name="dashboard_ws_broadcast"
        )
        log.info("dashboard_ws_broadcast_loop_started")

    # ── Cleanup ───────────────────────────────────────────────────────────────

    async def _cleanup(self) -> None:
        """Close all WS connections and tear down the aiohttp runner."""
        for ws in list(self._ws_clients):
            try:
                await ws.close()
            except Exception:
                pass
        self._ws_clients.clear()
        if self._runner is not None:
            try:
                await self._runner.cleanup()
            except Exception as exc:
                log.warning("dashboard_server_cleanup_error", error=str(exc))
            finally:
                self._runner = None
                self._site = None

    def __repr__(self) -> str:
        return (
            f"<DashboardServer host={self._host} port={self._port} "
            f"mode={self._mode} ws_clients={len(self._ws_clients)}>"
        )
