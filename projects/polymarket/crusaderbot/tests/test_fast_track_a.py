"""Hermetic tests for Fast Track A — trade engine + TP/SL auto-close pipeline.

Coverage:
    TradeEngine.execute()
      * gate approved → paper position opened, order_id/position_id returned
      * gate rejected (auto_trade_off, paused, kill_switch, daily_loss, etc.)
        → TradeResult(approved=False, rejection_reason=..., mode=None)
      * idempotent duplicate → TradeResult(approved=True, mode="duplicate")
      * router raises → exception propagates (no silent swallowing)
      * paper-only: chosen_mode always "paper" when activation guards are OFF

    Exit watcher (TP/SL auto-close loop) — Track A close reasons:
      * TP_HIT  — ret_pct >= applied_tp_pct → ExitReason.TP_HIT
      * SL_HIT  — ret_pct <= -applied_sl_pct → ExitReason.SL_HIT
      * MANUAL  — force_close_intent=False, no TP/SL breach → hold
                  (manual close is user-triggered directly, watcher holds)
      * EMERGENCY (FORCE_CLOSE) — force_close_intent=True → ExitReason.FORCE_CLOSE,
                  beats TP/SL (priority 1 in watcher)
      * resolved market → hold (watcher skips; redeemer settles)

    GateContext mapping — TradeSignal fields flow through correctly.
    TradeSignal / TradeResult dataclass field contract.
    ExitReason enum canonical string values.

No DB, no broker, no Telegram. All external calls patched.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from projects.polymarket.crusaderbot.domain.execution.exit_watcher import (
    evaluate as watcher_evaluate,
)
from projects.polymarket.crusaderbot.domain.positions.registry import (
    ExitReason,
    OpenPositionForExit,
)
from projects.polymarket.crusaderbot.domain.risk.gate import GateResult
from projects.polymarket.crusaderbot.services.trade_engine import (
    TradeEngine,
    TradeResult,
    TradeSignal,
)

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_USER_UUID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_ORDER_UUID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
_POS_UUID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
_MARKET = "market-001"
_NOW = datetime(2026, 5, 10, 12, 0, 0, tzinfo=timezone.utc)

_GATE_MODULE = "projects.polymarket.crusaderbot.services.trade_engine.engine._risk_evaluate"
_ROUTER_MODULE = "projects.polymarket.crusaderbot.services.trade_engine.engine._router_execute"


def _signal(
    *,
    auto_trade_on: bool = True,
    paused: bool = False,
    access_tier: int = 3,
    market_status: str = "active",
    market_liquidity: float = 50_000.0,
    side: str = "yes",
    proposed_size_usdc: Decimal = Decimal("100.00"),
    price: float = 0.40,
    tp_pct: float | None = 0.20,
    sl_pct: float | None = 0.10,
    trading_mode: str = "paper",
    risk_profile: str = "balanced",
    edge_bps: float | None = 300.0,
) -> TradeSignal:
    return TradeSignal(
        user_id=_USER_UUID,
        telegram_user_id=12345,
        access_tier=access_tier,
        auto_trade_on=auto_trade_on,
        paused=paused,
        market_id=_MARKET,
        market_question="Will X happen?",
        yes_token_id="tok-yes",
        no_token_id="tok-no",
        side=side,
        proposed_size_usdc=proposed_size_usdc,
        price=price,
        market_liquidity=market_liquidity,
        market_status=market_status,
        idempotency_key=f"ta:{uuid4().hex[:16]}",
        strategy_type="signal_following",
        risk_profile=risk_profile,
        trading_mode=trading_mode,
        signal_ts=_NOW,
        edge_bps=edge_bps,
        tp_pct=tp_pct,
        sl_pct=sl_pct,
    )


def _approved_gate(size: Decimal = Decimal("25.00")) -> GateResult:
    return GateResult(
        approved=True,
        reason="approved",
        failed_step=None,
        final_size_usdc=size,
        chosen_mode="paper",
    )


def _rejected_gate(reason: str, step: int) -> GateResult:
    return GateResult(approved=False, reason=reason, failed_step=step)


def _paper_ok() -> dict[str, Any]:
    return {"order_id": _ORDER_UUID, "position_id": _POS_UUID, "mode": "paper"}


def _paper_dup() -> dict[str, Any]:
    return {"status": "duplicate", "mode": "paper"}


def _make_position(
    *,
    side: str = "yes",
    entry_price: float = 0.40,
    yes_price: float | None = 0.40,
    no_price: float | None = 0.60,
    applied_tp_pct: float | None = 0.20,
    applied_sl_pct: float | None = 0.10,
    force_close_intent: bool = False,
    market_resolved: bool = False,
) -> OpenPositionForExit:
    return OpenPositionForExit(
        id=_POS_UUID,
        user_id=_USER_UUID,
        telegram_user_id=12345,
        market_id=_MARKET,
        market_question="Will X happen?",
        side=side,
        entry_price=entry_price,
        size_usdc=100.0,
        mode="paper",
        status="open",
        applied_tp_pct=applied_tp_pct,
        applied_sl_pct=applied_sl_pct,
        force_close_intent=force_close_intent,
        close_failure_count=0,
        yes_price=yes_price,
        no_price=no_price,
        market_resolved=market_resolved,
    )


# ---------------------------------------------------------------------------
# TradeEngine — gate rejected paths
# ---------------------------------------------------------------------------


class TestTradeEngineGateRejected:

    def test_auto_trade_off(self):
        sig = _signal(auto_trade_on=False)
        gate_rej = _rejected_gate("auto_trade_off_or_paused", 2)
        router_mock = AsyncMock()
        with (
            pytest.MonkeyPatch().context() as mp
        ):
            mp.setattr(
                "projects.polymarket.crusaderbot.services.trade_engine.engine._risk_evaluate",
                AsyncMock(return_value=gate_rej),
            )
            mp.setattr(
                "projects.polymarket.crusaderbot.services.trade_engine.engine._router_execute",
                router_mock,
            )
            result = asyncio.run(TradeEngine().execute(sig))
        assert result.approved is False
        assert result.rejection_reason == "auto_trade_off_or_paused"
        assert result.failed_gate_step == 2
        assert result.mode is None
        assert result.order_id is None
        router_mock.assert_not_called()

    def test_paused(self):
        sig = _signal(paused=True)
        gate_rej = _rejected_gate("auto_trade_off_or_paused", 2)
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(
                "projects.polymarket.crusaderbot.services.trade_engine.engine._risk_evaluate",
                AsyncMock(return_value=gate_rej),
            )
            result = asyncio.run(TradeEngine().execute(sig))
        assert result.approved is False

    def test_kill_switch_active(self):
        sig = _signal()
        gate_rej = _rejected_gate("kill_switch_active", 1)
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(
                "projects.polymarket.crusaderbot.services.trade_engine.engine._risk_evaluate",
                AsyncMock(return_value=gate_rej),
            )
            result = asyncio.run(TradeEngine().execute(sig))
        assert result.approved is False
        assert result.failed_gate_step == 1
        assert result.rejection_reason == "kill_switch_active"

    def test_daily_loss_cap(self):
        sig = _signal()
        gate_rej = _rejected_gate("daily_loss_cap_hit", 5)
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(
                "projects.polymarket.crusaderbot.services.trade_engine.engine._risk_evaluate",
                AsyncMock(return_value=gate_rej),
            )
            result = asyncio.run(TradeEngine().execute(sig))
        assert result.approved is False
        assert result.failed_gate_step == 5

    def test_market_inactive(self):
        sig = _signal(market_status="resolved")
        gate_rej = _rejected_gate("market_inactive", 13)
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(
                "projects.polymarket.crusaderbot.services.trade_engine.engine._risk_evaluate",
                AsyncMock(return_value=gate_rej),
            )
            result = asyncio.run(TradeEngine().execute(sig))
        assert result.approved is False
        assert result.failed_gate_step == 13

    def test_insufficient_tier(self):
        sig = _signal(access_tier=2)
        gate_rej = _rejected_gate("insufficient_tier", 3)
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(
                "projects.polymarket.crusaderbot.services.trade_engine.engine._risk_evaluate",
                AsyncMock(return_value=gate_rej),
            )
            result = asyncio.run(TradeEngine().execute(sig))
        assert result.approved is False
        assert result.failed_gate_step == 3

    def test_insufficient_liquidity(self):
        sig = _signal(market_liquidity=100.0)
        gate_rej = _rejected_gate("insufficient_liquidity", 11)
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(
                "projects.polymarket.crusaderbot.services.trade_engine.engine._risk_evaluate",
                AsyncMock(return_value=gate_rej),
            )
            result = asyncio.run(TradeEngine().execute(sig))
        assert result.approved is False
        assert result.failed_gate_step == 11


# ---------------------------------------------------------------------------
# TradeEngine — approved paths
# ---------------------------------------------------------------------------


class TestTradeEngineApproved:

    def test_paper_open_returns_ids(self):
        sig = _signal()
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(
                "projects.polymarket.crusaderbot.services.trade_engine.engine._risk_evaluate",
                AsyncMock(return_value=_approved_gate()),
            )
            mp.setattr(
                "projects.polymarket.crusaderbot.services.trade_engine.engine._router_execute",
                AsyncMock(return_value=_paper_ok()),
            )
            result = asyncio.run(TradeEngine().execute(sig))
        assert result.approved is True
        assert result.mode == "paper"
        assert result.order_id == _ORDER_UUID
        assert result.position_id == _POS_UUID
        assert result.rejection_reason is None
        assert result.chosen_mode == "paper"

    def test_idempotent_duplicate(self):
        sig = _signal()
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(
                "projects.polymarket.crusaderbot.services.trade_engine.engine._risk_evaluate",
                AsyncMock(return_value=_approved_gate()),
            )
            mp.setattr(
                "projects.polymarket.crusaderbot.services.trade_engine.engine._router_execute",
                AsyncMock(return_value=_paper_dup()),
            )
            result = asyncio.run(TradeEngine().execute(sig))
        assert result.approved is True
        assert result.mode == "duplicate"
        assert result.order_id is None
        assert result.position_id is None

    def test_final_size_from_gate_used(self):
        """Engine must use gate.final_size_usdc, not signal.proposed_size_usdc."""
        sig = _signal(proposed_size_usdc=Decimal("500.00"))
        gate_size = Decimal("25.00")
        captured: dict = {}

        async def capture_router(**kwargs):
            captured["size_usdc"] = kwargs["size_usdc"]
            return _paper_ok()

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(
                "projects.polymarket.crusaderbot.services.trade_engine.engine._risk_evaluate",
                AsyncMock(return_value=_approved_gate(size=gate_size)),
            )
            mp.setattr(
                "projects.polymarket.crusaderbot.services.trade_engine.engine._router_execute",
                capture_router,
            )
            result = asyncio.run(TradeEngine().execute(sig))
        assert result.approved is True
        assert captured["size_usdc"] == gate_size

    def test_tp_sl_forwarded_to_router(self):
        sig = _signal(tp_pct=0.20, sl_pct=0.08)
        captured: dict = {}

        async def capture_router(**kwargs):
            captured.update({"tp_pct": kwargs.get("tp_pct"), "sl_pct": kwargs.get("sl_pct")})
            return _paper_ok()

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(
                "projects.polymarket.crusaderbot.services.trade_engine.engine._risk_evaluate",
                AsyncMock(return_value=_approved_gate()),
            )
            mp.setattr(
                "projects.polymarket.crusaderbot.services.trade_engine.engine._router_execute",
                capture_router,
            )
            asyncio.run(TradeEngine().execute(sig))
        assert abs(captured["tp_pct"] - 0.20) < 1e-9
        assert abs(captured["sl_pct"] - 0.08) < 1e-9

    def test_no_tp_sl_forwarded_as_none(self):
        sig = _signal(tp_pct=None, sl_pct=None)
        captured: dict = {}

        async def capture_router(**kwargs):
            captured.update({"tp_pct": kwargs.get("tp_pct"), "sl_pct": kwargs.get("sl_pct")})
            return _paper_ok()

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(
                "projects.polymarket.crusaderbot.services.trade_engine.engine._risk_evaluate",
                AsyncMock(return_value=_approved_gate()),
            )
            mp.setattr(
                "projects.polymarket.crusaderbot.services.trade_engine.engine._router_execute",
                capture_router,
            )
            asyncio.run(TradeEngine().execute(sig))
        assert captured["tp_pct"] is None
        assert captured["sl_pct"] is None

    def test_router_raises_propagates(self):
        sig = _signal()
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(
                "projects.polymarket.crusaderbot.services.trade_engine.engine._risk_evaluate",
                AsyncMock(return_value=_approved_gate()),
            )
            mp.setattr(
                "projects.polymarket.crusaderbot.services.trade_engine.engine._router_execute",
                AsyncMock(side_effect=RuntimeError("db_pool_gone")),
            )
            with pytest.raises(RuntimeError, match="db_pool_gone"):
                asyncio.run(TradeEngine().execute(sig))

    def test_gate_raises_propagates(self):
        sig = _signal()
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(
                "projects.polymarket.crusaderbot.services.trade_engine.engine._risk_evaluate",
                AsyncMock(side_effect=RuntimeError("db_pool_gone")),
            )
            with pytest.raises(RuntimeError, match="db_pool_gone"):
                asyncio.run(TradeEngine().execute(sig))

    def test_paper_chosen_mode_when_guards_off(self):
        sig = _signal(trading_mode="paper")
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(
                "projects.polymarket.crusaderbot.services.trade_engine.engine._risk_evaluate",
                AsyncMock(return_value=_approved_gate()),
            )
            mp.setattr(
                "projects.polymarket.crusaderbot.services.trade_engine.engine._router_execute",
                AsyncMock(return_value=_paper_ok()),
            )
            result = asyncio.run(TradeEngine().execute(sig))
        assert result.chosen_mode == "paper"
        assert result.mode == "paper"


# ---------------------------------------------------------------------------
# GateContext mapping
# ---------------------------------------------------------------------------


class TestGateContextMapping:

    def test_all_fields_mapped(self):
        sig = _signal(
            side="no",
            proposed_size_usdc=Decimal("150.00"),
            price=0.60,
            market_liquidity=25_000.0,
            market_status="active",
            access_tier=4,
            auto_trade_on=True,
            paused=False,
            risk_profile="aggressive",
        )
        ctx = TradeEngine._build_gate_context(sig)
        assert ctx.user_id == _USER_UUID
        assert ctx.telegram_user_id == 12345
        assert ctx.access_tier == 4
        assert ctx.auto_trade_on is True
        assert ctx.paused is False
        assert ctx.market_id == _MARKET
        assert ctx.side == "no"
        assert ctx.proposed_size_usdc == Decimal("150.00")
        assert abs(ctx.proposed_price - 0.60) < 1e-9
        assert abs(ctx.market_liquidity - 25_000.0) < 1e-9
        assert ctx.market_status == "active"
        assert ctx.strategy_type == "signal_following"
        assert ctx.risk_profile == "aggressive"
        assert ctx.trading_mode == "paper"
        assert ctx.signal_ts == _NOW

    def test_edge_bps_forwarded(self):
        sig = _signal(edge_bps=500.0)
        ctx = TradeEngine._build_gate_context(sig)
        assert abs(ctx.edge_bps - 500.0) < 1e-9

    def test_no_edge_bps_is_none(self):
        sig = _signal(edge_bps=None)
        ctx = TradeEngine._build_gate_context(sig)
        assert ctx.edge_bps is None

    def test_gate_context_is_called_with_signal_fields(self):
        sig = _signal(side="yes", risk_profile="conservative")
        captured: dict = {}

        async def capture_gate(ctx):
            captured.update({"side": ctx.side, "risk_profile": ctx.risk_profile})
            return _approved_gate()

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(
                "projects.polymarket.crusaderbot.services.trade_engine.engine._risk_evaluate",
                capture_gate,
            )
            mp.setattr(
                "projects.polymarket.crusaderbot.services.trade_engine.engine._router_execute",
                AsyncMock(return_value=_paper_ok()),
            )
            asyncio.run(TradeEngine().execute(sig))
        assert captured["side"] == "yes"
        assert captured["risk_profile"] == "conservative"


# ---------------------------------------------------------------------------
# Exit watcher — Track A close reasons
# ---------------------------------------------------------------------------


class TestExitWatcherTrackACloseReasons:

    def test_tp_hit_yes_side(self):
        """YES side: current price > entry by >= tp_pct."""
        pos = _make_position(
            side="yes", entry_price=0.40,
            yes_price=0.49,   # (0.49-0.40)/0.40 = 22.5% > 20% TP
            applied_tp_pct=0.20, applied_sl_pct=0.10,
        )
        decision = asyncio.run(watcher_evaluate(pos))
        assert decision.should_exit is True
        assert decision.reason == ExitReason.TP_HIT.value

    def test_sl_hit_yes_side(self):
        """YES side: current price falls below entry by >= sl_pct."""
        pos = _make_position(
            side="yes", entry_price=0.40,
            yes_price=0.33,   # (0.33-0.40)/0.40 = -17.5%, sl=10% → SL_HIT
            applied_tp_pct=0.20, applied_sl_pct=0.10,
        )
        decision = asyncio.run(watcher_evaluate(pos))
        assert decision.should_exit is True
        assert decision.reason == ExitReason.SL_HIT.value

    def test_sl_hit_no_side(self):
        """NO side: YES rising (bad for NO holder) triggers SL."""
        pos = _make_position(
            side="no", entry_price=0.40,
            yes_price=0.53, no_price=0.47,
            # comp_entry=1-0.40=0.60, comp_exit=1-0.47=0.53
            # ret=(0.53-0.60)/0.60≈-11.7% <= -SL(10%) → SL_HIT
            applied_tp_pct=0.20, applied_sl_pct=0.10,
        )
        decision = asyncio.run(watcher_evaluate(pos))
        assert decision.should_exit is True
        assert decision.reason == ExitReason.SL_HIT.value

    def test_emergency_force_close_beats_tp(self):
        """FORCE_CLOSE (EMERGENCY) is priority 1 — beats TP even when TP triggered."""
        pos = _make_position(
            side="yes", entry_price=0.40,
            yes_price=0.55,    # would trigger TP at 20%
            applied_tp_pct=0.20,
            force_close_intent=True,
        )
        decision = asyncio.run(watcher_evaluate(pos))
        assert decision.should_exit is True
        assert decision.reason == ExitReason.FORCE_CLOSE.value

    def test_emergency_force_close_beats_sl(self):
        """FORCE_CLOSE also has priority over SL."""
        pos = _make_position(
            side="yes", entry_price=0.40,
            yes_price=0.30,    # would trigger SL
            applied_sl_pct=0.10,
            force_close_intent=True,
        )
        decision = asyncio.run(watcher_evaluate(pos))
        assert decision.should_exit is True
        assert decision.reason == ExitReason.FORCE_CLOSE.value

    def test_manual_close_watcher_holds(self):
        """MANUAL close is user-triggered directly — watcher holds when no breach."""
        pos = _make_position(
            side="yes", entry_price=0.40,
            yes_price=0.40,    # no P&L → no TP/SL breach
            applied_tp_pct=0.20, applied_sl_pct=0.10,
            force_close_intent=False,
        )
        decision = asyncio.run(watcher_evaluate(pos))
        assert decision.should_exit is False
        assert decision.reason is None

    def test_resolved_market_skipped(self):
        """Watcher must not close resolved markets — redeemer settles them."""
        pos = _make_position(
            side="yes", entry_price=0.40,
            yes_price=1.0,     # would be huge TP
            applied_tp_pct=0.20,
            market_resolved=True,
        )
        decision = asyncio.run(watcher_evaluate(pos))
        assert decision.should_exit is False

    def test_hold_when_no_tp_sl_set(self):
        """No auto-close when applied_tp/sl are None and force_close_intent=False."""
        pos = _make_position(
            side="yes", entry_price=0.40,
            yes_price=0.55,    # would be TP if set
            applied_tp_pct=None, applied_sl_pct=None,
            force_close_intent=False,
        )
        decision = asyncio.run(watcher_evaluate(pos))
        assert decision.should_exit is False

    def test_price_at_entry_holds(self):
        """Zero P&L → neither TP nor SL triggers."""
        pos = _make_position(
            side="yes", entry_price=0.50,
            yes_price=0.50,
            applied_tp_pct=0.10, applied_sl_pct=0.05,
        )
        decision = asyncio.run(watcher_evaluate(pos))
        assert decision.should_exit is False

    def test_tp_hit_no_side(self):
        """NO side: comp price rising (i.e. YES falls) triggers TP."""
        pos = _make_position(
            side="no", entry_price=0.60,
            yes_price=0.44, no_price=0.56,
            # comp_entry=0.40, comp_exit=0.44 → ret=(0.44-0.40)/0.40=+10% < 20% TP
            applied_tp_pct=0.05, applied_sl_pct=0.20,
            # with TP=5% and ret=10%, TP fires
        )
        decision = asyncio.run(watcher_evaluate(pos))
        assert decision.should_exit is True
        assert decision.reason == ExitReason.TP_HIT.value


# ---------------------------------------------------------------------------
# TradeSignal / TradeResult dataclass field contract
# ---------------------------------------------------------------------------


class TestTradeSignalContract:

    def test_frozen_raises_on_mutation(self):
        sig = _signal()
        with pytest.raises(Exception):
            sig.side = "no"  # type: ignore[misc]  # frozen dataclass

    def test_default_trading_mode_paper(self):
        sig = _signal()
        assert sig.trading_mode == "paper"

    def test_tp_sl_none_allowed(self):
        sig = _signal(tp_pct=None, sl_pct=None)
        assert sig.tp_pct is None
        assert sig.sl_pct is None

    def test_signal_ts_none_allowed(self):
        sig = TradeSignal(
            user_id=_USER_UUID, telegram_user_id=12345, access_tier=3,
            auto_trade_on=True, paused=False, market_id=_MARKET,
            market_question=None, yes_token_id=None, no_token_id=None,
            side="yes", proposed_size_usdc=Decimal("50"), price=0.50,
            market_liquidity=20_000.0, market_status="active",
            idempotency_key="k1", strategy_type="signal_following",
            risk_profile="balanced", trading_mode="paper", signal_ts=None,
        )
        assert sig.signal_ts is None


class TestTradeResultContract:

    def test_rejected_result_fields(self):
        r = TradeResult(
            approved=False, mode=None, order_id=None, position_id=None,
            rejection_reason="kill_switch_active", failed_gate_step=1,
        )
        assert r.approved is False
        assert r.mode is None
        assert r.rejection_reason == "kill_switch_active"
        assert r.failed_gate_step == 1

    def test_approved_result_fields(self):
        r = TradeResult(
            approved=True, mode="paper",
            order_id=_ORDER_UUID, position_id=_POS_UUID,
            rejection_reason=None, failed_gate_step=None,
            chosen_mode="paper",
        )
        assert r.approved is True
        assert r.mode == "paper"
        assert r.order_id == _ORDER_UUID
        assert r.chosen_mode == "paper"


# ---------------------------------------------------------------------------
# ExitReason canonical string values
# ---------------------------------------------------------------------------


class TestExitReasonValues:

    def test_tp_hit(self):
        assert ExitReason.TP_HIT.value == "tp_hit"

    def test_sl_hit(self):
        assert ExitReason.SL_HIT.value == "sl_hit"

    def test_manual(self):
        assert ExitReason.MANUAL.value == "manual"

    def test_emergency_maps_to_force_close(self):
        # Track A "EMERGENCY" close is stored as FORCE_CLOSE in the DB
        assert ExitReason.FORCE_CLOSE.value == "force_close"


# ---------------------------------------------------------------------------
# Scan path → TradeEngine integration
# ---------------------------------------------------------------------------

from unittest.mock import MagicMock, patch  # noqa: E402 (post-import for clarity)

from projects.polymarket.crusaderbot.domain.strategy.types import SignalCandidate
from projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job import (
    _build_trade_signal,
    _process_candidate,
)

_SCAN_ENGINE = (
    "projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job._engine"
)
_SCAN_ROUTER = (
    "projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job.router_execute"
)
_SCAN_DEDUP = (
    "projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job"
    "._publication_already_queued"
)
_SCAN_STALE = (
    "projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job"
    "._load_stale_queued_row"
)
_SCAN_MARKET = (
    "projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job._load_market"
)
_SCAN_INSERT = (
    "projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job"
    "._insert_execution_queue"
)
_SCAN_MARK_EXEC = (
    "projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job._mark_executed"
)


def _make_scan_row(user_id: UUID | None = None) -> dict:
    return {
        "user_id": user_id or _USER_UUID,
        "telegram_user_id": 12345,
        "access_tier": 3,
        "auto_trade_on": True,
        "paused": False,
        "balance_usdc": Decimal("500.00"),
        "risk_profile": "balanced",
        "trading_mode": "paper",
        "tp_pct": 0.20,
        "sl_pct": 0.10,
        "daily_loss_override": None,
        "resolved_profile": "balanced",
    }


def _make_scan_cand(pub_id: str | None = None) -> SignalCandidate:
    return SignalCandidate(
        market_id="mkt-scan-001",
        condition_id="cond-001",
        side="YES",
        confidence=0.75,
        suggested_size_usdc=25.0,
        strategy_name="signal_following",
        signal_ts=_NOW,
        metadata={"publication_id": pub_id or str(uuid4())},
    )


def _make_scan_market() -> dict:
    return {
        "id": "mkt-scan-001",
        "question": "Will X happen?",
        "yes_price": 0.60,
        "no_price": 0.40,
        "yes_token_id": "yt-001",
        "no_token_id": "nt-001",
        "liquidity_usdc": 50_000.0,
        "status": "open",
    }


class TestScanPathTradeEngineIntegration:
    """Prove the active scan path routes through TradeEngine, not direct router."""

    @pytest.mark.asyncio
    async def test_process_candidate_calls_engine_not_router_on_approval(self):
        """Normal approval path must call TradeEngine.execute(), not router_execute."""
        row = _make_scan_row()
        cand = _make_scan_cand()
        market = _make_scan_market()
        approved = TradeResult(
            approved=True, mode="paper",
            order_id=_ORDER_UUID, position_id=_POS_UUID,
            rejection_reason=None, failed_gate_step=None,
            chosen_mode="paper", final_size_usdc=Decimal("25.00"),
        )

        mock_router = AsyncMock()
        mock_engine_execute = AsyncMock(return_value=approved)

        with (
            patch(_SCAN_STALE, new=AsyncMock(return_value=None)),
            patch(_SCAN_DEDUP, new=AsyncMock(return_value=False)),
            patch(_SCAN_MARKET, new=AsyncMock(return_value=market)),
            patch(_SCAN_ENGINE + ".execute", new=mock_engine_execute),
            patch(_SCAN_ROUTER, new=mock_router),
            patch(_SCAN_INSERT, new=AsyncMock(return_value=True)),
            patch(_SCAN_MARK_EXEC, new=AsyncMock()),
        ):
            await _process_candidate(row, cand)

        mock_engine_execute.assert_called_once()
        signal_arg = mock_engine_execute.call_args[0][0]
        assert isinstance(signal_arg, TradeSignal)
        assert signal_arg.market_id == "mkt-scan-001"
        assert signal_arg.side == "yes"  # normalized to lowercase
        assert signal_arg.trading_mode == "paper"
        assert signal_arg.tp_pct == pytest.approx(0.20)
        assert signal_arg.sl_pct == pytest.approx(0.10)
        # router_execute must NOT be called on the normal approval path
        mock_router.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_candidate_gate_rejection_skips_queue(self):
        """Gate rejection must not insert into execution_queue."""
        row = _make_scan_row()
        cand = _make_scan_cand()
        market = _make_scan_market()
        rejected = TradeResult(
            approved=False, mode=None,
            order_id=None, position_id=None,
            rejection_reason="auto_trade_off", failed_gate_step=1,
            chosen_mode=None,
        )

        mock_insert = AsyncMock(return_value=True)
        with (
            patch(_SCAN_STALE, new=AsyncMock(return_value=None)),
            patch(_SCAN_DEDUP, new=AsyncMock(return_value=False)),
            patch(_SCAN_MARKET, new=AsyncMock(return_value=market)),
            patch(_SCAN_ENGINE + ".execute", new=AsyncMock(return_value=rejected)),
            patch(_SCAN_INSERT, new=mock_insert),
            patch(_SCAN_MARK_EXEC, new=AsyncMock()),
        ):
            await _process_candidate(row, cand)

        mock_insert.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_candidate_dedup_skips_engine(self):
        """Permanent dedup must short-circuit before TradeEngine is called."""
        row = _make_scan_row()
        cand = _make_scan_cand()

        mock_engine_execute = AsyncMock()
        with (
            patch(_SCAN_STALE, new=AsyncMock(return_value=None)),
            patch(_SCAN_DEDUP, new=AsyncMock(return_value=True)),
            patch(_SCAN_ENGINE + ".execute", new=mock_engine_execute),
        ):
            await _process_candidate(row, cand)

        mock_engine_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_candidate_duplicate_mode_skips_queue_insert(self):
        """Idempotent duplicate result must not insert a second queue entry."""
        row = _make_scan_row()
        cand = _make_scan_cand()
        market = _make_scan_market()
        dup = TradeResult(
            approved=True, mode="duplicate",
            order_id=None, position_id=None,
            rejection_reason=None, failed_gate_step=None,
            chosen_mode="paper", final_size_usdc=Decimal("25.00"),
        )

        mock_insert = AsyncMock(return_value=True)
        with (
            patch(_SCAN_STALE, new=AsyncMock(return_value=None)),
            patch(_SCAN_DEDUP, new=AsyncMock(return_value=False)),
            patch(_SCAN_MARKET, new=AsyncMock(return_value=market)),
            patch(_SCAN_ENGINE + ".execute", new=AsyncMock(return_value=dup)),
            patch(_SCAN_INSERT, new=mock_insert),
            patch(_SCAN_MARK_EXEC, new=AsyncMock()),
        ):
            await _process_candidate(row, cand)

        mock_insert.assert_not_called()

    def test_build_trade_signal_yes_side_maps_yes_price(self):
        """YES-side signal uses yes_price as proposed_price."""
        row = _make_scan_row()
        cand = _make_scan_cand()
        market = _make_scan_market()
        sig = _build_trade_signal(row=row, cand=cand, market=market, idempotency_key="k1")
        assert sig.side == "yes"
        assert sig.price == pytest.approx(0.60)
        assert sig.market_liquidity == pytest.approx(50_000.0)
        assert sig.trading_mode == "paper"
        assert sig.strategy_type == "signal_following"
        assert sig.idempotency_key == "k1"

    def test_build_trade_signal_no_side_maps_no_price(self):
        """NO-side signal uses no_price as proposed_price."""
        row = _make_scan_row()
        cand_no = SignalCandidate(
            market_id="mkt-scan-001",
            condition_id="cond-001",
            side="NO",
            confidence=0.70,
            suggested_size_usdc=20.0,
            strategy_name="signal_following",
            signal_ts=_NOW,
            metadata={},
        )
        market = _make_scan_market()
        sig = _build_trade_signal(row=row, cand=cand_no, market=market, idempotency_key="k2")
        assert sig.side == "no"
        assert sig.price == pytest.approx(0.40)

    def test_build_trade_signal_tp_sl_from_row(self):
        """TP and SL are taken from user settings row, not hardcoded."""
        row = {**_make_scan_row(), "tp_pct": 0.30, "sl_pct": 0.15}
        sig = _build_trade_signal(
            row=row, cand=_make_scan_cand(), market=_make_scan_market(),
            idempotency_key="k3",
        )
        assert sig.tp_pct == pytest.approx(0.30)
        assert sig.sl_pct == pytest.approx(0.15)

    def test_build_trade_signal_none_tp_sl_when_row_missing(self):
        """Missing TP/SL in row produces None fields on TradeSignal."""
        row = {**_make_scan_row(), "tp_pct": None, "sl_pct": None}
        sig = _build_trade_signal(
            row=row, cand=_make_scan_cand(), market=_make_scan_market(),
            idempotency_key="k4",
        )
        assert sig.tp_pct is None
        assert sig.sl_pct is None
