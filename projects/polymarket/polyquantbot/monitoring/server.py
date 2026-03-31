"""Observability layer — HTTP API server.

Exposes two endpoints over a lightweight async aiohttp server:

    GET /health   → 200 {"status": "ok"}
    GET /metrics  → 200 <MetricsSnapshot JSON>

Design constraints:
    - Server failure MUST NOT affect the trading pipeline.
    - Server runs in its own asyncio.Task; the bot continues if the server
      raises an unhandled exception.
    - All responses are JSON with Content-Type: application/json.
    - Default port is 8765; override via ``port`` constructor arg or the
      ``METRICS_SERVER_PORT`` environment variable.

Usage::

    exporter = MetricsExporter(metrics_validator=..., risk_guard=..., fill_tracker=...)
    server   = MetricsServer(exporter=exporter, port=8765)
    await server.start()         # non-blocking; returns once site is up
    ...
    await server.stop()          # graceful shutdown
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Optional

import structlog
from aiohttp import web

from .metrics_exporter import MetricsExporter

log = structlog.get_logger()

_DEFAULT_PORT: int = 8765
_ENV_PORT_KEY: str = "METRICS_SERVER_PORT"


class MetricsServer:
    """Async HTTP server that exposes the live metrics snapshot.

    The server runs in a separate :class:`asyncio.Task` so it is completely
    isolated from the main bot event loop.  A crash inside the server handler
    is caught, logged, and returns a 500 response — it never propagates.

    Args:
        exporter: :class:`~metrics_exporter.MetricsExporter` instance to
                  pull snapshots from.
        host: Interface to bind on (default ``"0.0.0.0"``).
        port: TCP port to listen on.  Overridden by the
              ``METRICS_SERVER_PORT`` environment variable if set.
    """

    def __init__(
        self,
        exporter: MetricsExporter,
        host: str = "0.0.0.0",
        port: int = _DEFAULT_PORT,
    ) -> None:
        env_port = os.environ.get(_ENV_PORT_KEY)
        self._port: int = int(env_port) if env_port else port
        self._host = host
        self._exporter = exporter
        self._app: web.Application = self._build_app()
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._server_task: Optional[asyncio.Task] = None  # type: ignore[type-arg]

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the HTTP server.

        Non-blocking — returns once the TCP socket is bound and accepting
        connections.  Safe to call multiple times (idempotent after first
        successful start).
        """
        if self._runner is not None:
            log.warning("metrics_server_already_running", port=self._port)
            return
        try:
            self._runner = web.AppRunner(self._app)
            await self._runner.setup()
            self._site = web.TCPSite(self._runner, self._host, self._port)
            await self._site.start()
            log.info(
                "metrics_server_started",
                host=self._host,
                port=self._port,
            )
        except Exception as exc:  # noqa: BLE001
            log.error(
                "metrics_server_start_failed",
                host=self._host,
                port=self._port,
                error=str(exc),
            )
            # Ensure partial state is cleaned up so start() can be retried
            await self._cleanup_runner()

    async def stop(self) -> None:
        """Gracefully stop the HTTP server."""
        await self._cleanup_runner()
        log.info("metrics_server_stopped")

    # ── Route handlers ─────────────────────────────────────────────────────────

    async def _handle_health(self, request: web.Request) -> web.Response:
        """GET /health — returns {"status": "ok"}."""
        return web.Response(
            text=json.dumps({"status": "ok"}),
            content_type="application/json",
        )

    async def _handle_metrics(self, request: web.Request) -> web.Response:
        """GET /metrics — returns the current :class:`~schema.MetricsSnapshot`."""
        try:
            snap = self._exporter.snapshot()
            payload = snap.to_dict()
            return web.Response(
                text=json.dumps(payload),
                content_type="application/json",
            )
        except Exception as exc:  # noqa: BLE001
            log.error("metrics_server_handler_error", endpoint="/metrics", error=str(exc))
            error_payload = json.dumps({"error": "metrics_unavailable", "detail": str(exc)})
            return web.Response(
                status=500,
                text=error_payload,
                content_type="application/json",
            )

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _build_app(self) -> web.Application:
        """Assemble the aiohttp application with routes."""
        app = web.Application()
        app.router.add_get("/health", self._handle_health)
        app.router.add_get("/metrics", self._handle_metrics)
        return app

    async def _cleanup_runner(self) -> None:
        """Tear down the aiohttp runner and reset state."""
        if self._runner is not None:
            try:
                await self._runner.cleanup()
            except Exception as exc:  # noqa: BLE001
                log.warning("metrics_server_cleanup_error", error=str(exc))
            finally:
                self._runner = None
                self._site = None
