from __future__ import annotations

from pathlib import Path

from projects.polymarket.polyquantbot.server.core.public_beta_state import PaperPosition, PublicBetaState
from projects.polymarket.polyquantbot.server.execution.paper_execution import PaperExecutionEngine
from projects.polymarket.polyquantbot.server.integrations.falcon_gateway import CandidateSignal
from projects.polymarket.polyquantbot.server.portfolio.paper_portfolio import PaperPortfolio
from projects.polymarket.polyquantbot.server.risk.paper_risk_gate import PaperRiskGate
from projects.polymarket.polyquantbot.server.services.paper_account_service import PaperAccountService
from projects.polymarket.polyquantbot.server.storage.paper_account_store import PersistentPaperAccountStore


def _make_signal(*, signal_id: str = "sig-1", price: float = 0.62) -> CandidateSignal:
    return CandidateSignal(
        signal_id=signal_id,
        condition_id="cond-1",
        side="YES",
        edge=0.03,
        liquidity=20000.0,
        price=price,
    )


def test_paper_account_creation_and_loading(tmp_path: Path) -> None:
    storage_path = tmp_path / "paper_account.json"
    store = PersistentPaperAccountStore(storage_path=storage_path)
    service = PaperAccountService(store=store)
    state = PublicBetaState()

    loaded = service.load_into_state(state)
    assert loaded.account_id == "paper-default"
    assert loaded.cash_balance == 10000.0

    loaded.daily_trade_count = 2
    store.put_account(loaded)

    reloaded_store = PersistentPaperAccountStore(storage_path=storage_path)
    reloaded = reloaded_store.get_account()
    assert reloaded.daily_trade_count == 2


def test_paper_execution_lifecycle_updates_account_and_positions(tmp_path: Path) -> None:
    state = PublicBetaState()
    store = PersistentPaperAccountStore(storage_path=tmp_path / "paper_account.json")
    account_service = PaperAccountService(store=store)
    account_service.load_into_state(state)
    engine = PaperExecutionEngine(PaperPortfolio(), account_service)

    event = engine.execute(_make_signal(), state)

    assert event["lifecycle"] == ["accepted", "filled"]
    assert event["order_id"] == "paper-sig-1"
    assert len(state.positions) == 1
    assert state.paper_account.daily_trade_count == 1
    assert state.paper_account.cash_balance < state.paper_account.starting_balance


def test_paper_risk_guards_trade_count_and_daily_loss() -> None:
    gate = PaperRiskGate()
    state = PublicBetaState()
    for idx in range(gate.MAX_CONCURRENT_TRADES):
        state.positions.append(
            PaperPosition(
                condition_id=f"c{idx}",
                side="YES",
                size=100.0,
                entry_price=0.6,
                edge=0.03,
            )
        )
    decision = gate.evaluate(_make_signal(signal_id="sig-cap"), state)
    assert decision.allowed is False
    assert decision.reason == "paper_trade_count_guard"

    state.positions.clear()
    state.paper_account.daily_realized_pnl = -2500.0
    loss_decision = gate.evaluate(_make_signal(signal_id="sig-loss"), state)
    assert loss_decision.allowed is False
    assert loss_decision.reason == "paper_daily_loss_guard"


def test_portfolio_summary_reflects_account_and_positions(tmp_path: Path) -> None:
    state = PublicBetaState()
    store = PersistentPaperAccountStore(storage_path=tmp_path / "paper_account.json")
    service = PaperAccountService(store=store)
    service.load_into_state(state)
    engine = PaperExecutionEngine(PaperPortfolio(), service)
    engine.execute(_make_signal(signal_id="sig-summary", price=0.55), state)

    summary = service.get_portfolio_summary(state)
    assert summary["paper_only_execution_boundary"] is True
    assert summary["position_count"] == 1
    assert summary["account"]["daily_trade_count"] == 1
    assert "cash_balance" in summary["account"]
