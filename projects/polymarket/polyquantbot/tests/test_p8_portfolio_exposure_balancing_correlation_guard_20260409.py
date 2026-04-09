from __future__ import annotations

import asyncio
from dataclasses import dataclass

from projects.polymarket.polyquantbot.execution.strategy_trigger import (
    StrategyAggregationDecision,
    StrategyCandidateScore,
    StrategyConfig,
    StrategyTrigger,
)


@dataclass(frozen=True)
class _Snapshot:
    positions: tuple[object, ...]
    cash: float
    equity: float
    realized_pnl: float
    unrealized_pnl: float
    implied_prob: float
    volatility: float


class _Position:
    def __init__(self, market_id: str, size: float, *, theme: str | None = None) -> None:
        self.market_id = market_id
        self._size = size
        self.theme = theme

    def exposure(self) -> float:
        return self._size


class _Engine:
    def __init__(self, *, equity: float = 10_000.0, exposure_ratio: float = 0.30) -> None:
        self.max_total_exposure_ratio = exposure_ratio
        self.max_position_size_ratio = 0.10
        self._snapshot = _Snapshot(
            positions=tuple(),
            cash=equity,
            equity=equity,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            implied_prob=0.50,
            volatility=0.10,
        )
        self.open_calls: list[dict[str, float | str]] = []

    async def snapshot(self) -> _Snapshot:
        return self._snapshot

    async def open_position(self, **kwargs: float | str):
        self.open_calls.append(kwargs)
        return type("Opened", (), {"position_id": str(kwargs.get("position_id", "p1"))})()

    async def update_mark_to_market(self, _: dict[str, float]) -> float:
        return 0.0

    async def close_position(self, _position: object, _price: float) -> float:
        return 0.0

    def set_snapshot(self, *, equity: float, positions: tuple[_Position, ...]) -> None:
        total_exposure = sum(item.exposure() for item in positions)
        self._snapshot = _Snapshot(
            positions=positions,
            cash=max(0.0, equity - total_exposure),
            equity=equity,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            implied_prob=0.50,
            volatility=0.10,
        )


def _make_trigger(engine: _Engine | None = None) -> StrategyTrigger:
    return StrategyTrigger(
        engine=engine or _Engine(),
        config=StrategyConfig(
            market_id="market-default",
            min_edge=0.02,
            min_position_size_usd=25.0,
            max_position_size_ratio=0.10,
            max_market_exposure_ratio=0.15,
            max_theme_exposure_ratio=0.20,
            correlation_size_reduction_factor=0.50,
            high_similarity_overlap_ratio=0.50,
        ),
    )


def _aggregation(*, market_id: str, theme: str, edge: float = 0.09, confidence: float = 0.95) -> StrategyAggregationDecision:
    candidate = StrategyCandidateScore(
        strategy_name="S2",
        decision="ENTER",
        reason="selected by S4",
        edge=edge,
        confidence=confidence,
        score=0.90,
        market_metadata={"market_id": market_id, "theme": theme},
    )
    return StrategyAggregationDecision(
        selected_trade="S2",
        ranked_candidates=[candidate],
        selection_reason="top score",
        top_score=0.90,
        decision="ENTER",
    )


def test_same_market_is_blocked() -> None:
    trigger = _make_trigger()
    decision = trigger.evaluate_portfolio_exposure_and_correlation(
        target_market_id="election-2026-winner",
        target_theme="us-politics",
        proposed_size=500.0,
        open_positions=[_Position("election-2026-winner", 300.0, theme="us-politics")],
        total_capital=10_000.0,
    )

    assert decision.final_decision == "SKIP"
    assert decision.adjusted_size == 0.0
    assert "same_market_block" in decision.flags


def test_similar_market_is_reduced() -> None:
    trigger = _make_trigger()
    decision = trigger.evaluate_portfolio_exposure_and_correlation(
        target_market_id="btc-will-hit-100k-in-2026",
        target_theme="crypto",
        proposed_size=800.0,
        open_positions=[_Position("btc-hit-100k-2026", 300.0, theme="crypto")],
        total_capital=10_000.0,
    )

    assert decision.final_decision == "REDUCE"
    assert 0.0 < decision.adjusted_size < 800.0
    assert "high_similarity_reduce" in decision.flags


def test_diversified_portfolio_is_allowed() -> None:
    trigger = _make_trigger()
    decision = trigger.evaluate_portfolio_exposure_and_correlation(
        target_market_id="fed-rate-cut-july",
        target_theme="macro",
        proposed_size=500.0,
        open_positions=[
            _Position("nba-finals-2026", 250.0, theme="sports"),
            _Position("weather-hurricane-atlantic", 350.0, theme="weather"),
        ],
        total_capital=10_000.0,
    )

    assert decision.final_decision == "ENTER"
    assert decision.adjusted_size == 500.0


def test_total_exposure_cap_is_enforced() -> None:
    trigger = _make_trigger()
    decision = trigger.evaluate_portfolio_exposure_and_correlation(
        target_market_id="new-clean-energy-bill",
        target_theme="policy",
        proposed_size=900.0,
        open_positions=[_Position("existing-position", 2_700.0, theme="sports")],
        total_capital=10_000.0,
    )

    assert decision.final_decision == "REDUCE"
    assert decision.adjusted_size == 300.0


def test_guard_is_deterministic() -> None:
    trigger = _make_trigger()
    p = [_Position("btc-hit-100k-2026", 400.0, theme="crypto")]
    first = trigger.evaluate_portfolio_exposure_and_correlation(
        target_market_id="btc-will-hit-100k-in-2026",
        target_theme="crypto",
        proposed_size=700.0,
        open_positions=p,
        total_capital=10_000.0,
    )
    second = trigger.evaluate_portfolio_exposure_and_correlation(
        target_market_id="btc-will-hit-100k-in-2026",
        target_theme="crypto",
        proposed_size=700.0,
        open_positions=p,
        total_capital=10_000.0,
    )

    assert first == second


def test_runtime_proof_blocked_due_to_correlation() -> None:
    engine = _Engine(equity=10_000.0)
    engine.set_snapshot(
        equity=10_000.0,
        positions=(_Position("election-2026-winner", 250.0, theme="us-politics"),),
    )
    trigger = _make_trigger(engine)

    async def _run() -> str:
        return await trigger.evaluate(
            market_price=0.20,
            aggregation_decision=_aggregation(market_id="election-2026-winner", theme="us-politics"),
        )

    outcome = asyncio.run(_run())
    assert outcome == "BLOCKED"
    assert len(engine.open_calls) == 0


def test_runtime_proof_reduced_due_to_exposure() -> None:
    engine = _Engine(equity=10_000.0)
    engine.set_snapshot(
        equity=10_000.0,
        positions=(_Position("existing-position", 2_700.0, theme="sports"),),
    )
    trigger = _make_trigger(engine)

    async def _run() -> str:
        return await trigger.evaluate(
            market_price=0.20,
            aggregation_decision=_aggregation(market_id="macro-fed-july", theme="macro", edge=0.10, confidence=0.95),
        )

    outcome = asyncio.run(_run())
    assert outcome == "OPENED"
    assert len(engine.open_calls) == 1
    assert engine.open_calls[0]["size"] == 300.0


def test_runtime_proof_normal_trade_allowed() -> None:
    engine = _Engine(equity=10_000.0)
    engine.set_snapshot(
        equity=10_000.0,
        positions=(_Position("weather-hurricane-atlantic", 300.0, theme="weather"),),
    )
    trigger = _make_trigger(engine)

    async def _run() -> str:
        return await trigger.evaluate(
            market_price=0.20,
            aggregation_decision=_aggregation(market_id="fed-rate-cut-july", theme="macro"),
        )

    outcome = asyncio.run(_run())
    assert outcome == "OPENED"
    assert len(engine.open_calls) == 1
    assert 0.0 < float(engine.open_calls[0]["size"]) <= 1_000.0
