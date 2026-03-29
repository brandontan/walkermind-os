"""HTTP health server on :8080 for liveness and status checks."""
from __future__ import annotations

import time
from typing import Any

import structlog
from aiohttp import web

from .state_manager import StateManager

log = structlog.get_logger()

_start_time = time.time()


def make_health_app(
    state: StateManager,
    pipeline_state: dict[str, Any],
) -> web.Application:
    """Create aiohttp application with /health endpoint."""
    app = web.Application()

    async def health_handler(request: web.Request) -> web.Response:
        """Return system health status as JSON."""
        try:
            open_positions = await state.get_open_positions()
            realized_pnl = await state.get_balance()
            initial_balance = pipeline_state.get("initial_balance", 1000.0)
            balance = initial_balance + realized_pnl

            payload = {
                "status": "ok",
                "uptime_seconds": round(time.time() - _start_time, 1),
                "pipeline_state": pipeline_state.get("state", "running"),
                "cycle": pipeline_state.get("cycle", 0),
                "balance": round(balance, 4),
                "open_positions": len(open_positions),
            }
            return web.json_response(payload)
        except Exception as exc:
            log.error("health_check_error", error=str(exc))
            return web.json_response(
                {"status": "error", "error": str(exc)}, status=500
            )

    app.router.add_get("/health", health_handler)
    return app


async def start_health_server(
    state: StateManager,
    pipeline_state: dict[str, Any],
    port: int = 8080,
) -> web.AppRunner:
    """Start the health server and return the runner for cleanup."""
    app = make_health_app(state, pipeline_state)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info("health_server_started", port=port)
    return runner
