"""Execution safety addendum tests for rejected/blocked/partial-fill semantics."""
from __future__ import annotations

import os
import asyncio
from unittest.mock import patch

from projects.polymarket.polyquantbot.core.execution.executor import (
    TradeResult,
    classify_trade_result_outcome,
    execute_trade,
    reset_state,
)
from projects.polymarket.polyquantbot.core.signal.signal_engine import SignalResult


def _signal(signal_id: str = "sig-p1-001") -> SignalResult:
    return SignalResult(
        signal_id=signal_id,
        market_id="mkt-p1",
        side="YES",
        p_market=0.41,
        p_model=0.62,
        edge=0.21,
        ev=0.22,
        kelly_f=0.25,
        size_usd=40.0,
        liquidity_usd=20_000.0,
    )


def test_rejected_callback_not_treated_as_executed() -> None:
    """Rejected callback response must produce non-success + rejected outcome."""
    reset_state()

    async def _rejected_callback(**_: object) -> dict[str, object]:
        return {"status": "REJECTED", "reason": "risk_reject", "filled_size": 0.0}

    with patch.dict(os.environ, {"ENABLE_LIVE_TRADING": "true"}):
        result = asyncio.run(
            execute_trade(
                _signal(),
                mode="LIVE",
                executor_callback=_rejected_callback,
            )
        )

    assert result.success is False
    assert "callback_rejected" in result.reason
    assert classify_trade_result_outcome(result) == "rejected"


def test_partial_fill_callback_is_explicit_and_auditable() -> None:
    """Partial fill callback must remain success with explicit partial semantics."""
    reset_state()

    async def _partial_callback(**_: object) -> dict[str, object]:
        return {
            "status": "PARTIAL",
            "reason": "partial_fill",
            "filled_size": 10.0,
            "fill_price": 0.43,
        }

    with patch.dict(os.environ, {"ENABLE_LIVE_TRADING": "true"}):
        result = asyncio.run(
            execute_trade(
                _signal("sig-p1-002"),
                mode="LIVE",
                executor_callback=_partial_callback,
            )
        )

    assert result.success is True
    assert result.partial_fill is True
    assert result.reason == "partial_fill"
    assert classify_trade_result_outcome(result) == "partial_fill"


def test_kill_switch_block_still_blocks() -> None:
    """Kill switch remains an explicit blocked outcome."""
    reset_state()
    result = asyncio.run(
        execute_trade(_signal("sig-p1-003"), mode="PAPER", kill_switch_active=True)
    )
    assert result.success is False
    assert result.reason == "kill_switch_active"
    assert classify_trade_result_outcome(result) == "blocked"


def test_live_mode_guard_blocks_without_enable_flag() -> None:
    """LIVE mode is blocked unless ENABLE_LIVE_TRADING is true."""
    reset_state()
    with patch.dict(os.environ, {"ENABLE_LIVE_TRADING": "false"}):
        result = asyncio.run(execute_trade(_signal("sig-p1-004"), mode="LIVE"))
    assert result.success is False
    assert result.reason == "live_mode_not_enabled"
    assert classify_trade_result_outcome(result) == "blocked"


def test_execution_outcome_classification_truth_table() -> None:
    """Audit outcome classification differentiates executed/blocked/rejected/failed."""
    executed = TradeResult(
        trade_id="t1",
        signal_id="s1",
        market_id="m1",
        side="YES",
        success=True,
        mode="PAPER",
        attempted_size=10.0,
        filled_size_usd=10.0,
        fill_price=0.5,
        reason="paper_filled",
    )
    blocked = TradeResult(
        trade_id="t2",
        signal_id="s2",
        market_id="m2",
        side="YES",
        success=False,
        mode="PAPER",
        attempted_size=10.0,
        reason="kill_switch_active",
    )
    rejected = TradeResult(
        trade_id="t3",
        signal_id="s3",
        market_id="m3",
        side="YES",
        success=False,
        mode="LIVE",
        attempted_size=10.0,
        reason="callback_rejected:insufficient_funds",
    )
    failed = TradeResult(
        trade_id="t4",
        signal_id="s4",
        market_id="m4",
        side="YES",
        success=False,
        mode="LIVE",
        attempted_size=10.0,
        reason="execution_exception:timeout",
    )

    assert classify_trade_result_outcome(executed) == "executed"
    assert classify_trade_result_outcome(blocked) == "blocked"
    assert classify_trade_result_outcome(rejected) == "rejected"
    assert classify_trade_result_outcome(failed) == "failed"
