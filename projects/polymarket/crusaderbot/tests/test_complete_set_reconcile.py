"""Lane 3C-2 — complete-set crash-recovery reconciler (set-aware).

Tests the DECISION routing of reconcile_complete_set_orders against broker truth:
confirmed non-fill -> cancel; confirmed fill -> persist tracked naked + halt;
unverifiable / ambiguous -> halt. Never refunds, never silently deletes. The DB
persistence internals are covered by the booker suite; here the persist/halt/mark
helpers are recorded so we assert the routing, hermetically.
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from projects.polymarket.crusaderbot.domain.execution import complete_set_exec as cse
from projects.polymarket.crusaderbot.domain.execution import lifecycle

pytestmark = pytest.mark.asyncio


# --- fakes --------------------------------------------------------------------
class _Conn:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    async def fetch(self, _q: str, *_a: Any) -> list[dict]:
        return self._rows


class _Acquire:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _Conn:
        return self._conn

    async def __aexit__(self, *_a: Any) -> bool:
        return False


class _Pool:
    def __init__(self, rows: list[dict]) -> None:
        self._conn = _Conn(rows)

    def acquire(self) -> _Acquire:
        return _Acquire(self._conn)


class _Clob:
    def __init__(self, order: dict | None = None, fills: list[dict] | None = None) -> None:
        self._order = order or {"status": "not_found"}
        self._fills = fills or []
        self.closed = False

    async def get_order(self, _oid: str) -> dict:
        return self._order

    async def get_fills(self, _oid: str) -> list[dict]:
        return list(self._fills)

    async def aclose(self) -> None:
        self.closed = True


def _row(**over: Any) -> dict:
    base = {
        "id": uuid4(), "user_id": uuid4(), "market_id": "m1", "side": "yes",
        "size_usdc": 45.0, "price": 0.45, "polymarket_order_id": "ord-x",
        "status": "pending", "strategy_type": "complete_set_arb",
    }
    base.update(over)
    return base


def _live_settings(**over: Any) -> SimpleNamespace:
    base = dict(USE_REAL_CLOB=True, COMPLETE_SET_RECONCILE_STALE_SEC=300)
    base.update(over)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _record(monkeypatch):
    rec = {"mark": [], "persist": [], "halt": []}

    async def _mark(order_id, status, *, broker_id="", error=""):
        rec["mark"].append((order_id, status, broker_id))

    async def _persist(**kw):
        rec["persist"].append(kw)
        return {"status": "naked_halt"}

    async def _halt(**kw):
        rec["halt"].append(kw)

    monkeypatch.setattr(cse, "_mark_order", _mark)
    monkeypatch.setattr(cse, "_persist_naked_halt", _persist)
    monkeypatch.setattr(cse, "_halt_and_alert", _halt)
    return rec


# --- tests --------------------------------------------------------------------
async def test_noop_in_paper_mode() -> None:
    res = await cse.reconcile_complete_set_orders(
        pool=_Pool([_row()]), clob_factory=lambda s: _Clob(),
        settings=_live_settings(USE_REAL_CLOB=False),
    )
    assert res == {"scanned": 0, "skipped_paper": True}


async def test_no_stale_rows_is_noop(_record) -> None:
    res = await cse.reconcile_complete_set_orders(
        pool=_Pool([]), clob_factory=lambda s: _Clob(), settings=_live_settings(),
    )
    assert res["scanned"] == 0 and res["errors"] == 0
    assert _record["halt"] == [] and _record["persist"] == []


async def test_confirmed_not_filled_marks_cancelled(_record) -> None:
    clob = _Clob(order={"status": "unmatched"}, fills=[])
    res = await cse.reconcile_complete_set_orders(
        pool=_Pool([_row()]), clob_factory=lambda s: clob, settings=_live_settings(),
    )
    assert res["cancelled"] == 1 and res["naked_halt"] == 0 and res["halted"] == 0
    assert _record["mark"] and _record["mark"][0][1] == "cancelled"
    assert _record["halt"] == []
    assert clob.closed  # client cleaned up


async def test_confirmed_fill_persists_naked_and_halts(_record) -> None:
    clob = _Clob(order={"status": "matched"}, fills=[{"size": "100", "price": "0.46"}])
    res = await cse.reconcile_complete_set_orders(
        pool=_Pool([_row()]), clob_factory=lambda s: clob, settings=_live_settings(),
    )
    assert res["naked_halt"] == 1
    assert _record["persist"] and _record["persist"][0]["reason"] == "reconcile_untracked_fill"
    # exact fill cost booked (0.46 * 100 = 46.0), not the 45.0 order estimate
    assert float(_record["persist"][0]["naked_cost"]) == 46.0


async def test_no_broker_id_halts_unverifiable(_record) -> None:
    res = await cse.reconcile_complete_set_orders(
        pool=_Pool([_row(polymarket_order_id="")]),
        clob_factory=lambda s: _Clob(), settings=_live_settings(),
    )
    assert res["halted"] == 1
    assert _record["halt"] and "unverifiable" in _record["halt"][0]["reason"]
    assert _record["mark"] == [] and _record["persist"] == []


async def test_still_ambiguous_halts(_record) -> None:
    clob = _Clob(order={"status": "delayed"}, fills=[])
    res = await cse.reconcile_complete_set_orders(
        pool=_Pool([_row(status="unknown")]),
        clob_factory=lambda s: clob, settings=_live_settings(),
    )
    assert res["halted"] == 1
    assert _record["halt"] and "ambiguous" in _record["halt"][0]["reason"]


async def test_lifecycle_excludes_complete_set_in_sql() -> None:
    # The directional poller must NEVER select a complete-set leg (its refund-on-
    # cancel logic would break the hedge); the exclusion is pinned in the SQL.
    src = inspect.getsource(lifecycle.OrderLifecycleManager.poll_once)
    assert "complete_set_arb%" in src and "NOT LIKE" in src
