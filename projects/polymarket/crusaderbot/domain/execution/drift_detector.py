"""WARP-74 Chunk C — broker <-> DB open-order drift detector.

A periodic safety net that compares the set of orders the BROKER reports as open
against the set of orders the DB believes are open, and pages the operator on
divergence. Two drift directions, both meaningful:

  * broker-only — a resting order live on Polymarket that the DB does NOT track.
    The dangerous direction: untracked exposure the lifecycle poller will never
    progress and the kill switch's global cancel is the only thing that catches.

  * db-only — an order the DB still marks open that the broker no longer lists.
    Usually a benign race (the order filled/cancelled between the lifecycle
    poll and this scan) but a persistent db-only id is a stuck row worth a look.

ALERT-ONLY by design: it never cancels or mutates orders — auto-acting on a
transient race would be more dangerous than the drift itself. Paper / non-live is
a no-op. Never raises.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

import structlog

from ... import audit, notifications
from ...config import get_settings
from ...database import get_pool
from ...integrations.clob import (
    ClobAuthError,
    ClobClientProtocol,
    ClobConfigError,
    get_clob_client,
)

log = structlog.get_logger(__name__)

_BROKER_ID_KEYS = ("orderID", "order_id", "id", "orderId")
_DB_OPEN_STATUSES = ("submitted", "pending", "partial_filled")


def _broker_id(o: dict[str, Any]) -> str:
    for k in _BROKER_ID_KEYS:
        v = o.get(k)
        if v:
            return str(v)
    return ""


async def detect_order_drift(
    *, pool=None, clob_factory=None, settings: Any = None,
) -> dict:
    """One drift-detection sweep. Returns a small dict for job-tracker tracing."""
    s = settings or get_settings()
    if not bool(getattr(s, "USE_REAL_CLOB", False)):
        return {"checked": False, "skipped_paper": True}
    if not bool(getattr(s, "ORDER_DRIFT_DETECT_ENABLED", True)):
        return {"checked": False, "skipped_disabled": True}
    pool = pool or get_pool()

    factory: Callable[[Any], ClobClientProtocol] = clob_factory or get_clob_client
    client: Optional[ClobClientProtocol] = None
    try:
        client = factory(s)
    except (ClobConfigError, ClobAuthError) as exc:
        log.error("order_drift_client_unavailable", err=str(exc))
        return {"checked": False, "error": str(exc)[:200]}

    try:
        try:
            broker_orders = await client.get_open_orders()
        except Exception as exc:  # noqa: BLE001 — broker hiccup must not raise
            log.warning("order_drift_broker_query_failed", err=str(exc))
            return {"checked": False, "error": str(exc)[:200]}

        broker_ids = {bid for o in (broker_orders or [])
                      if (bid := _broker_id(o))}

        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT polymarket_order_id FROM orders "
                    "WHERE mode='live' AND status = ANY($1::text[]) "
                    "AND polymarket_order_id IS NOT NULL "
                    "AND polymarket_order_id <> ''",
                    list(_DB_OPEN_STATUSES),
                )
        except Exception as exc:  # noqa: BLE001
            log.exception("order_drift_db_query_failed", err=str(exc))
            return {"checked": False, "error": str(exc)[:200]}

        db_ids = {str(r["polymarket_order_id"]) for r in rows}

        broker_only = sorted(broker_ids - db_ids)
        db_only = sorted(db_ids - broker_ids)
        out = {
            "checked": True,
            "broker_open": len(broker_ids),
            "db_open": len(db_ids),
            "broker_only": len(broker_only),
            "db_only": len(db_only),
        }
        if not broker_only and not db_only:
            log.info("order_drift_clean", **out)
            return out

        await audit.write(
            actor_role="bot", action="order_drift_detected",
            payload={"broker_only": broker_only[:50], "db_only": db_only[:50],
                     "broker_open": len(broker_ids), "db_open": len(db_ids)},
        )
        lines = ["⚠️ <b>ORDER DRIFT DETECTED</b>"]
        if broker_only:
            lines.append(
                f"• {len(broker_only)} resting order(s) LIVE on the exchange but "
                f"UNTRACKED in DB (orphan exposure): "
                f"<code>{', '.join(broker_only[:8])}</code>"
            )
        if db_only:
            lines.append(
                f"• {len(db_only)} order(s) marked open in DB but NOT on the "
                f"exchange (likely filled/cancelled mid-cycle): "
                f"<code>{', '.join(db_only[:8])}</code>"
            )
        try:
            await notifications.notify_operator("\n".join(lines))
        except Exception as exc:  # noqa: BLE001
            log.error("order_drift_page_failed", err=str(exc))
        log.warning("order_drift_detected", **out)
        return out
    finally:
        if client is not None:
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001
                log.warning("order_drift_client_close_failed")


__all__ = ["detect_order_drift"]
