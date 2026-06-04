"""WARP-74 Chunk A — generalized live reconciler routing tests.

Hermetic: fake pool + fake CLOB client. Asserts the DECISION routing of
``reconcile_live_orders`` (directional 'unknown' orders) and
``reconcile_closing_positions`` (stranded 'closing' rows) against broker truth.
Never touches a real DB / network.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from projects.polymarket.crusaderbot.domain.execution import live_reconcile as lr

pytestmark = pytest.mark.asyncio

_NOTIF = "projects.polymarket.crusaderbot.notifications.notify_operator"
_AUDIT = "projects.polymarket.crusaderbot.audit.write"
_KILL = "projects.polymarket.crusaderbot.domain.ops.kill_switch.set_active"
_CREDIT = "projects.polymarket.crusaderbot.wallet.ledger.credit_in_conn"


# --- fakes --------------------------------------------------------------------
class _Tx:
    async def __aenter__(self) -> "_Tx":
        return self

    async def __aexit__(self, *_a: Any) -> bool:
        return False


class _Conn:
    def __init__(self, *, scan_rows=None, tracked_rows=None, market_row=None,
                 closing_rows=None, finalize_id=None) -> None:
        self.scan_rows = scan_rows or []
        self.tracked_rows = tracked_rows or []
        self.market_row = market_row
        self.closing_rows = closing_rows or []
        self.finalize_id = finalize_id
        self.executed: list[tuple] = []

    async def fetch(self, q: str, *_a: Any) -> list[dict]:
        if "o.status = 'unknown'" in q:
            return self.scan_rows
        if "SELECT polymarket_order_id FROM orders" in q:
            return self.tracked_rows
        if "FROM positions WHERE mode='live' AND status='closing'" in q:
            return self.closing_rows
        return []

    async def fetchrow(self, q: str, *_a: Any) -> dict | None:
        if "FROM markets" in q:
            return self.market_row
        return None

    async def fetchval(self, q: str, *_a: Any) -> Any:
        if "status='closed'" in q and "RETURNING id" in q:
            return self.finalize_id
        return None

    async def execute(self, q: str, *a: Any) -> str:
        self.executed.append((q, a))
        return "OK"

    def transaction(self) -> _Tx:
        return _Tx()


class _Acquire:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _Conn:
        return self._conn

    async def __aexit__(self, *_a: Any) -> bool:
        return False


class _Pool:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    def acquire(self) -> _Acquire:
        return _Acquire(self._conn)


class _Clob:
    def __init__(self, *, open_orders=None, order=None, fills=None,
                 raise_open=False, raise_get=False) -> None:
        self.open_orders = open_orders or []
        self.order = order or {"status": "unknown"}
        self.fills = fills or []
        self.raise_open = raise_open
        self.raise_get = raise_get
        self.closed = False

    async def get_open_orders(self, market: str | None = None) -> list[dict]:
        if self.raise_open:
            raise RuntimeError("broker down")
        return list(self.open_orders)

    async def get_order(self, _oid: str) -> dict:
        if self.raise_get:
            raise RuntimeError("broker down")
        return self.order

    async def get_fills(self, _oid: str) -> list[dict]:
        return list(self.fills)

    async def aclose(self) -> None:
        self.closed = True


def _settings(**over: Any) -> SimpleNamespace:
    base = dict(USE_REAL_CLOB=True, LIVE_RECONCILE_ENABLED=True,
                LIVE_RECONCILE_STALE_SEC=300, LIVE_CLOSING_STALE_SEC=120,
                LIVE_RECONCILE_FILLS_WINDOW_SEC=3600)
    base.update(over)
    return SimpleNamespace(**base)


def _unknown_row(**over: Any) -> dict:
    base = {"id": uuid4(), "user_id": uuid4(), "market_id": "m1", "side": "yes",
            "size_usdc": 50.0, "price": 0.5, "polymarket_order_id": "",
            "status": "unknown", "strategy_type": "late_entry_v3"}
    base.update(over)
    return base


def _closing_row(**over: Any) -> dict:
    base = {"id": uuid4(), "user_id": uuid4(), "market_id": "m1", "side": "yes",
            "size_usdc": 50.0, "entry_price": 0.5, "current_price": 0.6,
            "close_order_id": "C1", "closing_at": None}
    base.update(over)
    return base


@pytest.fixture(autouse=True)
def _rec(monkeypatch):
    rec = {"page": [], "audit": [], "kill": [], "credit": []}

    async def _page(text, *_a, **_k):
        rec["page"].append(text)

    async def _audit(**kw):
        rec["audit"].append(kw)

    async def _kill(*_a, **kw):
        rec["kill"].append(kw)

    async def _credit(conn, user_id, amount, kind, *, ref_id=None, note=""):
        rec["credit"].append((user_id, amount, kind))

    monkeypatch.setattr(_NOTIF, _page)
    monkeypatch.setattr(_AUDIT, _audit)
    monkeypatch.setattr(_KILL, _kill)
    monkeypatch.setattr(_CREDIT, _credit)
    return rec


def _wire_pool(monkeypatch, conn: _Conn) -> _Pool:
    pool = _Pool(conn)
    monkeypatch.setattr(lr, "get_pool", lambda: pool)
    return pool


# --- reconcile_live_orders ----------------------------------------------------
async def test_paper_mode_is_noop() -> None:
    res = await lr.reconcile_live_orders(
        pool=_Pool(_Conn()), clob_factory=lambda s: _Clob(),
        settings=_settings(USE_REAL_CLOB=False))
    assert res == {"scanned": 0, "skipped_paper": True}


async def test_disabled_is_noop() -> None:
    res = await lr.reconcile_live_orders(
        pool=_Pool(_Conn()), clob_factory=lambda s: _Clob(),
        settings=_settings(LIVE_RECONCILE_ENABLED=False))
    assert res == {"scanned": 0, "skipped_disabled": True}


async def test_no_rows_noop(monkeypatch) -> None:
    conn = _Conn(scan_rows=[])
    pool = _wire_pool(monkeypatch, conn)
    res = await lr.reconcile_live_orders(
        pool=pool, clob_factory=lambda s: _Clob(), settings=_settings())
    assert res["scanned"] == 0


async def test_unique_resting_order_is_adopted(monkeypatch, _rec) -> None:
    conn = _Conn(scan_rows=[_unknown_row()], tracked_rows=[],
                 market_row={"yes_token_id": "TOK", "no_token_id": "TOKNO"})
    pool = _wire_pool(monkeypatch, conn)
    clob = _Clob(open_orders=[{"asset_id": "TOK", "orderID": "B1"}])
    res = await lr.reconcile_live_orders(
        pool=pool, clob_factory=lambda s: clob, settings=_settings())
    assert res["adopted"] == 1
    assert any("status='pending'" in q and "B1" in a for q, a in
               ((q, str(a)) for q, a in conn.executed))
    assert any(k["action"] == "live_reconcile_adopted" for k in _rec["audit"])
    assert clob.closed


async def test_multiple_untracked_resting_halts(monkeypatch, _rec) -> None:
    conn = _Conn(scan_rows=[_unknown_row()], tracked_rows=[],
                 market_row={"yes_token_id": "TOK", "no_token_id": "TOKNO"})
    pool = _wire_pool(monkeypatch, conn)
    clob = _Clob(open_orders=[{"asset_id": "TOK", "orderID": "B1"},
                              {"asset_id": "TOK", "orderID": "B2"}])
    res = await lr.reconcile_live_orders(
        pool=pool, clob_factory=lambda s: clob, settings=_settings())
    assert res["halted"] == 1
    assert _rec["kill"], "kill switch must engage on ambiguous untracked exposure"


async def test_tracked_resting_is_ignored_pages(monkeypatch, _rec) -> None:
    # The only resting order on the token is already tracked -> no orphan ->
    # falls through to the no-resting "verify on exchange" page.
    conn = _Conn(scan_rows=[_unknown_row()], tracked_rows=[{"polymarket_order_id": "B1"}],
                 market_row={"yes_token_id": "TOK", "no_token_id": "TOKNO"})
    pool = _wire_pool(monkeypatch, conn)
    clob = _Clob(open_orders=[{"asset_id": "TOK", "orderID": "B1"}])
    res = await lr.reconcile_live_orders(
        pool=pool, clob_factory=lambda s: clob, settings=_settings())
    assert res["paged"] == 1 and res["adopted"] == 0
    assert any("reconcile_paged" in str(a) for _q, a in conn.executed)


async def test_no_resting_order_pages_once(monkeypatch, _rec) -> None:
    conn = _Conn(scan_rows=[_unknown_row()], tracked_rows=[],
                 market_row={"yes_token_id": "TOK", "no_token_id": "TOKNO"})
    pool = _wire_pool(monkeypatch, conn)
    clob = _Clob(open_orders=[])
    res = await lr.reconcile_live_orders(
        pool=pool, clob_factory=lambda s: clob, settings=_settings())
    assert res["paged"] == 1
    assert _rec["page"]


async def test_broker_query_failure_pages_error(monkeypatch, _rec) -> None:
    conn = _Conn(scan_rows=[_unknown_row()], tracked_rows=[],
                 market_row={"yes_token_id": "TOK", "no_token_id": "TOKNO"})
    pool = _wire_pool(monkeypatch, conn)
    clob = _Clob(raise_open=True)
    res = await lr.reconcile_live_orders(
        pool=pool, clob_factory=lambda s: clob, settings=_settings())
    assert res["error"] == 1
    assert _rec["page"]


# --- reconcile_closing_positions ----------------------------------------------
async def test_closing_filled_finalizes_and_credits(monkeypatch, _rec) -> None:
    row = _closing_row()
    conn = _Conn(closing_rows=[row], finalize_id=row["id"])
    pool = _wire_pool(monkeypatch, conn)
    clob = _Clob(order={"status": "matched"}, fills=[{"size": "100", "price": "0.55"}])
    res = await lr.reconcile_closing_positions(
        pool=pool, clob_factory=lambda s: clob, settings=_settings())
    assert res["closed"] == 1
    # proceeds = 100 * 0.55 = 55.0 credited (float-roundtrip tolerant)
    assert _rec["credit"] and round(float(_rec["credit"][0][1]), 6) == 55.0
    assert any(k["action"] == "live_reconcile_closed" for k in _rec["audit"])


async def test_closing_killed_rolls_back(monkeypatch, _rec) -> None:
    conn = _Conn(closing_rows=[_closing_row()])
    pool = _wire_pool(monkeypatch, conn)
    clob = _Clob(order={"status": "unmatched"}, fills=[])
    res = await lr.reconcile_closing_positions(
        pool=pool, clob_factory=lambda s: clob, settings=_settings())
    assert res["rolled_back"] == 1
    assert any("status='open'" in q for q, _a in conn.executed)
    assert not _rec["credit"]


async def test_closing_non_terminal_stays_pending(monkeypatch, _rec) -> None:
    conn = _Conn(closing_rows=[_closing_row()])
    pool = _wire_pool(monkeypatch, conn)
    clob = _Clob(order={"status": "delayed"}, fills=[])
    res = await lr.reconcile_closing_positions(
        pool=pool, clob_factory=lambda s: clob, settings=_settings())
    assert res["pending"] == 1
    assert _rec["page"]


async def test_closing_without_order_id_pages(monkeypatch, _rec) -> None:
    conn = _Conn(closing_rows=[_closing_row(close_order_id=None)])
    pool = _wire_pool(monkeypatch, conn)
    clob = _Clob()
    res = await lr.reconcile_closing_positions(
        pool=pool, clob_factory=lambda s: clob, settings=_settings())
    assert res["paged_no_id"] == 1
    assert _rec["page"] and not _rec["credit"]


async def test_closing_query_failure_pages_error(monkeypatch, _rec) -> None:
    conn = _Conn(closing_rows=[_closing_row()])
    pool = _wire_pool(monkeypatch, conn)
    clob = _Clob(raise_get=True)
    res = await lr.reconcile_closing_positions(
        pool=pool, clob_factory=lambda s: clob, settings=_settings())
    assert res["error"] == 1
    assert _rec["page"]
