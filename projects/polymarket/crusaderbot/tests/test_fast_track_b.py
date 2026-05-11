"""Hermetic tests for Fast Track B — CopyTradeMonitor copy-trade execution.

Coverage (25 test cases, 13 async + 12 pure helpers):
  TC01  signal accepted end-to-end
  TC02  signal rejected — min_trade_size constraint
  TC03  signal rejected — daily max_spend cap reached
  TC04  signal rejected — idempotency (already processed)
  TC05  signal rejected — risk gate rejects
  TC06  idempotency row persisted after successful approval
  TC07  spend recorded after approval with correct args
  TC08  rejected — unknown side in leader trade
  TC09  reverse_copy flips side buy→no
  TC10  copy_size below MIN_TRADE_SIZE after spend cap
  TC11  kill switch active — tick exits; list_active_tasks NOT called
  TC12  no active tasks — tick is a no-op
  TC13  wallet API raises — no exception propagated

  Pure helpers:
    extract_trade_id from id field
    extract_trade_id content-hash fallback
    extract_trade_id returns None on empty dict
    resolve_side buy→yes
    resolve_side sell→no
    resolve_side reverse buy→no
    resolve_side reverse sell→yes
    resolve_side outcome overrides buy/sell
    resolve_side outcome + reverse_copy
    make_idempotency_key format
    compute_copy_size fixed mode
    compute_copy_size proportional mirror fallback + copy_pct

No DB, no broker, no Telegram. All external calls patched.
"""
from __future__ import annotations

import datetime as _dt
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from projects.polymarket.crusaderbot.domain.copy_trade.models import CopyTradeTask
from projects.polymarket.crusaderbot.services.copy_trade import monitor as ct_monitor
from projects.polymarket.crusaderbot.services.copy_trade.monitor import (
    _compute_copy_size,
    _extract_trade_id,
    _make_idempotency_key,
    _resolve_side,
)
from projects.polymarket.crusaderbot.services.trade_engine import TradeResult


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _task(
    *,
    copy_mode: str = "fixed",
    copy_amount: str = "10.00",
    min_trade_size: str = "1.00",
    max_daily_spend: str = "100.00",
    reverse_copy: bool = False,
    wallet_address: str = "0xLeaderWallet",
) -> CopyTradeTask:
    now = _dt.datetime.utcnow()
    return CopyTradeTask(
        id=uuid4(),
        user_id=uuid4(),
        wallet_address=wallet_address,
        task_name="test",
        status="active",
        copy_mode=copy_mode,
        copy_amount=Decimal(copy_amount),
        copy_pct=None,
        tp_pct=Decimal("0.20"),
        sl_pct=Decimal("0.10"),
        max_daily_spend=Decimal(max_daily_spend),
        slippage_pct=Decimal("0.05"),
        min_trade_size=Decimal(min_trade_size),
        reverse_copy=reverse_copy,
        created_at=now,
        updated_at=now,
    )


def _trade(
    *,
    trade_id: str = "lt_001",
    side: str = "buy",
    size: float = 20.0,
    price: float = 0.6,
    market_id: str = "mkt_abc",
) -> dict:
    return {
        "id": trade_id,
        "side": side,
        "usdcSize": size,
        "price": price,
        "market_id": market_id,
        "market_status": "active",
        "liquidity": 80_000.0,
    }


def _approved() -> TradeResult:
    return TradeResult(
        approved=True,
        mode="paper",
        order_id=uuid4(),
        position_id=uuid4(),
        rejection_reason=None,
        failed_gate_step=None,
        chosen_mode="paper",
        final_size_usdc=Decimal("10.00"),
    )


def _rejected(reason: str = "gate_step_1") -> TradeResult:
    return TradeResult(
        approved=False,
        mode=None,
        order_id=None,
        position_id=None,
        rejection_reason=reason,
        failed_gate_step=1,
        chosen_mode=None,
        final_size_usdc=None,
    )


USER_CTX: dict = {
    "telegram_user_id": 99999,
    "access_tier": 3,
    "auto_trade_on": True,
    "paused": False,
    "risk_profile": "balanced",
    "trading_mode": "paper",
}


# ---------------------------------------------------------------------------
# TC01 — signal accepted end-to-end
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tc01_signal_accepted_end_to_end() -> None:
    task = _task()
    trade = _trade()
    m_engine = AsyncMock(return_value=_approved())
    m_mark = AsyncMock()
    m_spend = AsyncMock()

    with patch.object(ct_monitor, "kill_switch_is_active", new=AsyncMock(return_value=False)), \
         patch.object(ct_monitor, "list_active_tasks", new=AsyncMock(return_value=[task])), \
         patch.object(ct_monitor, "fetch_recent_wallet_trades", new=AsyncMock(return_value=[trade])), \
         patch.object(ct_monitor, "_is_already_processed", new=AsyncMock(return_value=False)), \
         patch.object(ct_monitor, "_get_daily_spend", new=AsyncMock(return_value=0.0)), \
         patch.object(ct_monitor, "_record_spend", new=m_spend), \
         patch.object(ct_monitor, "_mark_processed", new=m_mark), \
         patch.object(ct_monitor, "_load_user_context", new=AsyncMock(return_value=USER_CTX)), \
         patch.object(ct_monitor._engine, "execute", new=m_engine):
        await ct_monitor.run_once()

    m_engine.assert_awaited_once()
    m_mark.assert_awaited_once()
    m_spend.assert_awaited_once()


# ---------------------------------------------------------------------------
# TC02 — rejected: min_trade_size
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tc02_rejected_min_trade_size() -> None:
    task = _task(min_trade_size="50.00")
    trade = _trade(size=20.0)
    m_engine = AsyncMock(return_value=_approved())
    m_mark = AsyncMock()

    with patch.object(ct_monitor, "kill_switch_is_active", new=AsyncMock(return_value=False)), \
         patch.object(ct_monitor, "list_active_tasks", new=AsyncMock(return_value=[task])), \
         patch.object(ct_monitor, "fetch_recent_wallet_trades", new=AsyncMock(return_value=[trade])), \
         patch.object(ct_monitor, "_is_already_processed", new=AsyncMock(return_value=False)), \
         patch.object(ct_monitor, "_get_daily_spend", new=AsyncMock(return_value=0.0)), \
         patch.object(ct_monitor, "_record_spend", new=AsyncMock()), \
         patch.object(ct_monitor, "_mark_processed", new=m_mark), \
         patch.object(ct_monitor, "_load_user_context", new=AsyncMock(return_value=USER_CTX)), \
         patch.object(ct_monitor._engine, "execute", new=m_engine):
        await ct_monitor.run_once()

    m_engine.assert_not_awaited()
    m_mark.assert_not_awaited()


# ---------------------------------------------------------------------------
# TC03 — rejected: daily spend cap
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tc03_rejected_daily_spend_cap() -> None:
    task = _task(max_daily_spend="10.00")
    trade = _trade(size=5.0)
    m_engine = AsyncMock(return_value=_approved())

    with patch.object(ct_monitor, "kill_switch_is_active", new=AsyncMock(return_value=False)), \
         patch.object(ct_monitor, "list_active_tasks", new=AsyncMock(return_value=[task])), \
         patch.object(ct_monitor, "fetch_recent_wallet_trades", new=AsyncMock(return_value=[trade])), \
         patch.object(ct_monitor, "_is_already_processed", new=AsyncMock(return_value=False)), \
         patch.object(ct_monitor, "_get_daily_spend", new=AsyncMock(return_value=10.0)), \
         patch.object(ct_monitor, "_record_spend", new=AsyncMock()), \
         patch.object(ct_monitor, "_mark_processed", new=AsyncMock()), \
         patch.object(ct_monitor, "_load_user_context", new=AsyncMock(return_value=USER_CTX)), \
         patch.object(ct_monitor._engine, "execute", new=m_engine):
        await ct_monitor.run_once()

    m_engine.assert_not_awaited()


# ---------------------------------------------------------------------------
# TC04 — rejected: idempotency (already processed)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tc04_rejected_idempotency() -> None:
    task = _task()
    trade = _trade()
    m_engine = AsyncMock(return_value=_approved())
    m_mark = AsyncMock()

    with patch.object(ct_monitor, "kill_switch_is_active", new=AsyncMock(return_value=False)), \
         patch.object(ct_monitor, "list_active_tasks", new=AsyncMock(return_value=[task])), \
         patch.object(ct_monitor, "fetch_recent_wallet_trades", new=AsyncMock(return_value=[trade])), \
         patch.object(ct_monitor, "_is_already_processed", new=AsyncMock(return_value=True)), \
         patch.object(ct_monitor, "_get_daily_spend", new=AsyncMock(return_value=0.0)), \
         patch.object(ct_monitor, "_record_spend", new=AsyncMock()), \
         patch.object(ct_monitor, "_mark_processed", new=m_mark), \
         patch.object(ct_monitor, "_load_user_context", new=AsyncMock(return_value=USER_CTX)), \
         patch.object(ct_monitor._engine, "execute", new=m_engine):
        await ct_monitor.run_once()

    m_engine.assert_not_awaited()
    m_mark.assert_not_awaited()


# ---------------------------------------------------------------------------
# TC05 — rejected by risk gate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tc05_rejected_by_risk_gate() -> None:
    task = _task()
    trade = _trade()
    m_engine = AsyncMock(return_value=_rejected())
    m_mark = AsyncMock()
    m_spend = AsyncMock()

    with patch.object(ct_monitor, "kill_switch_is_active", new=AsyncMock(return_value=False)), \
         patch.object(ct_monitor, "list_active_tasks", new=AsyncMock(return_value=[task])), \
         patch.object(ct_monitor, "fetch_recent_wallet_trades", new=AsyncMock(return_value=[trade])), \
         patch.object(ct_monitor, "_is_already_processed", new=AsyncMock(return_value=False)), \
         patch.object(ct_monitor, "_get_daily_spend", new=AsyncMock(return_value=0.0)), \
         patch.object(ct_monitor, "_record_spend", new=m_spend), \
         patch.object(ct_monitor, "_mark_processed", new=m_mark), \
         patch.object(ct_monitor, "_load_user_context", new=AsyncMock(return_value=USER_CTX)), \
         patch.object(ct_monitor._engine, "execute", new=m_engine):
        await ct_monitor.run_once()

    m_engine.assert_awaited_once()
    # idempotency always marked (no re-eval on next tick)
    m_mark.assert_awaited_once()
    m_spend.assert_not_awaited()


# ---------------------------------------------------------------------------
# TC06 — idempotency row persisted with correct leader_trade_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tc06_idempotency_persisted_correct_id() -> None:
    task = _task()
    trade = _trade(trade_id="lt_unique_001")
    m_mark = AsyncMock()

    with patch.object(ct_monitor, "kill_switch_is_active", new=AsyncMock(return_value=False)), \
         patch.object(ct_monitor, "list_active_tasks", new=AsyncMock(return_value=[task])), \
         patch.object(ct_monitor, "fetch_recent_wallet_trades", new=AsyncMock(return_value=[trade])), \
         patch.object(ct_monitor, "_is_already_processed", new=AsyncMock(return_value=False)), \
         patch.object(ct_monitor, "_get_daily_spend", new=AsyncMock(return_value=0.0)), \
         patch.object(ct_monitor, "_record_spend", new=AsyncMock()), \
         patch.object(ct_monitor, "_mark_processed", new=m_mark), \
         patch.object(ct_monitor, "_load_user_context", new=AsyncMock(return_value=USER_CTX)), \
         patch.object(ct_monitor._engine, "execute", new=AsyncMock(return_value=_approved())):
        await ct_monitor.run_once()

    call_args = m_mark.call_args
    assert call_args.args[2] == "lt_unique_001"


# ---------------------------------------------------------------------------
# TC07 — spend recorded with positive amount
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tc07_spend_recorded_positive() -> None:
    task = _task()
    trade = _trade()
    m_spend = AsyncMock()

    with patch.object(ct_monitor, "kill_switch_is_active", new=AsyncMock(return_value=False)), \
         patch.object(ct_monitor, "list_active_tasks", new=AsyncMock(return_value=[task])), \
         patch.object(ct_monitor, "fetch_recent_wallet_trades", new=AsyncMock(return_value=[trade])), \
         patch.object(ct_monitor, "_is_already_processed", new=AsyncMock(return_value=False)), \
         patch.object(ct_monitor, "_get_daily_spend", new=AsyncMock(return_value=0.0)), \
         patch.object(ct_monitor, "_record_spend", new=m_spend), \
         patch.object(ct_monitor, "_mark_processed", new=AsyncMock()), \
         patch.object(ct_monitor, "_load_user_context", new=AsyncMock(return_value=USER_CTX)), \
         patch.object(ct_monitor._engine, "execute", new=AsyncMock(return_value=_approved())):
        await ct_monitor.run_once()

    m_spend.assert_awaited_once()
    assert m_spend.call_args.args[2] > 0


# ---------------------------------------------------------------------------
# TC08 — rejected: unknown side
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tc08_rejected_unknown_side() -> None:
    task = _task()
    trade = _trade(side="HOLD")
    m_engine = AsyncMock(return_value=_approved())

    with patch.object(ct_monitor, "kill_switch_is_active", new=AsyncMock(return_value=False)), \
         patch.object(ct_monitor, "list_active_tasks", new=AsyncMock(return_value=[task])), \
         patch.object(ct_monitor, "fetch_recent_wallet_trades", new=AsyncMock(return_value=[trade])), \
         patch.object(ct_monitor, "_is_already_processed", new=AsyncMock(return_value=False)), \
         patch.object(ct_monitor, "_get_daily_spend", new=AsyncMock(return_value=0.0)), \
         patch.object(ct_monitor, "_record_spend", new=AsyncMock()), \
         patch.object(ct_monitor, "_mark_processed", new=AsyncMock()), \
         patch.object(ct_monitor, "_load_user_context", new=AsyncMock(return_value=USER_CTX)), \
         patch.object(ct_monitor._engine, "execute", new=m_engine):
        await ct_monitor.run_once()

    m_engine.assert_not_awaited()


# ---------------------------------------------------------------------------
# TC09 — reverse_copy flips buy→no
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tc09_reverse_copy_flips_side() -> None:
    task = _task(reverse_copy=True)
    trade = _trade(side="buy")
    captured: list = []

    async def _capture(signal):
        captured.append(signal)
        return _approved()

    with patch.object(ct_monitor, "kill_switch_is_active", new=AsyncMock(return_value=False)), \
         patch.object(ct_monitor, "list_active_tasks", new=AsyncMock(return_value=[task])), \
         patch.object(ct_monitor, "fetch_recent_wallet_trades", new=AsyncMock(return_value=[trade])), \
         patch.object(ct_monitor, "_is_already_processed", new=AsyncMock(return_value=False)), \
         patch.object(ct_monitor, "_get_daily_spend", new=AsyncMock(return_value=0.0)), \
         patch.object(ct_monitor, "_record_spend", new=AsyncMock()), \
         patch.object(ct_monitor, "_mark_processed", new=AsyncMock()), \
         patch.object(ct_monitor, "_load_user_context", new=AsyncMock(return_value=USER_CTX)), \
         patch.object(ct_monitor._engine, "execute", new=AsyncMock(side_effect=_capture)):
        await ct_monitor.run_once()

    assert len(captured) == 1
    assert captured[0].side == "no"


# ---------------------------------------------------------------------------
# TC10 — copy_size below min after spend cap
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tc10_copy_size_below_min_after_spend_cap() -> None:
    # remaining = 10.00 - 9.50 = 0.50 < 1.0 (MIN_TRADE_SIZE_USDC)
    task = _task(max_daily_spend="10.00", copy_amount="5.00")
    trade = _trade(size=5.0)
    m_engine = AsyncMock(return_value=_approved())

    with patch.object(ct_monitor, "kill_switch_is_active", new=AsyncMock(return_value=False)), \
         patch.object(ct_monitor, "list_active_tasks", new=AsyncMock(return_value=[task])), \
         patch.object(ct_monitor, "fetch_recent_wallet_trades", new=AsyncMock(return_value=[trade])), \
         patch.object(ct_monitor, "_is_already_processed", new=AsyncMock(return_value=False)), \
         patch.object(ct_monitor, "_get_daily_spend", new=AsyncMock(return_value=9.50)), \
         patch.object(ct_monitor, "_record_spend", new=AsyncMock()), \
         patch.object(ct_monitor, "_mark_processed", new=AsyncMock()), \
         patch.object(ct_monitor, "_load_user_context", new=AsyncMock(return_value=USER_CTX)), \
         patch.object(ct_monitor._engine, "execute", new=m_engine):
        await ct_monitor.run_once()

    m_engine.assert_not_awaited()


# ---------------------------------------------------------------------------
# TC11 — kill switch active: list_active_tasks not called
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tc11_kill_switch_active() -> None:
    m_tasks = AsyncMock(return_value=[_task()])
    m_engine = AsyncMock(return_value=_approved())

    with patch.object(ct_monitor, "kill_switch_is_active", new=AsyncMock(return_value=True)), \
         patch.object(ct_monitor, "list_active_tasks", new=m_tasks), \
         patch.object(ct_monitor._engine, "execute", new=m_engine):
        await ct_monitor.run_once()

    m_tasks.assert_not_awaited()
    m_engine.assert_not_awaited()


# ---------------------------------------------------------------------------
# TC12 — no active tasks: noop
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tc12_no_active_tasks_noop() -> None:
    m_engine = AsyncMock(return_value=_approved())
    m_fetch = AsyncMock()

    with patch.object(ct_monitor, "kill_switch_is_active", new=AsyncMock(return_value=False)), \
         patch.object(ct_monitor, "list_active_tasks", new=AsyncMock(return_value=[])), \
         patch.object(ct_monitor, "fetch_recent_wallet_trades", new=m_fetch), \
         patch.object(ct_monitor._engine, "execute", new=m_engine):
        await ct_monitor.run_once()

    m_fetch.assert_not_awaited()
    m_engine.assert_not_awaited()


# ---------------------------------------------------------------------------
# TC13 — wallet API raises: no propagation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tc13_wallet_api_unavailable_no_propagation() -> None:
    task = _task()
    m_engine = AsyncMock(return_value=_approved())

    with patch.object(ct_monitor, "kill_switch_is_active", new=AsyncMock(return_value=False)), \
         patch.object(ct_monitor, "list_active_tasks", new=AsyncMock(return_value=[task])), \
         patch.object(
             ct_monitor, "fetch_recent_wallet_trades",
             new=AsyncMock(side_effect=Exception("API down")),
         ), \
         patch.object(ct_monitor._engine, "execute", new=m_engine):
        # must NOT raise
        await ct_monitor.run_once()

    m_engine.assert_not_awaited()


# ---------------------------------------------------------------------------
# Pure helper tests
# ---------------------------------------------------------------------------


def test_extract_trade_id_from_id_field() -> None:
    assert _extract_trade_id({"id": "abc123"}) == "abc123"


def test_extract_trade_id_content_hash_fallback() -> None:
    trade = {"conditionId": "cond_1", "side": "BUY", "size": "5", "timestamp": "ts"}
    result = _extract_trade_id(trade)
    assert result is not None and result.startswith("hash_")


def test_extract_trade_id_returns_none_on_empty() -> None:
    assert _extract_trade_id({}) is None


def test_resolve_side_buy_to_yes() -> None:
    assert _resolve_side("buy", False) == "yes"


def test_resolve_side_sell_to_no() -> None:
    assert _resolve_side("sell", False) == "no"


def test_resolve_side_reverse_buy_to_no() -> None:
    assert _resolve_side("buy", True) == "no"


def test_resolve_side_reverse_sell_to_yes() -> None:
    assert _resolve_side("sell", True) == "yes"


def test_resolve_side_outcome_overrides_buy_sell() -> None:
    # BUY of NO outcome must resolve to 'no', not 'yes'
    assert _resolve_side("buy", False, outcome="no") == "no"
    assert _resolve_side("buy", False, outcome="yes") == "yes"
    # SELL of YES outcome must resolve to 'yes' when outcome is authoritative
    assert _resolve_side("sell", False, outcome="yes") == "yes"


def test_resolve_side_outcome_with_reverse_copy() -> None:
    # outcome='no' + reverse_copy → 'yes'
    assert _resolve_side("buy", True, outcome="no") == "yes"
    # outcome='yes' + reverse_copy → 'no'
    assert _resolve_side("buy", True, outcome="yes") == "no"


def test_make_idempotency_key_format() -> None:
    task_id = UUID("12345678-1234-1234-1234-123456789abc")
    assert _make_idempotency_key(task_id, "lt_999") == (
        "copy_12345678-1234-1234-1234-123456789abc_lt_999"
    )


def test_compute_copy_size_fixed_mode() -> None:
    now = _dt.datetime.utcnow()
    task = CopyTradeTask(
        id=uuid4(), user_id=uuid4(), wallet_address="0x", task_name="t",
        status="active", copy_mode="fixed", copy_amount=Decimal("15.00"),
        copy_pct=None, tp_pct=Decimal("0.2"), sl_pct=Decimal("0.1"),
        max_daily_spend=Decimal("100"), slippage_pct=Decimal("0.05"),
        min_trade_size=Decimal("1"), reverse_copy=False,
        created_at=now, updated_at=now,
    )
    assert _compute_copy_size(task, 50.0, {}, 100.0) == 15.0


def test_compute_copy_size_proportional_mirror_fallback() -> None:
    now = _dt.datetime.utcnow()
    task = CopyTradeTask(
        id=uuid4(), user_id=uuid4(), wallet_address="0x", task_name="t",
        status="active", copy_mode="proportional", copy_amount=Decimal("0"),
        copy_pct=Decimal("0.5"), tp_pct=Decimal("0.2"), sl_pct=Decimal("0.1"),
        max_daily_spend=Decimal("100"), slippage_pct=Decimal("0.05"),
        min_trade_size=Decimal("1"), reverse_copy=False,
        created_at=now, updated_at=now,
    )
    # No bankroll in trade → mirror_size_direct; leader=10, available=100, cap=10%
    # min(10, 100*0.10) = 10; copy_pct=0.5 → 10 * 0.5 = 5.0
    assert _compute_copy_size(task, 10.0, {}, 100.0) == 5.0
