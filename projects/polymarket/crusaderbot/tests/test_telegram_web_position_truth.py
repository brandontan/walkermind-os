"""Behaviour pins for #1820 — telegram-trade-opened-not-visible-in-web-position.

Owner production evidence: Telegram showed `TRADE OPENED` for a Bitcoin Up/Down
NO position, $0.03 size, $0.18 entry, Late Entry strategy — but the LIVE
WebTrader Portfolio showed no open position.

R00T root cause: the user is in ``trading_mode='live'`` with a tiny balance.
A ``late_entry_v3`` candidate sizes to ~$0.03; ``live.execute`` rejects it
pre-submit at the ``LIVE_MIN_ORDER_SHARES=5`` floor (0.03/0.18 = 0.167 shares),
so the router falls back to paper. ``paper.execute`` then fires a
``TRADE OPENED`` notification for a ``mode='paper'`` position that the LIVE
WebTrader portfolio query (``WHERE mode = 'live'``) filters out — Telegram and
WebTrader disagree on runtime truth.

Fix (symmetric with the #1810 exit-path mode-isolation guard): when the paper
entry fires for a user whose authoritative mode is LIVE, suppress the TRADE
OPENED notification AND the downstream ``position.opened`` event (which drives
the WebTrader SSE + notification_service). The paper position itself is
unchanged — it remains valid paper accounting; it just must not masquerade as
an active live trade the live portfolio can't show.

Hermetic: fake pool/conn, mocked notifier/audit/ledger, patched
``get_active_trading_mode``. No DB, no network, no CLOB.
"""
from __future__ import annotations

import asyncio
import inspect
import pathlib
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from projects.polymarket.crusaderbot.domain.execution import paper as paper_engine

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_PAPER = "projects.polymarket.crusaderbot.domain.execution.paper"

ORDER_ID = UUID("11111111-1111-1111-1111-111111111111")
POSITION_ID = UUID("22222222-2222-2222-2222-222222222222")


def _run(coro):
    return asyncio.run(coro)


class _Tx:
    async def __aenter__(self): return self
    async def __aexit__(self, *exc): return False


class FakeConn:
    async def fetchrow(self, sql: str, *args):
        if "INSERT INTO orders" in sql:
            return {"id": ORDER_ID}
        if "INSERT INTO positions" in sql:
            return {"id": POSITION_ID}
        return None

    async def fetchval(self, sql: str, *args):
        return None

    async def execute(self, sql: str, *args) -> str:
        return "OK"

    def transaction(self) -> _Tx:
        return _Tx()


class _Acq:
    def __init__(self, conn: FakeConn): self._c = conn
    async def __aenter__(self): return self._c
    async def __aexit__(self, *exc): return False


class FakePool:
    def __init__(self, conn: FakeConn): self._c = conn
    def acquire(self) -> _Acq: return _Acq(self._c)


def _run_paper_execute(*, active_mode: str, notify: Any, audit_actions: list[str]):
    async def _audit(**kw):
        audit_actions.append(kw.get("action", ""))

    async def _active(user_id, conn=None):
        return active_mode

    patches = [
        patch(f"{_PAPER}.get_pool", return_value=FakePool(FakeConn())),
        patch(f"{_PAPER}._notifier.notify_entry", new=notify),
        patch(f"{_PAPER}.audit.write", new=_audit),
        patch(f"{_PAPER}.ledger.debit_in_conn", new=AsyncMock()),
        patch(
            "projects.polymarket.crusaderbot.domain.activation."
            "live_mode.get_active_trading_mode",
            new=_active,
        ),
    ]
    for p in patches:
        p.start()
    try:
        return _run(paper_engine.execute(
            user_id=uuid4(),
            telegram_user_id=12345,
            market_id="BTC-UPDOWN-JUN13",
            market_question="Bitcoin Up or Down - June 13?",
            side="no",
            size_usdc=Decimal("0.03"),
            price=0.18,
            idempotency_key="key-1820",
            strategy_type="late_entry_v3",
            tp_pct=None,
            sl_pct=None,
        ))
    finally:
        for p in patches:
            p.stop()


# ---------------------------------------------------------------------------
# 1. Paper entry for a now-LIVE user is suppressed.
# ---------------------------------------------------------------------------

def test_paper_entry_suppressed_when_user_is_live() -> None:
    notified: list[dict] = []
    audit_actions: list[str] = []

    async def _notify(**kw):
        notified.append(kw)

    result = _run_paper_execute(
        active_mode="live", notify=_notify, audit_actions=audit_actions,
    )

    # The TRADE OPENED notification did NOT fire ...
    assert notified == []
    # ... the open event is flagged suppressed for the engine ...
    assert result["open_event_suppressed"] is True
    # ... and a diagnostic audit row was written.
    assert "paper_entry_suppressed_post_live" in audit_actions
    # The paper position itself still exists (valid paper accounting).
    assert result["position_id"] == POSITION_ID
    assert result["mode"] == "paper"


def test_paper_entry_notifies_when_user_is_paper() -> None:
    """Control: a genuine paper user still gets the TRADE OPENED card."""
    notified: list[dict] = []
    audit_actions: list[str] = []

    async def _notify(**kw):
        notified.append(kw)

    result = _run_paper_execute(
        active_mode="paper", notify=_notify, audit_actions=audit_actions,
    )

    assert len(notified) == 1
    assert notified[0]["mode"] == "paper"
    assert result["open_event_suppressed"] is False
    assert "paper_entry_suppressed_post_live" not in audit_actions


def test_paper_entry_fail_open_on_mode_read_error() -> None:
    """Defense-in-depth: if the authoritative mode read raises, the entry
    notification STILL fires (fail open) — a transient DB error must never
    silently swallow a legitimate paper user's TRADE OPENED."""
    notified: list[dict] = []

    async def _notify(**kw):
        notified.append(kw)

    async def _raising_active(user_id, conn=None):
        raise RuntimeError("user_settings read offline")

    patches = [
        patch(f"{_PAPER}.get_pool", return_value=FakePool(FakeConn())),
        patch(f"{_PAPER}._notifier.notify_entry", new=_notify),
        patch(f"{_PAPER}.audit.write", new=AsyncMock()),
        patch(f"{_PAPER}.ledger.debit_in_conn", new=AsyncMock()),
        patch(
            "projects.polymarket.crusaderbot.domain.activation."
            "live_mode.get_active_trading_mode",
            new=_raising_active,
        ),
    ]
    for p in patches:
        p.start()
    try:
        result = _run(paper_engine.execute(
            user_id=uuid4(), telegram_user_id=1, market_id="m",
            market_question="q", side="yes", size_usdc=Decimal("5"),
            price=0.5, idempotency_key="k", strategy_type="late_entry_v3",
            tp_pct=None, sl_pct=None,
        ))
    finally:
        for p in patches:
            p.stop()

    assert len(notified) == 1
    assert result["open_event_suppressed"] is False


# ---------------------------------------------------------------------------
# 2. Engine skips position.opened when the paper engine suppressed the entry.
# ---------------------------------------------------------------------------

def test_engine_skips_position_opened_when_suppressed() -> None:
    """The position.opened event drives the WebTrader SSE + notification_service.
    When the paper engine flags ``open_event_suppressed`` (paper fallback for a
    now-LIVE user), the engine must NOT emit it — otherwise the live WebTrader
    session would receive an opened-position event the portfolio query can never
    surface. Source-pin the gating condition."""
    src = inspect.getsource(
        __import__(
            "projects.polymarket.crusaderbot.services.trade_engine.engine",
            fromlist=["x"],
        )
    )
    assert "open_event_suppressed" in src
    # The position.opened emit is gated on NOT suppressed.
    assert "not _open_event_suppressed" in src
    assert 'raw.get("open_event_suppressed")' in src


# ---------------------------------------------------------------------------
# 3. Source-pin: the guard reuses the #1810 helpers and is symmetric.
# ---------------------------------------------------------------------------

def test_paper_entry_guard_reuses_1810_helpers() -> None:
    src = inspect.getsource(paper_engine.execute)
    # Reuses the authoritative single-source-of-truth helpers from #1810.
    assert "get_active_trading_mode" in src
    assert "paper_event_contaminates_live" in src
    # event_mode is hardcoded paper (this engine only ever creates paper rows).
    assert 'event_mode="paper"' in src
    # Suppression is auditable, not silent.
    assert "paper_entry_suppressed_post_live" in src
    # Fail-open posture is explicit.
    assert "Fail OPEN" in src or "fail open" in src.lower()


def test_paper_position_row_unchanged_by_guard() -> None:
    """The guard must never alter the paper position write itself — it only
    gates the user-facing notification + open event. The INSERT INTO positions
    stays mode='paper','open' and the ledger debit stays inside the txn."""
    src = inspect.getsource(paper_engine.execute)
    assert "INSERT INTO positions" in src
    assert "'paper','open'" in src
    assert "debit_in_conn(" in src
    # The suppression branch is AFTER the committed transaction + audit, never
    # inside the position-write transaction.
    insert_idx = src.index("INSERT INTO positions")
    guard_idx = src.index("paper_event_contaminates_live")
    assert guard_idx > insert_idx
