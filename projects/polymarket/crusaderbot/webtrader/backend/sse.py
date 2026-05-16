"""PostgreSQL LISTEN/NOTIFY fan-out for the WebTrader SSE stream.

Uses a DEDICATED asyncpg connection (not the pool) because:
  - LISTEN puts a connection into a persistent notification mode.
  - Pool connections get recycled and UNLISTEN'd on return.
  - Supabase Supavisor pooler (port 6543) silently drops pg_notify.
    This module normalises the URL to the direct Postgres port (5432).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import AsyncIterator
from urllib.parse import urlparse, urlunparse

import asyncpg

log = logging.getLogger(__name__)

# pg_notify channels → SSE event type
CHANNEL_MAP: dict[str, str] = {
    "cb_orders":          "orders",
    "cb_fills":           "fills",
    "cb_positions":       "positions",
    "cb_user_settings":   "settings",
    "cb_system_settings": "system",
    "cb_portfolio":       "portfolio",
    "cb_alerts":          "alerts",
}

# Broadcast channels — events fan out to all connected users
_BROADCAST_CHANNELS = {"cb_system_settings", "cb_alerts"}

# per-user queues: {user_id (str UUID): [Queue, ...]}
_user_queues: dict[str, list[asyncio.Queue]] = {}
_listener_conn: asyncpg.Connection | None = None
_listener_task: asyncio.Task | None = None
_lock = asyncio.Lock()


def _normalize_dsn_for_listen(dsn: str) -> str:
    """Switch pooler URL to direct connection so LISTEN/NOTIFY works.

    Supabase Supavisor (port 6543, host *.pooler.supabase.com) silently
    drops LISTEN. Swap to the direct Postgres endpoint (port 5432).
    """
    parsed = urlparse(dsn)
    host = parsed.hostname or ""

    if "pooler.supabase.com" in host:
        # Extract project ref from pooler hostname, e.g. "aws-0-us-east-1.pooler.supabase.com"
        # The direct host is "db.<project_ref>.supabase.co"
        # We derive the project ref from the path/user (username is the project ref on pooler)
        username = parsed.username or ""
        # Supabase pooler user format: postgres.<project_ref>
        m = re.match(r"postgres\.([a-z0-9]+)", username)
        project_ref = m.group(1) if m else username
        direct_host = f"db.{project_ref}.supabase.co"
        parsed = parsed._replace(
            netloc=f"{parsed.username}:{parsed.password}@{direct_host}:5432"
        )
        log.info("SSE: normalised pooler URL to direct host %s:5432", direct_host)
    elif parsed.port == 6543:
        parsed = parsed._replace(
            netloc=parsed.netloc.replace(":6543", ":5432")
        )
        log.info("SSE: normalised port 6543 → 5432 for LISTEN connection")

    return urlunparse(parsed)


async def _make_listener_conn(dsn: str) -> asyncpg.Connection:
    direct_dsn = _normalize_dsn_for_listen(dsn)
    return await asyncpg.connect(
        dsn=direct_dsn,
        statement_cache_size=0,
        server_settings={"application_name": "crusaderbot-sse"},
    )


def _put_event(user_id: str | None, channel: str, data: dict) -> None:
    event_type = CHANNEL_MAP.get(channel, channel)
    event = {"type": event_type, "payload": data}

    if channel in _BROADCAST_CHANNELS:
        for queues in _user_queues.values():
            for q in queues:
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    pass
    elif user_id:
        for q in _user_queues.get(user_id, []):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass


def _make_notification_handler(pool: asyncpg.Pool):
    async def _resolve_fill_user(order_id: str, channel: str, data: dict) -> None:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT user_id FROM orders WHERE id = $1::uuid", order_id
                )
            if row:
                _put_event(str(row["user_id"]), channel, data)
        except Exception as exc:
            log.warning("SSE: fill user resolution failed: %s", exc)

    def handler(conn, pid: int, channel: str, payload: str) -> None:
        try:
            data = json.loads(payload)
        except Exception:
            return

        if channel == "cb_fills":
            # fills has no user_id — resolve via orders table
            order_id = data.get("order_id")
            if order_id:
                asyncio.get_event_loop().create_task(
                    _resolve_fill_user(order_id, channel, data)
                )
        else:
            _put_event(data.get("user_id"), channel, data)

    return handler


async def _listen_loop(dsn: str, pool: asyncpg.Pool) -> None:
    global _listener_conn
    handler = _make_notification_handler(pool)
    backoff = 1.0

    while True:
        try:
            conn = await _make_listener_conn(dsn)
            _listener_conn = conn

            for channel in CHANNEL_MAP:
                await conn.add_listener(channel, handler)

            log.info("SSE: LISTEN established on %d channels", len(CHANNEL_MAP))
            backoff = 1.0

            while True:
                await asyncio.sleep(15)
                try:
                    await conn.execute("SELECT 1")
                except Exception:
                    break  # connection lost, reconnect

        except asyncio.CancelledError:
            if _listener_conn and not _listener_conn.is_closed():
                await _listener_conn.close()
            raise
        except Exception as exc:
            log.error("SSE listener error: %s — reconnecting in %.0fs", exc, backoff)
            _listener_conn = None
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)


async def start_listener(dsn: str, pool: asyncpg.Pool) -> None:
    global _listener_task
    _listener_task = asyncio.create_task(
        _listen_loop(dsn, pool), name="sse_listener"
    )


async def stop_listener() -> None:
    global _listener_task, _listener_conn
    if _listener_task and not _listener_task.done():
        _listener_task.cancel()
        try:
            await _listener_task
        except asyncio.CancelledError:
            pass
    if _listener_conn and not _listener_conn.is_closed():
        await _listener_conn.close()
    _listener_conn = None


async def stream_for_user(user_id: str) -> AsyncIterator[dict]:
    """Async generator that yields SSE events for a single user.

    Yields dicts with 'event' and 'data' keys for sse-starlette.
    Sends a 'ping' comment every 25 seconds to keep the connection alive
    through proxies and Fly.io's idle timeout.
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    async with _lock:
        _user_queues.setdefault(user_id, []).append(queue)

    try:
        yield {"event": "connected", "data": json.dumps({"user_id": user_id})}
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=25.0)
                yield {"event": event["type"], "data": json.dumps(event["payload"])}
            except asyncio.TimeoutError:
                yield {"event": "ping", "data": "{}"}
    finally:
        async with _lock:
            queues = _user_queues.get(user_id, [])
            if queue in queues:
                queues.remove(queue)
            if not queues:
                _user_queues.pop(user_id, None)
