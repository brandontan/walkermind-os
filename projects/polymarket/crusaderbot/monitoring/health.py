"""Dependency liveness checks for /health.

Every check is wrapped with a hard 3-second timeout so the health endpoint
never blocks. Failures are reported as ``error: <reason>`` strings — no
exception is allowed to escape and the endpoint always returns within the
configured timeout budget.

Aggregated status rules:
- All checks pass               -> status="ok",       ready=True
- Database fails                -> status="down",     ready=False
- Any non-DB check fails        -> status="degraded", ready=True

Redis is intentionally NOT checked here (cache layer falls back to in-memory
when REDIS_URL is unset; not part of the operator-critical dependency set).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable
from urllib.parse import urlparse

import httpx

from ..config import get_settings
from ..database import ping as db_ping

logger = logging.getLogger(__name__)

CHECK_TIMEOUT_SECONDS: float = 3.0


async def _with_timeout(
    name: str, coro_factory: Callable[[], Awaitable[bool]],
) -> str:
    """Run a check coroutine, return ``'ok'`` or ``'error: <reason>'``.

    Catches every exception — health endpoint must never raise.
    """
    try:
        ok = await asyncio.wait_for(coro_factory(), timeout=CHECK_TIMEOUT_SECONDS)
        return "ok" if ok else f"error: {name} reported unhealthy"
    except asyncio.TimeoutError:
        return f"error: {name} timeout after {CHECK_TIMEOUT_SECONDS:.0f}s"
    except Exception as exc:  # noqa: BLE001 — surfaced as health string
        return f"error: {type(exc).__name__}: {exc}"


async def check_database() -> bool:
    """Ping PostgreSQL via the shared asyncpg pool."""
    return await db_ping()


async def check_telegram() -> bool:
    """Verify the Telegram bot token via ``getMe`` on the shared bot instance.

    Uses the PTB ``Bot`` registered by ``main.py`` — no new bot is spawned.
    """
    # Lazy import to avoid a circular dep at module load.
    from .. import notifications

    bot = notifications.get_bot()
    me = await bot.get_me()
    return bool(getattr(me, "id", None))


async def check_alchemy_rpc() -> bool:
    """POST ``eth_blockNumber`` to the configured Polygon RPC endpoint."""
    settings = get_settings()
    url = (
        getattr(settings, "ALCHEMY_POLYGON_RPC_URL", None)
        or settings.POLYGON_RPC_URL
    )
    if not url:
        raise RuntimeError("ALCHEMY_POLYGON_RPC_URL/POLYGON_RPC_URL not set")
    payload = {"jsonrpc": "2.0", "method": "eth_blockNumber", "id": 1, "params": []}
    async with httpx.AsyncClient(timeout=CHECK_TIMEOUT_SECONDS) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        body = resp.json()
    if "error" in body:
        raise RuntimeError(f"rpc error: {body['error']}")
    return "result" in body


async def check_alchemy_ws() -> bool:
    """TCP-level reachability check for the Alchemy WebSocket endpoint.

    A full WS handshake would require an extra dependency; the TCP probe
    is sufficient to surface DNS/SSL/firewall outages, which is what the
    operator alert needs to catch.
    """
    settings = get_settings()
    url = getattr(settings, "ALCHEMY_POLYGON_WS_URL", None)
    if not url:
        raise RuntimeError("ALCHEMY_POLYGON_WS_URL not set")
    parsed = urlparse(url)
    if parsed.scheme not in ("ws", "wss"):
        raise RuntimeError(f"invalid ws scheme: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise RuntimeError("ws host missing")
    port = parsed.port or (443 if parsed.scheme == "wss" else 80)
    reader, writer = await asyncio.open_connection(host, port, ssl=parsed.scheme == "wss")
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:  # noqa: BLE001 — close races are benign here
        pass
    return True


async def run_health_checks() -> dict:
    """Run all dependency checks in parallel and aggregate the verdict.

    Returns a dict matching the documented ``GET /health`` response shape.
    """
    db_task = asyncio.create_task(_with_timeout("database", check_database))
    tg_task = asyncio.create_task(_with_timeout("telegram", check_telegram))
    rpc_task = asyncio.create_task(_with_timeout("alchemy_rpc", check_alchemy_rpc))
    ws_task = asyncio.create_task(_with_timeout("alchemy_ws", check_alchemy_ws))

    db_res, tg_res, rpc_res, ws_res = await asyncio.gather(
        db_task, tg_task, rpc_task, ws_task
    )

    checks = {
        "database": db_res,
        "telegram": tg_res,
        "alchemy_rpc": rpc_res,
        "alchemy_ws": ws_res,
    }

    db_ok = db_res == "ok"
    others_ok = all(v == "ok" for k, v in checks.items() if k != "database")

    if not db_ok:
        status = "down"
        ready = False
    elif not others_ok:
        status = "degraded"
        ready = True
    else:
        status = "ok"
        ready = True

    return {
        "status": status,
        "service": "CrusaderBot",
        "checks": checks,
        "ready": ready,
    }
