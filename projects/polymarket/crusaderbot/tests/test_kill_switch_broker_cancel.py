"""WARP-74 Chunk B — kill switch must broker-cancel resting orders.

Pins the false-safety fix: the kill switch now calls
``client.cancel_all_orders()`` on the exchange in addition to the DB-cancel
cascade, and a FAILED broker cancel pages the operator instead of reporting a
clean halt while resting GTC orders stay live.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from projects.polymarket.crusaderbot.domain.risk import kill_switch_exec as kse

pytestmark = pytest.mark.asyncio

_CLOB_FACTORY = "projects.polymarket.crusaderbot.integrations.clob.get_clob_client"
_NOTIFY = "projects.polymarket.crusaderbot.notifications.notify_operator"


class _Clob:
    def __init__(self, *, raise_cancel: bool = False) -> None:
        self.raise_cancel = raise_cancel
        self.cancel_called = False
        self.closed = False

    async def cancel_all_orders(self, market: str | None = None) -> dict:
        self.cancel_called = True
        if self.raise_cancel:
            raise RuntimeError("broker 503")
        return {"canceled": ["A", "B"]}

    async def aclose(self) -> None:
        self.closed = True


# --- _broker_cancel_all_orders ------------------------------------------------
async def test_broker_cancel_paper_is_noop(monkeypatch) -> None:
    monkeypatch.setattr(kse, "get_settings",
                        lambda: SimpleNamespace(USE_REAL_CLOB=False))
    res = await kse._broker_cancel_all_orders()
    assert res["attempted"] is False and res["skipped_paper"] is True


async def test_broker_cancel_live_ok(monkeypatch) -> None:
    clob = _Clob()
    monkeypatch.setattr(kse, "get_settings",
                        lambda: SimpleNamespace(USE_REAL_CLOB=True))
    monkeypatch.setattr(_CLOB_FACTORY, lambda s: clob)
    res = await kse._broker_cancel_all_orders()
    assert res["attempted"] is True and res["cancelled"] is True
    assert clob.cancel_called and clob.closed


async def test_broker_cancel_failure_is_contained(monkeypatch) -> None:
    clob = _Clob(raise_cancel=True)
    monkeypatch.setattr(kse, "get_settings",
                        lambda: SimpleNamespace(USE_REAL_CLOB=True))
    monkeypatch.setattr(_CLOB_FACTORY, lambda s: clob)
    res = await kse._broker_cancel_all_orders()
    assert res["attempted"] is True and res["cancelled"] is False
    assert "error" in res and clob.closed  # client still cleaned up


# --- execute_kill_switch integration ------------------------------------------
def _stub_kill_path(monkeypatch, broker_result: dict) -> dict:
    rec: dict[str, Any] = {"notify": []}

    async def _noop(*_a: Any, **_k: Any) -> None:
        return None

    async def _broker() -> dict:
        return broker_result

    async def _cancel_pending() -> int:
        return 0

    async def _notify(text: str, *_a: Any, **_k: Any) -> None:
        rec["notify"].append(text)

    monkeypatch.setattr(kse.ops_kill_switch, "set_active", _noop)
    monkeypatch.setattr(kse, "_broker_cancel_all_orders", _broker)
    monkeypatch.setattr(kse, "_cancel_pending_orders", _cancel_pending)
    monkeypatch.setattr(kse, "_set_system_flag", _noop)
    monkeypatch.setattr(kse, "_write_audit_log", _noop)
    monkeypatch.setattr(_NOTIFY, _notify)
    return rec


async def test_execute_kill_switch_invokes_broker_cancel(monkeypatch) -> None:
    rec = _stub_kill_path(monkeypatch, {"attempted": True, "cancelled": True})
    await kse.execute_kill_switch(reason="test", triggered_by="op")
    assert rec["notify"], "operator must be notified"
    assert "BROKER CANCEL FAILED" not in rec["notify"][0]


async def test_failed_broker_cancel_warns_operator(monkeypatch) -> None:
    rec = _stub_kill_path(monkeypatch, {"attempted": True, "cancelled": False})
    await kse.execute_kill_switch(reason="test", triggered_by="op")
    assert rec["notify"] and "BROKER CANCEL FAILED" in rec["notify"][0]
