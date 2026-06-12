"""Regression tests for self-serve PAPER -> LIVE mode semantics."""
from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from projects.polymarket.crusaderbot.domain.activation import live_mode


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Conn:
    def __init__(self, *, before_mode: str = "paper", live_balance: Decimal = Decimal("0")):
        self.before_mode = before_mode
        self.live_balance = live_balance
        self.executed: list[tuple[str, tuple]] = []

    def transaction(self):
        return _Tx()

    async def fetchval(self, sql: str, *args):
        if "SELECT trading_mode FROM user_settings" in sql:
            return self.before_mode
        if "SUM(l.amount_usdc)" in sql:
            return self.live_balance
        return None

    async def execute(self, sql: str, *args):
        self.executed.append((sql, args))
        if "UPDATE positions" in sql:
            return "UPDATE 2"
        if "UPDATE orders" in sql:
            return "UPDATE 3"
        return "UPDATE 1"


def test_min_live_autotrade_balance_is_exactly_five():
    assert live_mode.has_min_live_autotrade_balance(Decimal("4.99")) is False
    assert live_mode.has_min_live_autotrade_balance(Decimal("5.00")) is True
    assert live_mode.has_min_live_autotrade_balance(Decimal("5.01")) is True


def test_enable_live_self_serve_forces_autotrade_off_and_archives_paper_state():
    uid = uuid4()
    conn = _Conn(live_balance=Decimal("0"))

    result = asyncio.run(live_mode.enable_live_self_serve(uid, conn=conn))

    assert result.trading_mode == "live"
    assert result.auto_trade_on is False
    assert result.waiting_for_deposit is True
    assert result.archived_positions == 2
    assert result.archived_orders == 3
    sql = "\n".join(q for q, _ in conn.executed)
    assert "trading_mode = 'live'" in sql
    assert "paper_mode_override = FALSE" in sql
    assert "auto_trade_on = FALSE" in sql
    assert "mode = $2" in sql
    assert live_mode.PAPER_ARCHIVED_MODE in [arg for _, args in conn.executed for arg in args]
    assert "alerts_ack_at = NOW()" in sql


def test_enable_live_self_serve_exact_five_is_not_waiting_for_deposit():
    uid = uuid4()
    conn = _Conn(live_balance=Decimal("5.00"))

    result = asyncio.run(live_mode.enable_live_self_serve(uid, conn=conn))

    assert result.waiting_for_deposit is False
    assert result.live_balance_usdc == Decimal("5.00")


# ---------------- shared LIVE Auto-Trade start guard ------------------------
# evaluate_live_autotrade_start is the single decision every arming surface
# (WebTrader /autotrade/toggle, Telegram activation, MVP Auto-Trade) routes
# through, so the gate can never drift between surfaces.


def test_start_guard_paper_user_passes_through_without_live_checks():
    """Paper users are a no-op allow — the guard must NOT run the live
    checklist or balance read for them (existing paper behaviour intact)."""
    uid = uuid4()
    with patch.object(live_mode.live_checklist, "evaluate",
                      AsyncMock()) as eva, \
         patch.object(live_mode, "live_autotrade_balance_status",
                      AsyncMock()) as bal:
        gate = asyncio.run(
            live_mode.evaluate_live_autotrade_start(uid, trading_mode="paper"),
        )
    assert gate.allowed is True
    assert gate.is_live is False
    assert gate.reason == ""
    eva.assert_not_awaited()
    bal.assert_not_awaited()


def test_start_guard_live_checklist_failure_blocks_with_priority():
    """A failing checklist blocks and takes precedence over funding so the
    user fixes operator/strategy gates before being told to deposit."""
    uid = uuid4()
    failing = SimpleNamespace(ready_for_live=False)
    with patch.object(live_mode.live_checklist, "evaluate",
                      AsyncMock(return_value=failing)), \
         patch.object(live_mode, "live_autotrade_balance_status",
                      AsyncMock(return_value=(Decimal("0"), False))):
        gate = asyncio.run(
            live_mode.evaluate_live_autotrade_start(uid, trading_mode="live"),
        )
    assert gate.allowed is False
    assert gate.reason == live_mode.REASON_LIVE_NOT_READY
    assert gate.checklist is failing


def test_start_guard_live_ready_but_underfunded_blocks_no_funds():
    """Checklist ready but < $5 confirmed available → live_no_funds."""
    uid = uuid4()
    passing = SimpleNamespace(ready_for_live=True)
    with patch.object(live_mode.live_checklist, "evaluate",
                      AsyncMock(return_value=passing)), \
         patch.object(live_mode, "live_autotrade_balance_status",
                      AsyncMock(return_value=(Decimal("4.99"), False))):
        gate = asyncio.run(
            live_mode.evaluate_live_autotrade_start(uid, trading_mode="live"),
        )
    assert gate.allowed is False
    assert gate.reason == live_mode.REASON_LIVE_NO_FUNDS
    assert gate.live_balance_usdc == Decimal("4.99")


def test_start_guard_live_ready_and_funded_allows():
    """Checklist ready AND >= $5 confirmed available → allowed."""
    uid = uuid4()
    passing = SimpleNamespace(ready_for_live=True)
    with patch.object(live_mode.live_checklist, "evaluate",
                      AsyncMock(return_value=passing)), \
         patch.object(live_mode, "live_autotrade_balance_status",
                      AsyncMock(return_value=(Decimal("5.00"), True))):
        gate = asyncio.run(
            live_mode.evaluate_live_autotrade_start(uid, trading_mode="live"),
        )
    assert gate.allowed is True
    assert gate.reason == ""
    assert gate.checklist_ready is True


def test_start_guard_reads_trading_mode_when_not_supplied():
    """When the caller does not pre-resolve the mode (WebTrader path), the
    guard reads trading_mode itself off the supplied connection."""
    uid = uuid4()
    conn = _Conn(before_mode="paper")
    gate = asyncio.run(
        live_mode.evaluate_live_autotrade_start(uid, conn=conn),
    )
    assert gate.is_live is False
    assert gate.allowed is True
