from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from projects.polymarket.polyquantbot.server.core.paper_account import PaperAccountState, PaperAccountStore
from projects.polymarket.polyquantbot.server.core.public_beta_state import STATE
from projects.polymarket.polyquantbot.server.execution.paper_execution import PaperExecutionEngine
from projects.polymarket.polyquantbot.server.integrations.falcon_gateway import CandidateSignal
from projects.polymarket.polyquantbot.server.portfolio.paper_portfolio import PaperPortfolio
from projects.polymarket.polyquantbot.server.risk.paper_risk_gate import PaperRiskGate
from projects.polymarket.polyquantbot.server.workers.paper_beta_worker import PaperBetaWorker


class _SingleCandidateFalcon:
    async def rank_candidates(self):
        return [
            CandidateSignal(
                signal_id="sig-paper-001",
                condition_id="cond-paper-001",
                side="YES",
                edge=0.03,
                liquidity=25000.0,
                price=0.55,
            )
        ]


def _reset_state() -> None:
    STATE.mode = "paper"
    STATE.autotrade_enabled = False
    STATE.kill_switch = False
    STATE.pnl = 0.0
    STATE.drawdown = 0.0
    STATE.exposure = 0.0
    STATE.last_risk_reason = ""
    STATE.positions.clear()
    STATE.processed_signals.clear()
    STATE.paper_account = PaperAccountState()


def test_paper_account_creation_loading_and_persistence(tmp_path: Path) -> None:
    store = PaperAccountStore(tmp_path / "paper_account.json")
    initial = store.load()
    assert initial.account_id == "paper-default"
    assert initial.balance == 10000.0
    initial.apply_fill(condition_id="cond-a", side="YES", fill_size=90.0, fill_price=0.5)
    store.save(initial)
    loaded = store.load()
    assert loaded.order_sequence == initial.order_sequence
    assert loaded.positions["cond-a:YES"].size == 90.0
    assert loaded.equity >= 10000.0


def test_paper_execution_lifecycle_is_deterministic() -> None:
    _reset_state()
    engine = PaperExecutionEngine(PaperPortfolio())
    signal = CandidateSignal(
        signal_id="sig-lifecycle",
        condition_id="cond-lifecycle",
        side="YES",
        edge=0.04,
        liquidity=30000.0,
        price=0.61,
    )
    event = engine.execute(signal, STATE)
    assert event["order_id"] == "paper-order-000001"
    assert event["order_status"] == "filled"
    assert event["lifecycle"] == ["created", "validated", "submitted", "filled"]
    assert event["size"] == 90.0


def test_paper_risk_guard_enforcement_blocks_nonpaper_and_overexposure() -> None:
    _reset_state()
    gate = PaperRiskGate()
    signal = CandidateSignal(
        signal_id="sig-risk",
        condition_id="cond-risk",
        side="YES",
        edge=0.03,
        liquidity=25000.0,
        price=0.52,
    )
    STATE.mode = "live"
    decision_live = gate.evaluate(signal, STATE)
    assert decision_live.allowed is False
    assert decision_live.reason == "mode_not_paper_default"

    STATE.mode = "paper"
    STATE.exposure = 0.10
    decision_exposure = gate.evaluate(signal, STATE)
    assert decision_exposure.allowed is False
    assert decision_exposure.reason == "exposure_cap"


def test_portfolio_surface_reflects_worker_execution_path() -> None:
    _reset_state()
    STATE.autotrade_enabled = True
    worker = PaperBetaWorker(
        falcon=_SingleCandidateFalcon(),
        risk_gate=PaperRiskGate(),
        engine=PaperExecutionEngine(PaperPortfolio()),
    )
    events = asyncio.run(worker.run_once())
    assert len(events) == 1
    assert len(STATE.positions) == 1
    assert STATE.paper_account.total_exposure > 0
    assert STATE.paper_account.equity >= 10000.0
    assert len(STATE.paper_account.orders) == 1
