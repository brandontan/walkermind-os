"""Hermetic tests for WebTrader positions: awaiting_redeem + force-redeem.

The route functions are plain async callables, so we invoke them directly with
a fake asyncpg pool (no FastAPI/DB/network).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from projects.polymarket.crusaderbot.webtrader.backend import router as web_router


def _run(coro):
    return asyncio.run(coro)


class _Conn:
    def __init__(self, *, rows=None, row=None):
        self._rows = rows or []
        self._row = row

    async def fetch(self, *a, **k):
        return self._rows

    async def fetchrow(self, *a, **k):
        return self._row

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None


class _Pool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return self._conn


def _pos_row(*, status="open", side="yes", resolved=False, winning_side=None):
    return {
        "id": "11111111-1111-1111-1111-111111111111",
        "market_id": "mkt-1",
        "market_question": "BTC up or down?",
        "side": side,
        "size_usdc": 5.0,
        "entry_price": 0.55,
        "current_price": 0.57,
        "pnl_usdc": 0.1,
        "status": status,
        "mode": "paper",
        "opened_at": datetime.now(timezone.utc),
        "closed_at": None,
        "exit_reason": None,
        "market_resolved": resolved,
        "winning_side": winning_side,
        "tp_pct": 0.15,
        "sl_pct": 0.08,
        "strategy_type": "late_entry_v3",
        "active_preset": None,
    }


_USER = {"user_id": "22222222-2222-2222-2222-222222222222", "telegram_id": 1}


# ── awaiting_redeem derivation ────────────────────────────────────────────────


def test_awaiting_redeem_true_when_open_resolved_winner():
    conn = _Conn(rows=[_pos_row(status="open", side="yes", resolved=True, winning_side="yes")])
    with patch.object(web_router, "get_pool", return_value=_Pool(conn)):
        out = _run(web_router.get_positions(_USER, status="open"))
    assert out[0].awaiting_redeem is True


def test_awaiting_redeem_false_when_loser():
    conn = _Conn(rows=[_pos_row(status="open", side="no", resolved=True, winning_side="yes")])
    with patch.object(web_router, "get_pool", return_value=_Pool(conn)):
        out = _run(web_router.get_positions(_USER, status="open"))
    assert out[0].awaiting_redeem is False


def test_awaiting_redeem_false_when_unresolved():
    conn = _Conn(rows=[_pos_row(status="open", side="yes", resolved=False, winning_side=None)])
    with patch.object(web_router, "get_pool", return_value=_Pool(conn)):
        out = _run(web_router.get_positions(_USER, status="open"))
    assert out[0].awaiting_redeem is False


# ── force-redeem endpoint ─────────────────────────────────────────────────────


def test_force_redeem_runs_instant_worker_when_pending():
    conn = _Conn(row={"queue_id": "33333333-3333-3333-3333-333333333333"})
    proc = AsyncMock()
    with patch.object(web_router, "get_pool", return_value=_Pool(conn)), \
         patch("projects.polymarket.crusaderbot.services.redeem.instant_worker.try_process", new=proc):
        resp = _run(web_router.force_redeem_position("pos-1", _USER))
    proc.assert_awaited_once_with("33333333-3333-3333-3333-333333333333")
    assert resp.status_code == 200


def test_force_redeem_409_when_no_pending_row():
    from fastapi import HTTPException
    conn = _Conn(row=None)
    proc = AsyncMock()
    with patch.object(web_router, "get_pool", return_value=_Pool(conn)), \
         patch("projects.polymarket.crusaderbot.services.redeem.instant_worker.try_process", new=proc):
        with pytest.raises(HTTPException) as ei:
            _run(web_router.force_redeem_position("pos-1", _USER))
    assert ei.value.status_code == 409
    proc.assert_not_called()
