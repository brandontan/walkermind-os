"""PostgreSQL LISTEN/NOTIFY fan-out for the WebTrader SSE stream.

Uses a DEDICATED asyncpg connection (not the pool) because:
  - LISTEN puts a connection into a persistent notification mode.
  - Pool connections get recycled and UNLISTEN'd on return.
  - Supabase Supavisor pooler (port 6543) silently drops pg_notify.
    This module normalises the URL to the direct Postgres port (5432).

event_bus bridge:
  register_event_bus_handlers() wires position.opened, position.closed,
  and scanner.tick events from the in-process event_bus into SSE queues
  so the browser sees updates without polling.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, AsyncIterator
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

# reverse map: telegram_user_id (int) → user_id (UUID str) for event_bus bridge
_telegram_to_user_id: dict[int, str] = {}


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
                asyncio.get_running_loop().create_task(
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


def _push_to_user(user_id: str, event_type: str, payload: dict) -> None:
    """Push an SSE event directly to a specific user's queue(s)."""
    event = {"type": event_type, "payload": payload}
    for q in _user_queues.get(user_id, []):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass


def _push_broadcast(event_type: str, payload: dict) -> None:
    """Push an SSE event to all currently connected users."""
    event = {"type": event_type, "payload": payload}
    for queues in _user_queues.values():
        for q in queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass


# ---------------------------------------------------------------------------
# event_bus bridge handlers
# ---------------------------------------------------------------------------

async def _resolve_user_id_by_telegram(telegram_user_id: int) -> str | None:
    """DB fallback: resolve telegram_user_id → user UUID when not in reverse map."""
    from ...database import get_pool
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM users WHERE telegram_user_id = $1", telegram_user_id
            )
        return str(row["id"]) if row else None
    except Exception as exc:
        log.warning("SSE: DB user resolution failed telegram_user_id=%d: %s", telegram_user_id, exc)
        return None


async def _on_position_opened_sse(
    *,
    telegram_user_id: int,
    market_id: str,
    side: str,
    size_usdc: Any,
    price: float,
    market_question: str | None = None,
    strategy_type: str | None = None,
    **_: Any,
) -> None:
    if not _user_queues:
        return
    user_id = _telegram_to_user_id.get(telegram_user_id)
    if not user_id:
        log.debug("SSE: position.opened — telegram_user_id=%d not in reverse map, trying DB", telegram_user_id)
        user_id = await _resolve_user_id_by_telegram(telegram_user_id)
    if not user_id:
        log.debug("SSE: position.opened dropped — telegram_user_id=%d has no active WebTrader session", telegram_user_id)
        return
    _push_to_user(user_id, "position_opened", {
        "market_id": market_id,
        "market_question": market_question,
        "side": side,
        "size_usdc": float(size_usdc),
        "price": price,
        "strategy_type": strategy_type,
    })
    _push_to_user(user_id, "portfolio_update", {})


async def _on_position_closed_sse(
    *,
    telegram_user_id: int,
    market_id: str,
    pnl_usdc: Any,
    market_question: str | None = None,
    side: str = "",
    close_reason: str = "MANUAL",
    **_: Any,
) -> None:
    if not _user_queues:
        return
    user_id = _telegram_to_user_id.get(telegram_user_id)
    if not user_id:
        log.debug("SSE: position.closed — telegram_user_id=%d not in reverse map, trying DB", telegram_user_id)
        user_id = await _resolve_user_id_by_telegram(telegram_user_id)
    if not user_id:
        log.debug("SSE: position.closed dropped — telegram_user_id=%d has no active WebTrader session", telegram_user_id)
        return
    _push_to_user(user_id, "position_closed", {
        "market_id": market_id,
        "market_question": market_question,
        "side": side,
        "pnl_usdc": float(pnl_usdc),
        "close_reason": close_reason,
    })
    _push_to_user(user_id, "portfolio_update", {})


async def _on_scanner_tick_sse(
    *,
    markets: int = 0,
    signals: int = 0,
    ts: float = 0.0,
    **_: Any,
) -> None:
    log.info("SSE push: scanner.tick → %d users connected", len(_user_queues))
    _push_broadcast("scanner_tick", {"markets": markets, "signals": signals, "ts": ts})


def push_position_updated(user_id: str, position_id: str, current_price: float, pnl_usdc: float) -> None:
    """Push a position_updated tick to the user's SSE stream."""
    _push_to_user(user_id, "position_updated", {
        "position_id": position_id,
        "current_price": current_price,
        "pnl_usdc": pnl_usdc,
    })


def register_event_bus_handlers() -> None:
    """Subscribe SSE broadcaster to in-process event_bus events. Call once at startup."""
    from ...core.event_bus import subscribe
    subscribe("position.opened", _on_position_opened_sse)
    subscribe("position.closed", _on_position_closed_sse)
    subscribe("scanner.tick",    _on_scanner_tick_sse)
    log.info("SSE: event_bus handlers registered")


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


async def stream_for_user(
    user_id: str,
    telegram_user_id: int | None = None,
) -> AsyncIterator[dict]:
    """Async generator that yields SSE events for a single user.

    Yields dicts with 'event' and 'data' keys for sse-starlette.
    Sends a 'ping' comment every 25 seconds to keep the connection alive
    through proxies and Fly.io's idle timeout.

    telegram_user_id is stored so event_bus handlers can resolve UUID from
    telegram_user_id without a DB lookup.
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    async with _lock:
        _user_queues.setdefault(user_id, []).append(queue)
        if telegram_user_id is not None:
            _telegram_to_user_id[telegram_user_id] = user_id

    log.info("SSE: user %s connected (telegram_id=%s), active sessions: %d",
             user_id, telegram_user_id, len(_user_queues))

    try:
        yield {"event": "connected", "data": json.dumps({"user_id": user_id})}
        # Diagnostic: push test event through the queue to verify end-to-end delivery
        _push_to_user(user_id, "debug_connected", {
            "user_id": user_id,
            "sessions": len(_user_queues),
        })
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
                if telegram_user_id is not None:
                    _telegram_to_user_id.pop(telegram_user_id, None)
        log.info("SSE: user %s disconnected, remaining sessions: %d",
                 user_id, len(_user_queues))
