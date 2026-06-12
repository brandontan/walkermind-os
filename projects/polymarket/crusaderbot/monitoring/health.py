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
import json
import logging
import re
from typing import Awaitable, Callable
from urllib.parse import urlparse

import httpx

from ..config import get_settings
from ..database import last_ping_error as db_last_ping_error
from ..database import ping as db_ping

logger = logging.getLogger(__name__)

CHECK_TIMEOUT_SECONDS: float = 5.0

# Strip the path (and any query/fragment) from anything that looks like a URL
# in a string. Alchemy embeds the API key in the URL path
# (``https://polygon-mainnet.g.alchemy.com/v2/<API_KEY>``), so any HTTP
# client exception text we log MUST have the path component removed before
# it reaches Fly's log aggregation.
_URL_RE = re.compile(r"(https?://)([^/\s'\"<>]+)([/?#]\S*)?")


def _scrub_url(text: str) -> str:
    return _URL_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}/<redacted>", text)


async def _with_timeout(
    name: str,
    coro_factory: Callable[[], Awaitable[bool]],
    *,
    reason_provider: Callable[[], str | None] | None = None,
    critical: bool = True,
) -> str:
    """Run a check coroutine, return ``'ok'`` or ``'error: <reason>'``.

    Catches every exception — health endpoint must never raise.

    The returned reason string is exposed by the unauthenticated ``/health``
    endpoint, so it MUST NOT contain raw exception messages: ``httpx``
    request errors, for instance, embed the full request URL and Alchemy
    encodes the API key in that URL path. Only the exception class name is
    surfaced publicly; full details (including ``str(exc)``) go to internal
    logs.

    ``reason_provider`` is an optional zero-arg callable consulted only on
    the ``ok=False`` branch — when present and non-empty, its return value
    (an exception class name) is appended to the unhealthy string in
    parentheses. This lets the database check surface the asyncpg
    exception class to operators without making the inner ping coroutine
    leak structured data through the bool contract.

    ``critical`` controls the log severity of a probe *exception*: only the
    database check drives ``status='down'`` / ``ready=False`` and is logged at
    ERROR (a Sentry event). The non-blocking probes (telegram / alchemy_*)
    merely degrade readiness, so a transient network blip is logged at WARNING
    — keeping it out of Sentry's error stream (default ``event_level=ERROR``)
    instead of paging on every flaky Telegram/RPC poll with zero user impact.
    """
    try:
        ok = await asyncio.wait_for(coro_factory(), timeout=CHECK_TIMEOUT_SECONDS)
        if ok:
            return "ok"
        reason = reason_provider() if reason_provider is not None else None
        if reason:
            return f"error: {name} reported unhealthy ({reason})"
        return f"error: {name} reported unhealthy"
    except asyncio.TimeoutError:
        return f"error: {name} timeout after {CHECK_TIMEOUT_SECONDS:.0f}s"
    except Exception as exc:  # noqa: BLE001 — surfaced as sanitised health string
        # Both ``str(exc)`` and the formatted traceback can embed the full
        # request URL on httpx errors (Alchemy carries the API key in the
        # URL path). Scrub URLs and skip ``exc_info`` so the application
        # log stream — which fans out to Fly's log aggregation — never
        # sees the secret. The exception class name + scrubbed message is
        # enough for diagnosis given the small number of check entry
        # points. Severity follows ``critical`` so only a real readiness
        # blocker (the DB) pages Sentry.
        log = logger.error if critical else logger.warning
        log(
            "health check failed: name=%s type=%s msg=%s",
            name, type(exc).__name__, _scrub_url(str(exc)),
        )
        return f"error: {type(exc).__name__}"


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
    """Full WebSocket handshake + JSON-RPC probe of the Alchemy WS endpoint.

    Opens a real WebSocket connection (TLS + HTTP Upgrade handshake) and
    issues a single ``eth_blockNumber`` call. This confirms the endpoint is
    not merely TCP-reachable but actually serving the JSON-RPC protocol over
    WS, so a broken upstream (failed handshake, auth rejection, protocol
    error) now fails the check instead of passing on raw socket reachability.
    Wrapped by the caller's 3s timeout.
    """
    settings = get_settings()
    url = getattr(settings, "ALCHEMY_POLYGON_WS_URL", None)
    if not url:
        raise RuntimeError("ALCHEMY_POLYGON_WS_URL not set")
    parsed = urlparse(url)
    if parsed.scheme not in ("ws", "wss"):
        raise RuntimeError(f"invalid ws scheme: {parsed.scheme!r}")
    # Soft import keeps test environments without ``websockets`` functional;
    # production lists it as a hard dependency in pyproject.toml.
    try:
        import websockets
    except ImportError as exc:  # pragma: no cover — only on missing dep
        raise RuntimeError("websockets package not installed") from exc

    payload = json.dumps(
        {"jsonrpc": "2.0", "method": "eth_blockNumber", "id": 1, "params": []}
    )
    async with websockets.connect(url, close_timeout=1, ping_interval=None) as ws:
        await ws.send(payload)
        raw = await ws.recv()
    body = json.loads(raw)
    if "error" in body:
        raise RuntimeError(f"ws rpc error: {body['error']}")
    return "result" in body


async def run_health_checks() -> dict:
    """Run all dependency checks in parallel and aggregate the verdict.

    Returns a dict matching the documented ``GET /health`` response shape.
    """
    # Only the database failure drives status='down'/ready=False -> ERROR
    # (Sentry event). The other probes only degrade readiness, so their
    # transient failures log at WARNING and stay out of the error stream.
    db_task = asyncio.create_task(_with_timeout(
        "database", check_database, reason_provider=db_last_ping_error,
        critical=True,
    ))
    tg_task = asyncio.create_task(_with_timeout(
        "telegram", check_telegram, critical=False,
    ))
    rpc_task = asyncio.create_task(_with_timeout(
        "alchemy_rpc", check_alchemy_rpc, critical=False,
    ))
    ws_task = asyncio.create_task(_with_timeout(
        "alchemy_ws", check_alchemy_ws, critical=False,
    ))

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
