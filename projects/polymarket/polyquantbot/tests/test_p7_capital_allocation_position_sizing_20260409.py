from __future__ import annotations

import asyncio
from dataclasses import dataclass

from projects.polymarket.polyquantbot.execution.strategy_trigger import (
    PositionSizingDecision,
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
    def __init__(self, size: float) -> None:
        self._size = size

    def exposure(self) -> float:
        return self._size


class _SizingEngine:
    def __init__(self, equity: float = 10_000.0, *, exposure_ratio: float = 0.30) -> None:
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
        self.open_calls: list[dict[str, float]] = []

    async def snapshot(self) -> _Snapshot:
        return self._snapshot

    async def open_position(self, **kwargs: float):
        self.open_calls.append(kwargs)
        return type("Opened", (), {"position_id": str(kwargs.get("position_id", "p1"))})()

    async def update_mark_to_market(self, _: dict[str, float]) -> float:
        return 0.0

    async def close_position(self, _position: object, _price: float) -> float:
        return 0.0

    def set_snapshot(self, *, equity: float, exposure: float = 0.0) -> None:
        positions = tuple([_Position(exposure)]) if exposure > 0.0 else tuple()
        self._snapshot = _Snapshot(
            positions=positions,
            cash=max(0.0, equity - exposure),
            equity=equity,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            implied_prob=0.50,
            volatility=0.10,
        )


def _make_trigger(engine: _SizingEngine | None = None) -> StrategyTrigger:
    return StrategyTrigger(
        engine=engine or _SizingEngine(),
        config=StrategyConfig(
            market_id="m-p7-sizing-1",
            min_edge=0.02,
            min_liquidity_usd=10_000.0,
            min_position_size_usd=25.0,
            max_position_size_ratio=0.10,
        ),
    )


def _aggregation(*, edge: float, confidence: float | None, selected_trade: str = "S1") -> StrategyAggregationDecision:
    candidate = StrategyCandidateScore(
        strategy_name=selected_trade,
        decision="ENTER",
        reason="selected for sizing",
        edge=edge,
        confidence=0.5 if confidence is None else confidence,
        score=0.80,
        market_metadata={},
    )
    return StrategyAggregationDecision(
        selected_trade=selected_trade,
        ranked_candidates=[candidate],
        selection_reason="highest-ranked",
        top_score=0.8,
        decision="ENTER",
    )


def test_strong_edge_produces_larger_position_within_cap() -> None:
    trigger = _make_trigger()
    strong = trigger._compute_position_size("S1", edge=0.09, confidence=0.92, total_capital=10_000.0, current_total_exposure=0.0)
    weak = trigger._compute_position_size("S1", edge=0.03, confidence=0.60, total_capital=10_000.0, current_total_exposure=0.0)

    assert strong.position_size > weak.position_size
    assert strong.position_size <= 1_000.0


def test_weak_edge_produces_small_or_zero_size() -> None:
    trigger = _make_trigger()
    result = trigger._compute_position_size("S1", edge=0.021, confidence=0.55, total_capital=10_000.0, current_total_exposure=0.0)

    assert result.position_size < 150.0
    assert "borderline_edge_conservative" in result.applied_constraints


def test_missing_confidence_is_conservative() -> None:
    trigger = _make_trigger()
    with_conf = trigger._compute_position_size("S1", edge=0.06, confidence=0.80, total_capital=10_000.0, current_total_exposure=0.0)
    missing_conf = trigger._compute_position_size("S1", edge=0.06, confidence=None, total_capital=10_000.0, current_total_exposure=0.0)

    assert missing_conf.position_size < with_conf.position_size
    assert "confidence_missing_conservative" in missing_conf.applied_constraints


def test_cap_and_total_exposure_constraints_are_enforced() -> None:
    trigger = _make_trigger()
    result = trigger._compute_position_size("S1", edge=0.20, confidence=1.0, total_capital=10_000.0, current_total_exposure=2_700.0)

    assert result.position_size == 300.0
    assert "total_exposure_cap" in result.applied_constraints


def test_sizing_is_deterministic() -> None:
    trigger = _make_trigger()
    r1 = trigger._compute_position_size("S1", edge=0.045, confidence=0.67, total_capital=12_500.0, current_total_exposure=400.0)
    r2 = trigger._compute_position_size("S1", edge=0.045, confidence=0.67, total_capital=12_500.0, current_total_exposure=400.0)

    assert r1 == r2


def test_s4_selected_trade_is_applied_before_execution() -> None:
    engine = _SizingEngine(equity=10_000.0)
    trigger = _make_trigger(engine)
    aggregation = _aggregation(edge=0.09, confidence=0.95, selected_trade="S2")

    async def _run() -> PositionSizingDecision:
        outcome = await trigger.evaluate(market_price=0.20, aggregation_decision=aggregation)
        assert outcome == "OPENED"
        assert len(engine.open_calls) == 1
        return trigger.compute_position_size_from_s4_selection(
            aggregation=aggregation,
            total_capital=10_000.0,
            current_total_exposure=0.0,
        )

    sizing = asyncio.run(_run())
    assert engine.open_calls[0]["size"] == sizing.position_size
    assert sizing.position_size > 0.0
