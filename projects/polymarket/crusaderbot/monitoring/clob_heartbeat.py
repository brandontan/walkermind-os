"""WARP-77 Phase 1.2 — real-CLOB-data feed heartbeat.

Tracks the freshness of the unauthenticated CLOB data feed (every successful
``MarketDataClient`` read stamps a timestamp) and pages the operator + Sentry when
the feed goes stale. Mirrors the WARP-76 H3 RTDS oracle feed-loss fail-safe
(latched, paged once per down<->up transition, auto-resume), but for the
market-data feed the strategy consumes on real data after the ``USE_PYSDK_CLOB``
cutover.

DORMANCY (proven by tests): the alarm ARMS ONLY when ``USE_PYSDK_CLOB`` is true.
On the legacy adapter (current prod) ``check_clob_feed_and_alert`` returns
immediately, so it can NEVER page. ``mark_clob_read_ok`` is a cheap timestamp set
with no side effects, safe to call on every read regardless of mode. Every path is
fail-soft — monitoring never breaks a read or the scheduler.
"""
from __future__ import annotations

import time
from typing import Any, Awaitable, Callable, Optional

import structlog

log = structlog.get_logger(__name__)

# Last successful real-CLOB data read (epoch seconds), and the down-latch so the
# operator is paged exactly once per down<->up transition (not every check tick).
_last_read_ok_ts: Optional[float] = None
_feed_down: bool = False


def mark_clob_read_ok(ts: Optional[float] = None) -> None:
    """Stamp a successful CLOB data read. Cheap, side-effect-free; never raises."""
    global _last_read_ok_ts
    try:
        _last_read_ok_ts = time.time() if ts is None else float(ts)
    except Exception:  # noqa: BLE001 — telemetry must never break a read
        pass


def clob_feed_age_sec(now: Optional[float] = None) -> Optional[float]:
    """Age (seconds) of the newest successful read, or ``None`` if none seen yet."""
    if _last_read_ok_ts is None:
        return None
    n = time.time() if now is None else now
    return n - _last_read_ok_ts


def clob_feed_down(timeout_sec: float, now: Optional[float] = None) -> bool:
    """True when the feed is stale beyond ``timeout_sec``.

    Mirrors ``oracle.is_feed_down``: a feed that has never produced a read is NOT
    'down' (it is warming up) — we never page on a cold start.
    """
    age = clob_feed_age_sec(now)
    if age is None:
        return False
    try:
        return age > float(timeout_sec)
    except (TypeError, ValueError):
        return False


async def _page(text: str) -> None:
    """Best-effort operator Telegram page. Never raises."""
    try:
        from .. import notifications

        await notifications.notify_operator(text)
    except Exception as exc:  # noqa: BLE001 — page is best-effort
        log.warning("clob_feed_page_failed", error=str(exc))


def _sentry(message: str) -> None:
    """Best-effort Sentry capture at error level. Never raises."""
    try:
        import sentry_sdk

        sentry_sdk.capture_message(message, level="error")
    except Exception:  # noqa: BLE001 — Sentry capture is best-effort
        pass


def _reset_for_test() -> None:
    """Test hook: clear module state (last-read stamp + down latch)."""
    global _last_read_ok_ts, _feed_down
    _last_read_ok_ts = None
    _feed_down = False


async def check_clob_feed_and_alert(
    *,
    settings: Any = None,
    now: Optional[float] = None,
    page_fn: Optional[Callable[[str], Awaitable[None]]] = None,
    capture_fn: Optional[Callable[[str], None]] = None,
) -> bool:
    """Page (once per transition) when the real-CLOB data feed goes stale.

    Returns the current down state. ARMS ONLY when ``USE_PYSDK_CLOB`` is true; on
    the legacy adapter it returns ``False`` immediately (dormant — cannot page in
    current prod). Fail-soft: any error returns ``False`` so a monitoring fault can
    never escalate into a phantom alarm.
    """
    global _feed_down
    try:
        if settings is None:
            from ..config import get_settings

            settings = get_settings()
        if not bool(getattr(settings, "USE_PYSDK_CLOB", False)):
            return False  # dormant on the legacy adapter
        timeout = float(getattr(settings, "CLOB_DATA_FEED_TIMEOUT_SEC", 180))
        down = clob_feed_down(timeout, now)
    except Exception as exc:  # noqa: BLE001 — monitoring must never escalate
        log.warning("clob_feed_check_error", error=str(exc))
        return False

    page = page_fn or _page
    capture = capture_fn or _sentry
    try:
        if down and not _feed_down:
            _feed_down = True
            log.error("clob_data_feed_lost")
            capture(
                "CLOB data feed lost: no successful MarketDataClient read within "
                "CLOB_DATA_FEED_TIMEOUT_SEC (USE_PYSDK_CLOB on)"
            )
            await page(
                "🚨 <b>CLOB data feed lost</b>\n"
                "No successful market-data read within CLOB_DATA_FEED_TIMEOUT_SEC "
                "while USE_PYSDK_CLOB is on — the strategy is running on stale or "
                "absent real-CLOB data. Investigate the feed."
            )
        elif not down and _feed_down:
            _feed_down = False
            log.info("clob_data_feed_restored")
            await page(
                "✅ <b>CLOB data feed restored</b>\n"
                "Market-data reads are fresh again."
            )
    except Exception as exc:  # noqa: BLE001 — alerting is best-effort
        log.warning("clob_feed_alert_failed", error=str(exc))
    return down


__all__ = [
    "mark_clob_read_ok",
    "clob_feed_age_sec",
    "clob_feed_down",
    "check_clob_feed_and_alert",
]
