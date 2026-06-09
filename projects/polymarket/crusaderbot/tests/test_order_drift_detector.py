"""WARP-74 Chunk C — broker<->DB open-order drift detector tests (alert-only)."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from projects.polymarket.crusaderbot.domain.execution import drift_detector as dd

pytestmark = pytest.mark.asyncio

_NOTIFY = "projects.polymarket.crusaderbot.notifications.notify_operator"
_AUDIT = "projects.polymarket.crusaderbot.audit.write"


class _Conn:
    def __init__(self, db_ids: list[str]) -> None:
        self._rows = [{"polymarket_order_id": i} for i in db_ids]

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
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    def acquire(self) -> _Acquire:
        return _Acquire(self._conn)


class _Clob:
    def __init__(self, broker_ids: list[str], *, raise_query: bool = False) -> None:
        self._ids = broker_ids
        self.raise_query = raise_query
        self.closed = False

    async def get_open_orders(self, market: str | None = None) -> list[dict]:
        if self.raise_query:
            raise RuntimeError("broker down")
        return [{"orderID": i} for i in self._ids]

    async def aclose(self) -> None:
        self.closed = True


def _settings(**over: Any) -> SimpleNamespace:
    base = dict(USE_REAL_CLOB=True, ORDER_DRIFT_DETECT_ENABLED=True)
    base.update(over)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _rec(monkeypatch):
    rec = {"page": [], "audit": []}

    async def _page(text, *_a, **_k):
        rec["page"].append(text)

    async def _audit(**kw):
        rec["audit"].append(kw)

    monkeypatch.setattr(_NOTIFY, _page)
    monkeypatch.setattr(_AUDIT, _audit)
    return rec


async def test_paper_noop() -> None:
    res = await dd.detect_order_drift(
        pool=_Pool(_Conn([])), clob_factory=lambda s: _Clob([]),
        settings=_settings(USE_REAL_CLOB=False))
    assert res == {"checked": False, "skipped_paper": True}


async def test_disabled_noop() -> None:
    res = await dd.detect_order_drift(
        pool=_Pool(_Conn([])), clob_factory=lambda s: _Clob([]),
        settings=_settings(ORDER_DRIFT_DETECT_ENABLED=False))
    assert res == {"checked": False, "skipped_disabled": True}


async def test_clean_no_drift_no_page(_rec) -> None:
    clob = _Clob(["A", "B"])
    res = await dd.detect_order_drift(
        pool=_Pool(_Conn(["A", "B"])), clob_factory=lambda s: clob,
        settings=_settings())
    assert res["checked"] and res["broker_only"] == 0 and res["db_only"] == 0
    assert not _rec["page"] and clob.closed


async def test_broker_only_drift_pages(_rec) -> None:
    # 'X' rests on the exchange but is untracked in DB -> orphan exposure.
    clob = _Clob(["A", "X"])
    res = await dd.detect_order_drift(
        pool=_Pool(_Conn(["A"])), clob_factory=lambda s: clob, settings=_settings())
    assert res["broker_only"] == 1
    assert _rec["page"] and "ORDER DRIFT" in _rec["page"][0]
    assert any(k["action"] == "order_drift_detected" for k in _rec["audit"])


async def test_db_only_drift_pages(_rec) -> None:
    clob = _Clob(["A"])
    res = await dd.detect_order_drift(
        pool=_Pool(_Conn(["A", "Z"])), clob_factory=lambda s: clob, settings=_settings())
    assert res["db_only"] == 1 and _rec["page"]


async def test_broker_query_failure_is_contained(_rec) -> None:
    clob = _Clob([], raise_query=True)
    res = await dd.detect_order_drift(
        pool=_Pool(_Conn(["A"])), clob_factory=lambda s: clob, settings=_settings())
    assert res["checked"] is False and "error" in res
    assert clob.closed and not _rec["page"]
