"""WARP-74 Chunk A — live-order broker-reconcile sweep tests.

Covers the broker<->DB diff (in-sync / orphan-untracked / orphan-drift / db-only),
the paper-mode skip, fail-soft on broker + DB errors, the orphan operator-page
throttle, and aclose hygiene. Hermetic — no DB, no broker, no Telegram: a fake
asyncpg pool/conn serves canned rows and a fake CLOB client serves canned open
orders; notify/audit are captured in-memory.
"""
from __future__ import annotations

import asyncio

import pytest

from projects.polymarket.crusaderbot.domain.execution import reconcile as rc
from projects.polymarket.crusaderbot.domain.execution.reconcile import (
    LiveOrderReconciler,
)


# ── fakes ──────────────────────────────────────────────────────────────────
class _Settings:
    def __init__(self, use_real_clob: bool = True) -> None:
        self.USE_REAL_CLOB = use_real_clob


class _Client:
    def __init__(self, open_orders=None, raise_on_get: bool = False) -> None:
        self._open = open_orders or []
        self._raise = raise_on_get
        self.closed = False

    async def get_open_orders(self, market=None):
        if self._raise:
            raise RuntimeError("broker down")
        return self._open

    async def aclose(self):
        self.closed = True


class _Conn:
    def __init__(self, db_open=None, known=None, raise_on_fetch: bool = False) -> None:
        # db_open: list of broker ids the DB still tracks as open
        # known: {broker_id: status} across ALL statuses
        self._db_open = db_open or []
        self._known = known or {}
        self._raise = raise_on_fetch
        self.calls: list[tuple] = []

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        if self._raise:
            raise RuntimeError("db down")
        if "WHERE polymarket_order_id = ANY($1::text[])" in sql:
            ids = args[0]
            return [
                {"polymarket_order_id": b, "status": self._known[b]}
                for b in ids if b in self._known
            ]
        # db-open query
        return [{"polymarket_order_id": b} for b in self._db_open]


class _Pool:
    def __init__(self, conn: _Conn) -> None:
        self._c = conn

    def acquire(self):
        c = self._c

        class _Ctx:
            async def __aenter__(self_inner):
                return c

            async def __aexit__(self_inner, *a):
                return False

        return _Ctx()


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _reset_alert_throttle():
    rc._last_orphan_alert.clear()
    yield
    rc._last_orphan_alert.clear()


def _make(*, client, conn, settings=None):
    pages: list[str] = []
    audits: list[dict] = []

    async def _notify(text):
        pages.append(text)

    async def _audit(**kwargs):
        audits.append(kwargs)

    rec = LiveOrderReconciler(
        settings=settings or _Settings(),
        pool=_Pool(conn),
        clob_factory=lambda s: client,
        notify_operator=_notify,
        audit_write=_audit,
    )
    return rec, pages, audits


# ── paper-mode skip ────────────────────────────────────────────────────────
def test_paper_mode_skips_without_broker_call():
    client = _Client(open_orders=[{"id": "0xB1"}])
    rec, pages, audits = _make(
        client=client, conn=_Conn(), settings=_Settings(use_real_clob=False),
    )
    out = _run(rec.reconcile_once())
    assert out["skipped"] is True
    assert out["broker_open"] == 0
    assert client.closed is False  # never constructed/used
    assert pages == [] and audits == []


# ── in-sync: broker order matches a db-open order ──────────────────────────
def test_in_sync_no_orphan_no_page():
    client = _Client(open_orders=[{"id": "0xB1"}])
    conn = _Conn(db_open=["0xB1"], known={"0xB1": "submitted"})
    rec, pages, audits = _make(client=client, conn=conn)
    out = _run(rec.reconcile_once())
    assert out == {
        "skipped": False, "broker_open": 1, "db_open": 1,
        "in_sync": 1, "orphans": 0, "db_only": 0, "errors": 0,
    }
    assert pages == []            # nothing to escalate
    assert audits == []           # no orphans, no db_only -> no summary audit
    assert client.closed is True  # aclose hygiene


# ── orphan: untracked at DB (no row) ───────────────────────────────────────
def test_orphan_untracked_pages_and_audits():
    client = _Client(open_orders=[{"orderID": "0xZ9"}])
    conn = _Conn(db_open=[], known={})
    rec, pages, audits = _make(client=client, conn=conn)
    out = _run(rec.reconcile_once())
    assert out["orphans"] == 1 and out["in_sync"] == 0
    assert len(pages) == 1 and "ORPHANS" in pages[0] and "0xZ9" in pages[0]
    actions = [a["action"] for a in audits]
    assert "live_order_orphan_detected" in actions
    assert "live_orders_reconciled" in actions
    detected = next(a for a in audits if a["action"] == "live_order_orphan_detected")
    assert detected["payload"]["db_status"] == "untracked"


# ── orphan: drift (DB row exists but is terminal) ──────────────────────────
def test_orphan_terminal_drift():
    client = _Client(open_orders=[{"order_id": "0xC3"}])
    conn = _Conn(db_open=[], known={"0xC3": "filled"})
    rec, pages, audits = _make(client=client, conn=conn)
    out = _run(rec.reconcile_once())
    assert out["orphans"] == 1
    detected = next(a for a in audits if a["action"] == "live_order_orphan_detected")
    assert detected["payload"]["db_status"] == "filled"


# ── db-only drift: DB open, not at broker (poll owns it; count only) ───────
def test_db_only_counted_no_page():
    client = _Client(open_orders=[])  # broker has nothing open
    conn = _Conn(db_open=["0xD1"], known={})
    rec, pages, audits = _make(client=client, conn=conn)
    out = _run(rec.reconcile_once())
    assert out["db_only"] == 1 and out["orphans"] == 0
    assert pages == []  # db-only is not an escalation
    assert [a["action"] for a in audits] == ["live_orders_reconciled"]


# ── orphan page throttle: re-page suppressed within cooldown ───────────────
def test_orphan_page_throttled_within_cooldown():
    client = _Client(open_orders=[{"id": "0xZ9"}])
    conn = _Conn(db_open=[], known={})
    rec, pages, _ = _make(client=client, conn=conn)
    _run(rec.reconcile_once(now=1000.0))
    _run(rec.reconcile_once(now=1100.0))  # < ORPHAN_ALERT_COOLDOWN_SEC (600)
    assert len(pages) == 1                # second pass did not re-page
    _run(rec.reconcile_once(now=2000.0))  # > cooldown -> pages again
    assert len(pages) == 2


# ── fail-soft: broker get_open_orders raises ───────────────────────────────
def test_failsoft_on_broker_error():
    client = _Client(raise_on_get=True)
    rec, pages, audits = _make(client=client, conn=_Conn())
    out = _run(rec.reconcile_once())
    assert out["errors"] == 1 and out["orphans"] == 0
    assert pages == []
    assert client.closed is True  # aclose still runs in finally


# ── fail-soft: DB load raises ──────────────────────────────────────────────
def test_failsoft_on_db_error():
    client = _Client(open_orders=[{"id": "0xB1"}])
    conn = _Conn(raise_on_fetch=True)
    rec, pages, audits = _make(client=client, conn=conn)
    out = _run(rec.reconcile_once())
    assert out["errors"] == 1
    assert client.closed is True


# ── client construction error -> errors, no broker call ────────────────────
def test_client_config_error():
    from projects.polymarket.crusaderbot.integrations.clob import ClobConfigError

    def _boom(s):
        raise ClobConfigError("no creds")

    rec = LiveOrderReconciler(
        settings=_Settings(), pool=_Pool(_Conn()), clob_factory=_boom,
    )
    out = _run(rec.reconcile_once())
    assert out["errors"] == 1 and out["skipped"] is False
