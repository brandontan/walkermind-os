"""Per-user notification preferences gate.

Single source of truth for the 9 alert keys × 2 channels (web, tg) preference
matrix surfaced in the WebTrader "Notification Preferences" card. Default is
both channels ON for every key; users override per-row via the UI.

`should_notify(user_id, alert_key, channel)` is the gate every notification
sender calls before delivery. Unknown alert keys / channels return True
(fail-open — better to send a notification than silently drop one).

`persist_user_alert(...)` writes to system_alerts.user_id so the row shows in
the user's WebTrader AlertCenter; gated by should_notify(user_id, key, "web").
"""
from __future__ import annotations

import logging
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


async def persist_user_alert(
    *,
    user_id: UUID | str,
    alert_key: str,
    title: str,
    body: Optional[str] = None,
    severity: str = DEFAULT_SEVERITY,
) -> Optional[str]:
    """Write a per-user row into system_alerts when the user wants web delivery.

    Returns the alert UUID on insert, None if the user disabled web delivery
    for this alert_key (or if the write fails — failure is logged, not raised,
    so an alert outage cannot break the calling event flow).
    """
    try:
        ok = await should_notify(user_id, alert_key, "web")
    except Exception:
        ok = True
    if not ok:
        return None

    if severity not in ("info", "warning", "critical"):
        severity = DEFAULT_SEVERITY

    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO system_alerts (user_id, severity, title, body)
                VALUES ($1::uuid, $2, $3, $4)
                RETURNING id
                """,
                str(user_id), severity, title, body,
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
