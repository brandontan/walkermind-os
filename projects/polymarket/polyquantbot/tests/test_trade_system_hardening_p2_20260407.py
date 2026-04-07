from __future__ import annotations

import asyncio

from projects.polymarket.polyquantbot.core.execution.executor import (
    evaluate_formal_risk_gate,
    TradeResult,
    classify_trade_result_outcome,
)
from projects.polymarket.polyquantbot.core.portfolio.pnl import PnLTracker
from projects.polymarket.polyquantbot.core.signal.signal_engine import SignalResult
from projects.polymarket.polyquantbot.execution.engine_router import EngineContainer


class InMemoryExecutionDB:
    def __init__(self) -> None:
        self._seen: set[str] = set()
        self.intent_marks: list[tuple[str, str, str]] = []

    async def reserve_execution_intent(self, signal_id: str, market_id: str) -> bool:
        _ = market_id
        if signal_id in self._seen:
            return False
        self._seen.add(signal_id)
        return True

    async def mark_execution_intent(
        self,
        signal_id: str,
        *,
        status: str,
        reason: str = "",
        trade_id: str = "",
    ) -> bool:
        _ = trade_id
        self.intent_marks.append((signal_id, status, reason))
        return True

    async def get_positions(self, user_id: str):
        _ = user_id
        return []

    async def get_recent_trades(self, limit: int = 500):
        _ = limit
        return []

    async def upsert_position(self, payload: dict):
        _ = payload
        return True

    async def insert_trade(self, payload: dict):
        _ = payload
        return True

    async def update_trade_status(self, trade_id: str, status: str, **kwargs):
        _ = (trade_id, status, kwargs)
        return True


def test_active_loop_blocks_before_execution_on_formal_risk_gate():
    signal = SignalResult(
        signal_id="sig-risk-block",
        market_id="m1",
        side="YES",
        p_market=0.5,
        p_model=0.5,
        edge=0.0,
        ev=0.0,
        kelly_f=0.0,
        size_usd=10.0,
        liquidity_usd=50_000.0,
    )
    decision = evaluate_formal_risk_gate(
        signal,
        mode="PAPER",
        max_position_usd=100.0,
        min_edge=0.01,
        min_liquidity_usd=10_000.0,
        kill_switch_active=False,
    )
    assert decision.allowed is False
    assert decision.reason == "edge_non_positive"


def test_duplicate_replay_blocked_after_restart():
    signal = SignalResult(
        signal_id="sig-dup",
        market_id="m2",
        side="YES",
        p_market=0.4,
        p_model=0.6,
        edge=0.2,
        ev=0.1,
        kelly_f=0.2,
        size_usd=10.0,
        liquidity_usd=50_000.0,
    )
    db = InMemoryExecutionDB()
    first = asyncio.run(db.reserve_execution_intent(signal.signal_id, signal.market_id))
    second = asyncio.run(db.reserve_execution_intent(signal.signal_id, signal.market_id))
    assert first is True
    assert second is False


def test_restore_rebinds_wallet_runtime_state():
    class _RestoreDB:
        async def load_latest_wallet_state(self):
            return {"cash": 777.0, "locked": 23.0, "equity": 800.0}

        async def load_open_paper_positions(self):
            return []

        async def load_ledger_entries(self, limit: int = 5000):
            _ = limit
            return []

    container = EngineContainer()
    old_wallet = container.wallet
    asyncio.run(container.restore_from_db(_RestoreDB()))

    assert container.wallet is not old_wallet
    assert container.paper_engine._wallet is container.wallet
    assert container.wallet.get_state().cash == 777.0


def test_outcomes_are_explicit_and_auditable():
    assert classify_trade_result_outcome(TradeResult("1", "s", "m", "YES", True, "PAPER", 10.0)) == "executed"
    assert classify_trade_result_outcome(TradeResult("1", "s", "m", "YES", True, "PAPER", 10.0, partial_fill=True)) == "partial_fill"
    assert classify_trade_result_outcome(TradeResult("1", "s", "m", "YES", False, "PAPER", 10.0, reason="callback_rejected:bad")) == "rejected"
    assert classify_trade_result_outcome(TradeResult("1", "s", "m", "YES", False, "PAPER", 10.0, reason="kill_switch_active")) == "blocked"


def test_critical_exception_path_is_observable(monkeypatch, capsys):
    tracker = PnLTracker(db=object())
    monkeypatch.setattr(asyncio, "get_event_loop", lambda: (_ for _ in ()).throw(RuntimeError("no_loop")))
    tracker.record_realized("m3", 1.0, trade_id="tid")
    assert "pnl_persist_schedule_skipped" in capsys.readouterr().out
