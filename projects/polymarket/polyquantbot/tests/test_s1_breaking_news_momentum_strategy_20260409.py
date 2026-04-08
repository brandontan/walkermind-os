from __future__ import annotations

from projects.polymarket.polyquantbot.execution.strategy_trigger import (
    SocialPulseInput,
    StrategyConfig,
    StrategyTrigger,
)


class _NoopEngine:
    async def snapshot(self):  # pragma: no cover - not used by this suite
        raise NotImplementedError


def _make_trigger() -> StrategyTrigger:
    config = StrategyConfig(
        market_id="m-news-1",
        social_spike_threshold=0.65,
        min_mention_surge_ratio=1.6,
        min_author_diversity=12,
        min_acceleration=0.4,
        min_market_lag=0.03,
        min_edge=0.02,
        min_liquidity_usd=10_000.0,
    )
    return StrategyTrigger(engine=_NoopEngine(), config=config)


def test_social_spike_triggers_candidate() -> None:
    trigger = _make_trigger()
    pulse = SocialPulseInput(
        mention_surge_ratio=2.4,
        author_diversity=26,
        acceleration=0.9,
        narrative_probability=0.66,
        liquidity_usd=25_000.0,
        risk_constraints_ok=True,
    )

    decision = trigger.evaluate_breaking_news_momentum(market_price=0.52, social_pulse=pulse)

    assert decision.decision == "ENTER"
    assert decision.edge > 0.02


def test_no_price_move_entry_allowed() -> None:
    trigger = _make_trigger()
    pulse = SocialPulseInput(
        mention_surge_ratio=2.0,
        author_diversity=18,
        acceleration=0.7,
        narrative_probability=0.64,
        liquidity_usd=15_000.0,
        risk_constraints_ok=True,
    )

    decision = trigger.evaluate_breaking_news_momentum(market_price=0.50, social_pulse=pulse)

    assert decision.decision == "ENTER"
    assert "entry conditions met" in decision.reason


def test_already_priced_is_skipped() -> None:
    trigger = _make_trigger()
    pulse = SocialPulseInput(
        mention_surge_ratio=2.5,
        author_diversity=22,
        acceleration=1.0,
        narrative_probability=0.58,
        liquidity_usd=20_000.0,
        risk_constraints_ok=True,
    )

    decision = trigger.evaluate_breaking_news_momentum(market_price=0.56, social_pulse=pulse)

    assert decision.decision == "SKIP"
    assert "already priced in" in decision.reason


def test_weak_signal_is_skipped() -> None:
    trigger = _make_trigger()
    pulse = SocialPulseInput(
        mention_surge_ratio=1.1,
        author_diversity=4,
        acceleration=0.1,
        narrative_probability=0.62,
        liquidity_usd=18_000.0,
        risk_constraints_ok=True,
    )

    decision = trigger.evaluate_breaking_news_momentum(market_price=0.50, social_pulse=pulse)

    assert decision.decision == "SKIP"
    assert "weak signal" in decision.reason


def test_output_format_is_decision_reason_edge() -> None:
    trigger = _make_trigger()
    pulse = SocialPulseInput(
        mention_surge_ratio=2.1,
        author_diversity=17,
        acceleration=0.8,
        narrative_probability=0.65,
        liquidity_usd=16_000.0,
        risk_constraints_ok=True,
    )

    decision = trigger.evaluate_breaking_news_momentum(market_price=0.51, social_pulse=pulse)

    assert set(decision.__dict__.keys()) == {"decision", "reason", "edge"}
    assert isinstance(decision.decision, str)
    assert isinstance(decision.reason, str)
    assert isinstance(decision.edge, float)
