from __future__ import annotations

from projects.polymarket.polyquantbot.execution.strategy_trigger import (
    CrossExchangeArbitrageDecision,
    SmartMoneyCopyTradingDecision,
    StrategyConfig,
    StrategyDecision,
    StrategyTrigger,
)


class _NoopEngine:
    async def snapshot(self):  # pragma: no cover - not used in this suite
        raise NotImplementedError


def _make_trigger() -> StrategyTrigger:
    return StrategyTrigger(
        engine=_NoopEngine(),
        config=StrategyConfig(
            market_id="m-s4-aggregation-1",
            min_edge=0.02,
            min_liquidity_usd=10_000.0,
        ),
    )


def _s1(*, decision: str, edge: float, reason: str) -> StrategyDecision:
    return StrategyDecision(decision=decision, reason=reason, edge=edge)


def _s2(*, decision: str, edge: float, reason: str) -> CrossExchangeArbitrageDecision:
    return CrossExchangeArbitrageDecision(
        decision=decision,
        reason=reason,
        edge=edge,
        matched_markets_info={"source": "kalshi"},
    )


def _s3(*, decision: str, confidence: float, reason: str) -> SmartMoneyCopyTradingDecision:
    return SmartMoneyCopyTradingDecision(
        decision=decision,
        reason=reason,
        confidence=confidence,
        wallet_info={"source": "wallet"},
    )


def test_multiple_candidates_best_selected() -> None:
    trigger = _make_trigger()

    result = trigger.aggregate_strategy_decisions(
        s1_decision=_s1(decision="ENTER", edge=0.038, reason="news momentum intact"),
        s2_decision=_s2(decision="ENTER", edge=0.026, reason="actionable spread"),
        s3_decision=_s3(decision="ENTER", confidence=0.78, reason="smart wallet alignment"),
    )

    assert result.selected_trade == "S1"
    assert result.ranking[0].strategy_id == "S1"
    assert {candidate.strategy_id for candidate in result.ranking} == {"S1", "S2", "S3"}
    assert "highest-ranked" in result.reason


def test_all_weak_candidates_returns_no_trade() -> None:
    trigger = _make_trigger()

    result = trigger.aggregate_strategy_decisions(
        s1_decision=_s1(decision="ENTER", edge=0.012, reason="weak momentum"),
        s2_decision=_s2(decision="ENTER", edge=0.011, reason="weak spread"),
        s3_decision=_s3(decision="ENTER", confidence=0.30, reason="weak wallet signal"),
    )

    assert result.selected_trade is None
    assert result.reason == "all candidates below threshold"


def test_conflicting_signals_too_strong_returns_no_trade() -> None:
    trigger = _make_trigger()

    result = trigger.aggregate_strategy_decisions(
        s1_decision=_s1(decision="ENTER", edge=0.050, reason="momentum continuation"),
        s2_decision=_s2(decision="ENTER", edge=0.049, reason="reversion spread signal"),
        s3_decision=_s3(decision="SKIP", confidence=0.10, reason="low-confidence wallet signal"),
    )

    assert result.selected_trade is None
    assert result.reason == "conflicting signals too strong"


def test_score_calculation_uses_weighted_edge_confidence() -> None:
    trigger = _make_trigger()

    score = trigger._build_strategy_candidate_score(
        strategy_id="S1",
        decision="ENTER",
        reason="score check",
        edge=0.05,
        confidence=0.8,
    )

    assert score.score == 0.59
    assert score.edge == 0.05
    assert score.confidence == 0.8


def test_selection_is_deterministic_on_identical_inputs() -> None:
    trigger = _make_trigger()

    first = trigger.aggregate_strategy_decisions(
        s1_decision=_s1(decision="ENTER", edge=0.039, reason="news momentum"),
        s2_decision=_s2(decision="ENTER", edge=0.027, reason="arb spread"),
        s3_decision=_s3(decision="ENTER", confidence=0.80, reason="wallet alignment"),
    )
    second = trigger.aggregate_strategy_decisions(
        s1_decision=_s1(decision="ENTER", edge=0.039, reason="news momentum"),
        s2_decision=_s2(decision="ENTER", edge=0.027, reason="arb spread"),
        s3_decision=_s3(decision="ENTER", confidence=0.80, reason="wallet alignment"),
    )

    assert first.selected_trade == second.selected_trade
    assert first.reason == second.reason
    assert first.ranking == second.ranking
