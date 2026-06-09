"""Per-user notification preferences gate.

Single source of truth for the 9 alert keys × 2 channels (web, tg) preference
matrix surfaced in the WebTrader "Notification Preferences" card. Default is
both channels ON for every key; users override per-row via the UI.

`should_notify(user_id, alert_key, channel)` is the gate every notification
sender calls before delivery. Unknown alert keys / channels return True
(fail-open — better to send a notification than silently drop one).

`persist_user_alert(...)` writes to system_alerts.user_id so the row shows in
the user's WebTrader AlertCenter; gated by should_notify(user_id, key, "web").

`route_outgoing_alert(...)` is the convenience wrapper every inner TG send
helper calls: resolves user_id from telegram_user_id, writes the web mirror
when web channel is enabled, returns True iff the TG channel should also fire.
"""
from __future__ import annotations

import asyncio
import html as _html
import json as _json
import logging
import re
import time
from typing import Literal, Optional
from uuid import UUID

import structlog

from ...database import get_pool

logger = logging.getLogger(__name__)
log = structlog.get_logger(__name__)

Channel = Literal["web", "tg"]

# Keys must match NotificationPrefsCard.tsx exactly — the UI is the source of
# truth for which alert categories exist. Adding a new alert in code without
# also adding the UI row would orphan it (defaults still apply — fail-open).
ALERT_KEYS: frozenset[str] = frozenset({
    "trade_opened",
    "trade_closed",
    "position_resolved",
    "signal_detected",
    "system_status",
    "bot_errors",
    "kill_switch",
    "low_balance",
    "daily_report",
})

VALID_CHANNELS: frozenset[Channel] = frozenset({"web", "tg"})

# Severity for system_alerts rows persisted via persist_user_alert(). Caller
# can pass an explicit severity; this is the default fallback for events that
# don't carry their own severity.
DEFAULT_SEVERITY = "info"


async def get_prefs(user_id: UUID | str) -> dict[str, dict[str, bool]]:
    """Read the raw notification_prefs JSONB for a user. Returns {} when unset.

    Caller should treat missing keys + missing channels as True (default ON).
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT notification_prefs FROM user_settings WHERE user_id = $1::uuid",
            str(user_id),
        )
    if row is None or row["notification_prefs"] is None:
        return {}
    raw = row["notification_prefs"]
    # asyncpg returns JSONB as already-parsed dict; older paths might give str.
    if isinstance(raw, str):
        import json
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return {}
    if not isinstance(raw, dict):
        return {}
    return raw


async def set_prefs(user_id: UUID | str, prefs: dict[str, dict[str, bool]]) -> None:
    """Overwrite the notification_prefs blob. Caller is expected to send the
    complete prefs dict (UI loads, edits, saves the whole thing).

    Unknown keys / channels are dropped silently — UI guarantees shape so a
    drift here is a frontend bug, not a user-facing failure.
    """
    cleaned: dict[str, dict[str, bool]] = {}
    for k, v in prefs.items():
        if k not in ALERT_KEYS or not isinstance(v, dict):
            continue
        channels: dict[str, bool] = {}
        for ch, on in v.items():
            if ch in VALID_CHANNELS:
                channels[ch] = bool(on)
        if channels:
            cleaned[k] = channels

    import json
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE user_settings
               SET notification_prefs = $1::jsonb
             WHERE user_id = $2::uuid
            """,
            json.dumps(cleaned),
            str(user_id),
        )


async def should_notify(
    user_id: UUID | str | None,
    alert_key: str,
    channel: Channel,
) -> bool:
    """Return True if the user wants this alert delivered on this channel.

    Fail-open semantics: unknown user_id / alert_key / channel → True. The
    cost of a stray notification is much lower than a missed trade event.
    DB unreachable → True (logged WARNING).
    """
    if user_id is None:
        return True
    if alert_key not in ALERT_KEYS or channel not in VALID_CHANNELS:
        return True
    try:
        prefs = await get_prefs(user_id)
    except Exception:
        logger.warning(
            "notification_prefs_read_failed user_id=%s alert=%s channel=%s",
            user_id, alert_key, channel,
            exc_info=True,
        )
        return True
    row = prefs.get(alert_key)
    if not isinstance(row, dict):
        return True  # default: both channels ON
    val = row.get(channel)
    if not isinstance(val, bool):
        return True
    return val


# Tag-strip regex. Inner-send helpers build Telegram messages with HTML
# formatting (<b>, <pre>, <code>, &amp; entities, etc.) — the WebTrader
# AlertCenter renders body as plain text, so unstripped tags show up literally
# as "<pre>Market | …</pre>" to the user. We render once to plain text on the
# way in to system_alerts so the DB row is consumer-agnostic.
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RUN = re.compile(r"[ \t]+\n")


def _strip_html_for_web(text: Optional[str]) -> Optional[str]:
    """Convert a Telegram-formatted body to plain text suitable for the web
    AlertCenter. Idempotent and tolerant of None / non-string input."""
    if not text:
        return text
    if not isinstance(text, str):
        return str(text)
    # Strip tags first, then decode entities (&amp; → &, &lt; → <, etc.).
    stripped = _HTML_TAG_RE.sub("", text)
    decoded = _html.unescape(stripped)
    # Collapse "Foo   \n" trailing whitespace from the pre-block layout so
    # the AlertCenter card is dense.
    cleaned = _WHITESPACE_RUN.sub("\n", decoded)
    return cleaned.strip()


async def persist_user_alert(
    *,
    user_id: UUID | str,
    alert_key: str,
    title: str,
    body: Optional[str] = None,
    severity: str = DEFAULT_SEVERITY,
    alert_kind: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> Optional[str]:
    """Write a per-user row into system_alerts when the user wants web delivery.

    Returns the alert UUID on insert, None if the user disabled web delivery
    for this alert_key (or if the write fails — failure is logged, not raised,
    so an alert outage cannot break the calling event flow).

    ``alert_kind`` is a short discriminator (e.g. 'trade_opened', 'tp_hit')
    that the WebTrader AlertCenter renders by. ``metadata`` carries the
    structured event fields (market_label, side, size_usdc, entry_price,
    exit_price, pnl_usdc, strategy, mode, market_id, position_id, ...).
    Both default to NULL/{} so legacy callers stay unchanged.
    """
    try:
        ok = await should_notify(user_id, alert_key, "web")
    except Exception:
        ok = True
    if not ok:
        return None

    if severity not in ("info", "warning", "critical"):
        severity = DEFAULT_SEVERITY

    clean_title = _strip_html_for_web(title) or title
    clean_body = _strip_html_for_web(body)
    payload = metadata if isinstance(metadata, dict) else {}

    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO system_alerts (
                    user_id, severity, title, body, alert_kind, metadata
                )
                VALUES ($1::uuid, $2, $3, $4, $5, $6::jsonb)
                RETURNING id
                """,
                str(user_id), severity, clean_title, clean_body,
                alert_kind, _json.dumps(payload),
            )
        if row is None:
            return None
        return str(row["id"])
    except Exception:
        logger.warning(
            "persist_user_alert_failed user_id=%s alert=%s",
            user_id, alert_key,
            exc_info=True,
        )
        return None


# ---------------------------------------------------------------------------
# Telegram-ID → user_id resolver with a small TTL cache.
# The cache avoids a DB roundtrip on every notification; entries are tiny
# (int → str pair) and expire fast so a re-link of an account is picked up
# within the TTL window without manual eviction.
# ---------------------------------------------------------------------------

_TG_ID_CACHE: dict[int, tuple[str | None, float]] = {}
_TG_ID_CACHE_TTL_SEC = 60.0
_TG_ID_CACHE_LOCK = asyncio.Lock()

# ---------------------------------------------------------------------------
# Dedup cache — suppresses duplicate route_outgoing_alert calls when
# multiple surfaces (notification_service / trade_notifications / monitoring)
# fire for the same event within a 30 s window.
# Key: (user_id_str, alert_key, dedup_key).  Value: monotonic expiry time.
# Caller provides dedup_key (typically market_id); None = no dedup (fail-open).
# ---------------------------------------------------------------------------

_DEDUP_CACHE: dict[tuple[str, str, str], float] = {}
_DEDUP_TTL_SEC: float = 30.0
_DEDUP_LOCK = asyncio.Lock()


async def resolve_user_id_for_telegram(telegram_user_id: int | None) -> Optional[str]:
    """Return the users.id UUID (as string) for a given telegram_user_id, or None.

    Hot path: ~ microseconds via in-process cache. Cold path: one indexed DB
    SELECT. None means "no matching row" — the gate falls back to fail-open.
    DB error → None (logged WARNING) so notifications continue to flow.
    """
    if telegram_user_id is None:
        return None

    now = time.monotonic()
    hit = _TG_ID_CACHE.get(telegram_user_id)
    if hit is not None:
        uid, expires_at = hit
        if expires_at > now:
            return uid

    async with _TG_ID_CACHE_LOCK:
        hit = _TG_ID_CACHE.get(telegram_user_id)
        if hit is not None:
            uid, expires_at = hit
            if expires_at > now:
                return uid

        try:
            pool = get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id FROM users WHERE telegram_user_id = $1",
                    int(telegram_user_id),
                )
        except Exception:
            logger.warning(
                "resolve_user_id_for_telegram_failed telegram_user_id=%s",
                telegram_user_id, exc_info=True,
            )
            return None

        uid = str(row["id"]) if row else None
        _TG_ID_CACHE[telegram_user_id] = (uid, now + _TG_ID_CACHE_TTL_SEC)
        return uid


async def route_outgoing_alert(
    *,
    telegram_user_id: int | None,
    alert_key: str,
    web_title: str,
    web_body: Optional[str] = None,
    severity: str = DEFAULT_SEVERITY,
    dedup_key: Optional[str] = None,
    alert_kind: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> bool:
    """End-to-end routing for a user-facing notification.

    Steps:
      1. Resolve user_id from telegram_user_id (cached).
      2. Dedup check: if the same (user, alert_key, dedup_key) already fired
         within _DEDUP_TTL_SEC, suppress both web insert and TG send.
      3. If user_id resolved AND user wants web → INSERT into system_alerts.
      4. Return True iff the Telegram channel should also fire.

    Fail-open: any DB error / unknown user / unknown alert_key returns True
    for TG so a missing pref row never silently drops the notification.
    dedup_key=None disables dedup (caller has no event context to key on).
    """
    user_id = await resolve_user_id_for_telegram(telegram_user_id)

    # Dedup: suppress duplicate calls from multiple surfaces firing for the
    # same event within the TTL window. Only active when dedup_key provided.
    if dedup_key is not None and user_id is not None:
        cache_key = (user_id, alert_key, dedup_key)
        now = time.monotonic()
        async with _DEDUP_LOCK:
            expires_at = _DEDUP_CACHE.get(cache_key)
            if expires_at is not None and expires_at > now:
                log.debug(
                    "route_outgoing_alert.dedup_hit",
                    user_id=user_id,
                    alert_key=alert_key,
                    dedup_key=dedup_key,
                )
                return False
            _DEDUP_CACHE[cache_key] = now + _DEDUP_TTL_SEC
            if len(_DEDUP_CACHE) > 4096:
                _evict_stale_dedup(now)

    # Web mirror is best-effort and self-gated by should_notify(.., "web").
    if user_id is not None:
        try:
            await persist_user_alert(
                user_id=user_id,
                alert_key=alert_key,
                title=web_title,
                body=web_body,
                severity=severity,
                alert_kind=alert_kind,
                metadata=metadata,
            )
        except Exception:
            logger.warning(
                "route_outgoing_alert_web_mirror_failed user_id=%s alert=%s",
                user_id, alert_key,
                exc_info=True,
            )

    return await should_notify(user_id, alert_key, "tg")


def _evict_cache_entry(telegram_user_id: int) -> None:
    """Test-only helper — drops a single cached telegram_user_id → user_id row."""
    _TG_ID_CACHE.pop(telegram_user_id, None)


def _evict_stale_dedup(now: float) -> None:
    """Remove expired entries from _DEDUP_CACHE. Must be called under _DEDUP_LOCK."""
    stale = [k for k, exp in _DEDUP_CACHE.items() if exp <= now]
    for k in stale:
        del _DEDUP_CACHE[k]


def _clear_dedup_cache() -> None:
    """Test-only helper — clears the entire dedup cache."""
    _DEDUP_CACHE.clear()
