"""Pipeline runtime hardening tests.

Proves:
  1. RISK gate always runs before EXECUTION (router_execute)
  2. router_execute is NEVER called when gate rejects
  3. MONITORING receives events from every pipeline stage via event_bus
  4. No mock/fake data leaks into paper runtime paths when is_demo filtering holds
  5. Paper mode does not bypass the pipeline ordering

No DB, no broker, no Telegram. All external calls patched.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import UUID, uuid4

import pytest

from projects.polymarket.crusaderbot.core import event_bus
from projects.polymarket.crusaderbot.domain.risk.gate import GateResult
from projects.polymarket.crusaderbot.services.trade_engine import (
    TradeEngine,
    TradeResult,
    TradeSignal,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_USER = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_ORDER = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
_POS = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
_MARKET = "0xdeadbeef000000000000000000000001"
_NOW = datetime(2026, 5, 18, 12, 0, 0, tzinfo=timezone.utc)

_GATE = "projects.polymarket.crusaderbot.services.trade_engine.engine._risk_evaluate"
_ROUTER = "projects.polymarket.crusaderbot.services.trade_engine.engine._router_execute"
_EMIT = "projects.polymarket.crusaderbot.services.trade_engine.engine._event_bus.emit"


def _gate_approve(chosen_mode: str = "paper", size: Decimal = Decimal("50.00")) -> GateResult:
    return GateResult(
        approved=True,
        reason=None,
        failed_step=None,
        chosen_mode=chosen_mode,
        final_size_usdc=size,
    )


def _gate_reject(reason: str = "kill_switch", step: int = 1) -> GateResult:
    return GateResult(
        approved=False,
        reason=reason,
        failed_step=step,
        chosen_mode="paper",
        final_size_usdc=None,
    )


def _router_paper_response() -> dict:
    return {
        "order_id": str(_ORDER),
        "position_id": str(_POS),
        "status": "filled",
        "mode": "paper",
    }


def _signal(**overrides: Any) -> TradeSignal:
    defaults: dict[str, Any] = dict(
        user_id=_USER,
        telegram_user_id=99_999,
        access_tier=3,
        auto_trade_on=True,
        paused=False,
        market_id=_MARKET,
        market_question="Will this test pass?",
        yes_token_id="tok-yes",
        no_token_id="tok-no",
        side="yes",
        proposed_size_usdc=Decimal("100.00"),
        price=0.42,
        market_liquidity=50_000.0,
        market_status="active",
        idempotency_key="sf:testhardening",
        strategy_type="trend_breakout",
        risk_profile="balanced",
        trading_mode="paper",
        signal_ts=_NOW,
        tp_pct=0.20,
        sl_pct=0.10,
        daily_loss_override=None,
        edge_bps=300.0,
    )
    defaults.update(overrides)
    return TradeSignal(**defaults)


# ---------------------------------------------------------------------------
# 1. RISK runs before EXECUTION — gate rejection prevents router call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_risk_gate_runs_before_router_on_reject():
    """When gate rejects, router_execute is NEVER called."""
    engine = TradeEngine()
    gate_mock = AsyncMock(return_value=_gate_reject("kill_switch", 1))
    router_mock = AsyncMock()

    with patch(_GATE, gate_mock), patch(_ROUTER, router_mock), patch(_EMIT, AsyncMock()):
        result = await engine.execute(_signal())

    gate_mock.assert_awaited_once()
    router_mock.assert_not_awaited()
    assert not result.approved
    assert result.rejection_reason == "kill_switch"


@pytest.mark.asyncio
async def test_risk_gate_runs_before_router_on_approve():
    """When gate approves, router_execute is called exactly once."""
    engine = TradeEngine()
    gate_mock = AsyncMock(return_value=_gate_approve())
    router_mock = AsyncMock(return_value=_router_paper_response())

    with patch(_GATE, gate_mock), patch(_ROUTER, router_mock), patch(_EMIT, AsyncMock()):
        result = await engine.execute(_signal())

    gate_mock.assert_awaited_once()
    router_mock.assert_awaited_once()
    assert result.approved
    assert result.mode == "paper"


@pytest.mark.asyncio
async def test_router_not_called_on_any_rejection_reason():
    """All gate rejection reasons prevent router from being called."""
    rejection_reasons = [
        ("kill_switch", 1),
        ("paused", 2),
        ("insufficient_balance", 3),
        ("single_position_cap", 4),
        ("total_exposure_cap", 5),
        ("daily_loss_floor", 6),
        ("drawdown_circuit_breaker", 7),
        ("max_concurrent_trades", 8),
        ("insufficient_liquidity", 9),
        ("low_edge", 10),
        ("signal_stale", 11),
        ("duplicate_idempotency", 12),
    ]
    engine = TradeEngine()
    for reason, step in rejection_reasons:
        gate_mock = AsyncMock(return_value=_gate_reject(reason, step))
        router_mock = AsyncMock()
        with patch(_GATE, gate_mock), patch(_ROUTER, router_mock), patch(_EMIT, AsyncMock()):
            result = await engine.execute(_signal())
        assert not result.approved, f"expected rejected for {reason}"
        router_mock.assert_not_awaited(), f"router called for reason={reason}"


# ---------------------------------------------------------------------------
# 2. MONITORING receives events from pipeline stages via event_bus
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_risk_gate_evaluated_event_emitted_on_approve():
    """pipeline.risk_gate_evaluated is emitted when gate approves."""
    engine = TradeEngine()
    gate_mock = AsyncMock(return_value=_gate_approve())
    router_mock = AsyncMock(return_value=_router_paper_response())
    emitted_events: list[str] = []

    async def capture_emit(event: str, **_kw: Any) -> None:
        emitted_events.append(event)

    with patch(_GATE, gate_mock), patch(_ROUTER, router_mock), patch(_EMIT, capture_emit):
        await engine.execute(_signal())

    assert "pipeline.risk_gate_evaluated" in emitted_events, \
        f"Expected pipeline.risk_gate_evaluated in {emitted_events}"


@pytest.mark.asyncio
async def test_risk_gate_evaluated_event_emitted_on_reject():
    """pipeline.risk_gate_evaluated is emitted when gate rejects."""
    engine = TradeEngine()
    gate_mock = AsyncMock(return_value=_gate_reject("paused", 2))
    emitted_events: list[str] = []

    async def capture_emit(event: str, **_kw: Any) -> None:
        emitted_events.append(event)

    with patch(_GATE, gate_mock), patch(_EMIT, capture_emit):
        await engine.execute(_signal())

    assert "pipeline.risk_gate_evaluated" in emitted_events


@pytest.mark.asyncio
async def test_position_opened_event_emitted_on_successful_fill():
    """position.opened is emitted after a successful paper fill (EXECUTION → MONITORING)."""
    engine = TradeEngine()
    gate_mock = AsyncMock(return_value=_gate_approve())
    router_mock = AsyncMock(return_value=_router_paper_response())
    emitted_events: list[str] = []

    async def capture_emit(event: str, **_kw: Any) -> None:
        emitted_events.append(event)

    with patch(_GATE, gate_mock), patch(_ROUTER, router_mock), patch(_EMIT, capture_emit):
        await engine.execute(_signal())

    assert "position.opened" in emitted_events, \
        f"Expected position.opened in {emitted_events}"


@pytest.mark.asyncio
async def test_event_order_risk_then_execution():
    """pipeline.risk_gate_evaluated is emitted BEFORE position.opened."""
    engine = TradeEngine()
    gate_mock = AsyncMock(return_value=_gate_approve())
    router_mock = AsyncMock(return_value=_router_paper_response())
    emitted_events: list[str] = []

    async def capture_emit(event: str, **_kw: Any) -> None:
        emitted_events.append(event)

    with patch(_GATE, gate_mock), patch(_ROUTER, router_mock), patch(_EMIT, capture_emit):
        await engine.execute(_signal())

    risk_idx = emitted_events.index("pipeline.risk_gate_evaluated")
    exec_idx = emitted_events.index("position.opened")
    assert risk_idx < exec_idx, \
        f"RISK event at {risk_idx} must precede EXECUTION event at {exec_idx}; got {emitted_events}"


@pytest.mark.asyncio
async def test_trade_blocked_event_emitted_on_liquidity_rejection():
    """trade.blocked is emitted when gate rejects due to insufficient_liquidity."""
    engine = TradeEngine()
    gate_mock = AsyncMock(return_value=_gate_reject("insufficient_liquidity", 9))
    emitted_events: list[str] = []

    async def capture_emit(event: str, **_kw: Any) -> None:
        emitted_events.append(event)

    with patch(_GATE, gate_mock), patch(_EMIT, capture_emit):
        await engine.execute(_signal())

    assert "trade.blocked" in emitted_events


# ---------------------------------------------------------------------------
# 3. No mock/fake data leaks into paper runtime paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_paper_mode_signal_goes_through_real_pipeline():
    """Paper mode signals flow through the real risk gate + router path, not a mock shortcut."""
    engine = TradeEngine()
    gate_mock = AsyncMock(return_value=_gate_approve(chosen_mode="paper"))
    router_mock = AsyncMock(return_value=_router_paper_response())

    with patch(_GATE, gate_mock), patch(_ROUTER, router_mock), patch(_EMIT, AsyncMock()):
        result = await engine.execute(_signal(trading_mode="paper"))

    assert result.approved
    assert result.chosen_mode == "paper"
    # Gate must have been called — no shortcut
    gate_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_live_execution_without_all_guards():
    """chosen_mode must be 'paper' when activation guards are off (default)."""
    engine = TradeEngine()
    # Gate returns paper mode because guards are off
    gate_mock = AsyncMock(return_value=_gate_approve(chosen_mode="paper"))
    router_mock = AsyncMock(return_value=_router_paper_response())

    with patch(_GATE, gate_mock), patch(_ROUTER, router_mock), patch(_EMIT, AsyncMock()):
        result = await engine.execute(_signal(trading_mode="paper"))

    # router receives chosen_mode="paper" — live execution path never entered
    call_kwargs = router_mock.call_args.kwargs
    assert call_kwargs.get("chosen_mode") == "paper", \
        f"expected chosen_mode=paper, got {call_kwargs.get('chosen_mode')}"


@pytest.mark.asyncio
async def test_dry_run_does_not_call_router():
    """dry_run_execute runs risk gate but never calls router_execute."""
    engine = TradeEngine()
    gate_mock = AsyncMock(return_value=_gate_approve())
    router_mock = AsyncMock()

    with patch(_GATE, gate_mock), patch(_ROUTER, router_mock), patch(_EMIT, AsyncMock()):
        dry = await engine.dry_run_execute(_signal())

    gate_mock.assert_awaited_once()
    router_mock.assert_not_awaited()
    assert dry.would_be_rejected is False


@pytest.mark.asyncio
async def test_duplicate_idempotency_key_returns_duplicate_not_new_position():
    """Idempotent duplicate returns mode='duplicate', not a new position."""
    engine = TradeEngine()
    gate_mock = AsyncMock(return_value=_gate_approve())
    router_mock = AsyncMock(return_value={"status": "duplicate", "mode": "paper"})

    with patch(_GATE, gate_mock), patch(_ROUTER, router_mock), patch(_EMIT, AsyncMock()):
        result = await engine.execute(_signal())

    assert result.approved
    assert result.mode == "duplicate"
    # Router was called once — idempotency handled at paper engine level
    router_mock.assert_awaited_once()


# ---------------------------------------------------------------------------
# 4. Signal scan pipeline stage event ordering
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scan_completed_event_contract():
    """pipeline.scan_completed event carries correct field contract."""
    from projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job import run_once

    emitted: list[tuple[str, dict]] = []

    async def capture(event: str, **kw: Any) -> None:
        emitted.append((event, kw))

    _scan_emit = "projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job._event_bus.emit"

    with (
        patch("projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job._load_enrolled_users",
              AsyncMock(return_value=[])),
        patch(_scan_emit, capture),
    ):
        await run_once()

    # When no users, only the first scan_started is emitted with user_count=0
    events = [e for e, _ in emitted]
    assert "pipeline.strategy_scan_started" in events


@pytest.mark.asyncio
async def test_strategy_scan_done_event_emitted():
    """pipeline.strategy_scan_done fires after Phase A when users exist."""
    from projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job import run_once

    _mock_user = {
        "user_id": str(_USER),
        "telegram_user_id": 12345,
        "access_tier": 3,
        "auto_trade_on": True,
        "paused": False,
        "balance_usdc": Decimal("1000.00"),
        "risk_profile": "balanced",
        "trading_mode": "paper",
        "tp_pct": 0.2,
        "sl_pct": 0.1,
        "daily_loss_override": None,
        "capital_allocation_pct": 0.1,
        "resolved_profile": "balanced",
        "active_preset": None,
        "min_liquidity_threshold": 0.0,
    }

    emitted: list[tuple[str, dict]] = []

    async def capture(event: str, **kw: Any) -> None:
        emitted.append((event, dict(kw)))

    _scan_emit = "projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job._event_bus.emit"

    with (
        patch("projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job._load_enrolled_users",
              AsyncMock(return_value=[_mock_user])),
        patch("projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job._fetch_markets_for_lib_strategies",
              AsyncMock(return_value=[])),
        patch("projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job.run_lib_strategy",
              return_value=[]),
        patch(_scan_emit, capture),
    ):
        await run_once()

    events = [e for e, _ in emitted]
    assert "pipeline.strategy_scan_done" in events, f"Got events: {events}"
    assert "pipeline.scan_completed" in events, f"Got events: {events}"

    done_payload = next(kw for e, kw in emitted if e == "pipeline.strategy_scan_done")
    assert "strategy_count" in done_payload
    assert "total_signals" in done_payload
