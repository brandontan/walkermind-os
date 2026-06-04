"""Live order reconciliation — broker-truth sweep for orphan/drift detection.

WARP-74 Chunk A (WARP•R00T). The ``OrderLifecycleManager`` poll loop reconciles
the DB -> broker direction (each in-flight DB order is checked against the broker
via ``get_order``). This module covers the REVERSE direction: it pulls the
broker's open orders and diffs them against the DB, surfacing two drift classes
the poll loop structurally cannot see:

  * ORPHAN  — an order resting at the broker that the DB has as terminal
              (filled / cancelled / expired / stale) or has no row for at all.
              This is uncontrolled live exposure: an ambiguous submit
              (``orders.status='unknown'``) that actually reached the book, a
              crash between submit and persist, or an order placed manually
              outside the bot.
  * DB_ONLY — an order the DB still tracks as open but the broker no longer lists
              as open (it filled / cancelled / expired). The poll loop owns
              resolving these; reconcile only counts them as drift telemetry.

Detection + telemetry ONLY. This module never cancels, sizes, gates, or mutates
an ``orders`` / ``positions`` row — it writes audit + structured logs and pages
the operator on a newly-seen orphan (throttled). Cancelling orphans is a
deliberate capital action handled elsewhere (operator action / kill-switch
cancel-all), never here.

Paper / non-live (``USE_REAL_CLOB=False``) is a no-op: nothing rests at a broker.
Fail-soft throughout — a broker hiccup or DB blip logs and returns; the sweep
never raises so a single bad pass can't stop the scheduler job.
"""
from __future__ import annotations

import time
from typing import Any, Awaitable, Callable, Optional

import structlog

from ... import audit as audit_module
from ... import notifications as notifications_module
from ...config import Settings, get_settings
from ...database import get_pool
from ...integrations.clob import (
    ClobAuthError,
    ClobClientProtocol,
    ClobConfigError,
    get_clob_client,
)
from .lifecycle import STATUS_OPEN

log = structlog.get_logger(__name__)


# Re-page cooldown per orphan broker id. A persistent orphan (operator hasn't
# cleared it yet) must not page on every sweep — once per this window is enough
# to keep it on the operator's radar without spamming. Keyed by broker_order_id.
ORPHAN_ALERT_COOLDOWN_SEC: float = 600.0
_MAX_ALERT_KEYS: int = 4096
_ALERT_PRUNE_SEC: float = 3600.0
_last_orphan_alert: dict[str, float] = {}

# Cap on the number of orphan ids enumerated in a single operator page so a
# pathological reconcile (e.g. account-wide drift) can't post a multi-KB message.
_MAX_PAGED_ORPHANS: int = 20


def _broker_id(order: dict) -> str:
    """Extract the broker order id from a /data/orders row.

    Polymarket has surfaced ``id`` / ``orderID`` / ``order_id`` across versions;
    accept all three so a schema variation never silently drops an order from the
    diff (which would manufacture a false orphan or hide a real one).
    """
    return str(
        order.get("id")
        or order.get("orderID")
        or order.get("order_id")
        or ""
    )


class LiveOrderReconciler:
    """Sweeps broker open orders against the DB and surfaces orphan/drift.

    Dependencies are injectable so the sweep is hermetically testable without a
    DB, broker, or Telegram. Defaults wire the real pool / CLOB factory / notify /
    audit surfaces, mirroring ``OrderLifecycleManager``.
    """

    def __init__(
        self,
        *,
        settings: Optional[Settings] = None,
        pool: Any = None,
        clob_factory: Optional[Callable[[Settings], ClobClientProtocol]] = None,
        notify_operator: Optional[Callable[[str], Awaitable[None]]] = None,
        audit_write: Optional[Callable[..., Awaitable[None]]] = None,
    ) -> None:
        self._settings = settings
        self._pool_override = pool
        self._clob_factory = clob_factory or get_clob_client
        self._notify_operator = (
            notify_operator or notifications_module.notify_operator
        )
        self._audit_write = audit_write or audit_module.write

    async def reconcile_once(self, *, now: float | None = None) -> dict:
        """Run one broker-truth reconcile sweep.

        Returns a small dict suitable for ``job_runs.metadata`` tracing:
        ``{skipped, broker_open, db_open, in_sync, orphans, db_only, errors}``.
        Never raises.
        """
        now = time.time() if now is None else now
        s = self._settings or get_settings()
        out = {
            "skipped": False, "broker_open": 0, "db_open": 0,
            "in_sync": 0, "orphans": 0, "db_only": 0, "errors": 0,
        }

        # Paper / non-live: nothing rests at a broker, so the sweep is a no-op.
        # Short-circuit before building a client to keep job_runs noise-free.
        if not s.USE_REAL_CLOB:
            out["skipped"] = True
            return out

        try:
            client = self._clob_factory(s)
        except (ClobConfigError, ClobAuthError) as exc:
            log.error("reconcile: CLOB client unavailable", err=str(exc))
            out["errors"] = 1
            return out

        try:
            try:
                broker_orders = await client.get_open_orders()
            except Exception as exc:  # noqa: BLE001 — fail-soft, retry next tick
                log.warning("reconcile: broker get_open_orders failed", err=str(exc))
                out["errors"] = 1
                return out

            broker_ids = [bid for bid in (_broker_id(o) for o in broker_orders) if bid]
            broker_set = set(broker_ids)
            out["broker_open"] = len(broker_set)

            try:
                db_open_ids, known = await self._load_db_state(broker_ids)
            except Exception as exc:  # noqa: BLE001 — fail-soft, retry next tick
                log.warning("reconcile: DB state load failed", err=str(exc))
                out["errors"] = 1
                return out
            out["db_open"] = len(db_open_ids)

            # ORPHAN diff: a broker-open id is in sync only when the DB still has
            # it as open. Any other state (terminal row, or no row at all) is an
            # orphan — live exposure the bot is not actively tracking.
            orphans: list[tuple[str, str | None]] = []
            for bid in broker_set:
                status = known.get(bid)
                if status in STATUS_OPEN:
                    out["in_sync"] += 1
                else:
                    orphans.append((bid, status))
            out["orphans"] = len(orphans)

            # DB_ONLY drift: DB thinks open, broker no longer lists it. The poll
            # loop owns resolving these (it polls each by id); reconcile only
            # counts them so the drift is visible in job metadata.
            out["db_only"] = len(db_open_ids - broker_set)

            if orphans:
                await self._handle_orphans(orphans, now)
            if out["orphans"] or out["db_only"]:
                await self._safe_audit(
                    actor_role="system",
                    action="live_orders_reconciled",
                    payload={
                        "broker_open": out["broker_open"],
                        "db_open": out["db_open"],
                        "in_sync": out["in_sync"],
                        "orphans": out["orphans"],
                        "db_only": out["db_only"],
                    },
                )
        finally:
            try:
                await client.aclose()
            except Exception as exc:  # noqa: BLE001
                log.warning("reconcile: client.aclose failed", err=str(exc))

        return out

    async def _load_db_state(
        self, broker_ids: list[str],
    ) -> tuple[set[str], dict[str, str]]:
        """Return (db_open_broker_ids, broker_id -> status for known broker ids).

        ``db_open_broker_ids`` are the broker ids of every live order the DB still
        tracks as open. ``known`` maps each *broker-reported* id to its current DB
        status (across ALL statuses) so the orphan diff can tell an untracked id
        (no row) apart from a terminal-drift id (row exists but is done).
        """
        pool = self._pool_override or get_pool()
        async with pool.acquire() as conn:
            # INTENTIONAL: operator-scoped, all-user read — reconcile compares the
            # broker account (single signer, all users) against every live order.
            db_open_rows = await conn.fetch(
                """
                SELECT polymarket_order_id
                  FROM orders
                 WHERE mode = 'live'
                   AND status = ANY($1::text[])
                   AND polymarket_order_id IS NOT NULL
                   AND polymarket_order_id <> ''
                """,
                list(STATUS_OPEN),
            )
            known: dict[str, str] = {}
            if broker_ids:
                known_rows = await conn.fetch(
                    """
                    SELECT polymarket_order_id, status
                      FROM orders
                     WHERE polymarket_order_id = ANY($1::text[])
                    """,
                    broker_ids,
                )
                for r in known_rows:
                    known[str(r["polymarket_order_id"])] = str(r["status"])
        db_open_ids = {str(r["polymarket_order_id"]) for r in db_open_rows}
        return db_open_ids, known

    async def _handle_orphans(
        self, orphans: list[tuple[str, str | None]], now: float,
    ) -> None:
        """Audit every orphan; page the operator for newly-seen ones (throttled)."""
        to_page: list[tuple[str, str | None]] = []
        for bid, status in orphans:
            await self._safe_audit(
                actor_role="system",
                action="live_order_orphan_detected",
                payload={"broker_order_id": bid, "db_status": status or "untracked"},
            )
            last = _last_orphan_alert.get(bid)
            if last is None or (now - last) >= ORPHAN_ALERT_COOLDOWN_SEC:
                _last_orphan_alert[bid] = now
                to_page.append((bid, status))

        # Bound the throttle map: prune ids untouched for a full prune window so a
        # long-running process can't accumulate them without limit.
        if len(_last_orphan_alert) > _MAX_ALERT_KEYS:
            cutoff = now - _ALERT_PRUNE_SEC
            for k in [k for k, t in _last_orphan_alert.items() if t < cutoff]:
                _last_orphan_alert.pop(k, None)

        if to_page:
            lines = "\n".join(
                f"• `{bid}` (db: {status or 'untracked'})"
                for bid, status in to_page[:_MAX_PAGED_ORPHANS]
            )
            more = (
                f"\n…and {len(to_page) - _MAX_PAGED_ORPHANS} more"
                if len(to_page) > _MAX_PAGED_ORPHANS else ""
            )
            try:
                await self._notify_operator(
                    "⚠️ *LIVE ORDER ORPHANS*\n"
                    f"{len(to_page)} order(s) resting at the broker not tracked "
                    f"as open:\n{lines}{more}\n"
                    "Reconcile via Polymarket dashboard or kill-switch cancel-all."
                )
            except Exception as exc:  # noqa: BLE001 — paging must never break the sweep
                log.error("reconcile: operator page failed", err=str(exc))

    async def _safe_audit(self, **kwargs: Any) -> None:
        try:
            await self._audit_write(**kwargs)
        except Exception as exc:  # noqa: BLE001
            log.error("reconcile: audit write failed", err=str(exc))


# ---------------------------------------------------------------------------
# Module-level entry point (APScheduler job target)
# ---------------------------------------------------------------------------

_default_reconciler: Optional[LiveOrderReconciler] = None


def get_default_reconciler() -> LiveOrderReconciler:
    global _default_reconciler
    if _default_reconciler is None:
        _default_reconciler = LiveOrderReconciler()
    return _default_reconciler


async def reconcile_once() -> dict:
    """Module-level shim used as the APScheduler job target."""
    return await get_default_reconciler().reconcile_once()


__all__ = [
    "LiveOrderReconciler",
    "reconcile_once",
    "get_default_reconciler",
    "ORPHAN_ALERT_COOLDOWN_SEC",
]
