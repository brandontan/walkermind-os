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
        matched_markets_info={"exchange": "kalshi", "market_id": "k1"},
    )


def _s3(*, decision: str, confidence: float, reason: str) -> SmartMoneyCopyTradingDecision:
    return SmartMoneyCopyTradingDecision(
        decision=decision,
        reason=reason,
        confidence=confidence,
        wallet_info={"wallet": "0xabc", "signal_type": "buy"},
    )


def test_multiple_valid_candidates_selects_highest_score() -> None:
    trigger = _make_trigger()

    result = trigger.aggregate_strategy_decisions(
        s1_decision=_s1(decision="ENTER", edge=0.040, reason="news momentum intact"),
        s2_decision=_s2(decision="ENTER", edge=0.028, reason="actionable spread"),
        s3_decision=_s3(decision="ENTER", confidence=0.78, reason="smart wallet alignment"),
    )

    assert result.decision == "ENTER"
    assert result.selected_trade == "S1"
    assert [candidate.strategy_name for candidate in result.ranked_candidates] == ["S1", "S2", "S3"]
    assert result.top_score == result.ranked_candidates[0].score
    assert "highest-ranked" in result.selection_reason


def test_all_weak_candidates_returns_global_skip() -> None:
    trigger = _make_trigger()

    result = trigger.aggregate_strategy_decisions(
        s1_decision=_s1(decision="ENTER", edge=0.010, reason="weak momentum"),
        s2_decision=_s2(decision="ENTER", edge=0.011, reason="weak spread"),
        s3_decision=_s3(decision="ENTER", confidence=0.20, reason="weak wallet signal"),
    )

    assert result.decision == "SKIP"
    assert result.selected_trade is None
    assert result.selection_reason == "all candidates are weak"


def test_mixed_enter_skip_only_considers_enter_candidates() -> None:
    trigger = _make_trigger()

    result = trigger.aggregate_strategy_decisions(
        s1_decision=_s1(decision="SKIP", edge=0.060, reason="already priced in"),
        s2_decision=_s2(decision="ENTER", edge=0.045, reason="actionable spread"),
        s3_decision=_s3(decision="SKIP", confidence=0.90, reason="late wallet signal"),
    )

    assert result.decision == "ENTER"
    assert result.selected_trade == "S2"


def test_tie_case_uses_deterministic_winner() -> None:
    trigger = _make_trigger()

    result = trigger.aggregate_strategy_decisions(
        s1_decision=_s1(decision="ENTER", edge=0.040, reason="s1 tie"),
        s2_decision=_s2(decision="ENTER", edge=0.040, reason="s2 tie"),
        s3_decision=_s3(decision="SKIP", confidence=0.30, reason="ignore"),
    )

    # tie score resolved by strategy_name ascending => S1 wins.
    assert result.decision == "ENTER"
    assert result.selected_trade == "S1"
    assert result.ranked_candidates[0].score == result.ranked_candidates[1].score


def test_missing_confidence_handled_safely_for_s1_s2() -> None:
    trigger = _make_trigger()

    score = trigger._build_strategy_candidate_score(
        strategy_name="S1",
        decision="ENTER",
        reason="missing confidence",
        edge=0.05,
        confidence=None,
        market_metadata={},
    )

    assert score.confidence == 0.5
    assert score.score == 0.5


def test_ranking_output_order_is_stable_and_correct() -> None:
    trigger = _make_trigger()

    result = trigger.aggregate_strategy_decisions(
        s1_decision=_s1(decision="ENTER", edge=0.030, reason="third"),
        s2_decision=_s2(decision="ENTER", edge=0.050, reason="first"),
        s3_decision=_s3(decision="ENTER", confidence=0.70, reason="second"),
    )

    assert [candidate.strategy_name for candidate in result.ranked_candidates] == ["S2", "S1", "S3"]
    assert [candidate.score for candidate in result.ranked_candidates] == sorted(
        [candidate.score for candidate in result.ranked_candidates],
        reverse=True,
    )


def test_global_skip_behavior_conflict_hold_rule() -> None:
    trigger = _make_trigger()

    result = trigger.aggregate_strategy_decisions(
        s1_decision=_s1(decision="ENTER", edge=0.050, reason="CONFLICT_HOLD momentum/reversion"),
        s2_decision=_s2(decision="ENTER", edge=0.048, reason="actionable spread"),
        s3_decision=_s3(decision="ENTER", confidence=0.82, reason="smart wallet alignment"),
    )

    assert result.decision == "SKIP"
    assert result.selected_trade is None
    assert result.selection_reason == "conflict rules require holding"
