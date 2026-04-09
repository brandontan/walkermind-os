from __future__ import annotations

from projects.polymarket.polyquantbot.execution.strategy_trigger import (
    CrossExchangeArbitrageDecision,
    MarketRegimeInputs,
    SmartMoneyCopyTradingDecision,
    StrategyConfig,
    StrategyDecision,
    StrategyTrigger,
)


class _NoopEngine:
    async def snapshot(self):  # pragma: no cover - not used
        raise NotImplementedError


def _make_trigger() -> StrategyTrigger:
    return StrategyTrigger(
        engine=_NoopEngine(),
        config=StrategyConfig(market_id="m-p11-regime", min_edge=0.02),
    )


def test_strong_social_spike_classifies_news_regime() -> None:
    trigger = _make_trigger()
    result = trigger.detect_market_regime(
        MarketRegimeInputs(
            social_spike_intensity=0.92,
            price_dispersion=0.42,
            wallet_activity_strength=0.40,
            trade_frequency=0.60,
            volatility=0.58,
        )
    )

    assert result.regime_type == "NEWS_DRIVEN"
    assert result.confidence_score >= 0.90
    assert result.strategy_weight_modifiers["S1"] > result.strategy_weight_modifiers["S2"]


def test_price_divergence_classifies_arbitrage_regime() -> None:
    trigger = _make_trigger()
    result = trigger.detect_market_regime(
        MarketRegimeInputs(
            social_spike_intensity=0.45,
            price_dispersion=0.90,
            wallet_activity_strength=0.50,
            trade_frequency=0.62,
            volatility=0.66,
        )
    )

    assert result.regime_type == "ARBITRAGE_DOMINANT"
    assert result.strategy_weight_modifiers["S2"] > result.strategy_weight_modifiers["S1"]


def test_strong_wallet_signal_classifies_smart_money_regime() -> None:
    trigger = _make_trigger()
    result = trigger.detect_market_regime(
        MarketRegimeInputs(
            social_spike_intensity=0.35,
            price_dispersion=0.40,
            wallet_activity_strength=0.91,
            trade_frequency=0.57,
            volatility=0.59,
        )
    )

    assert result.regime_type == "SMART_MONEY_DOMINANT"
    assert result.strategy_weight_modifiers["S3"] > result.strategy_weight_modifiers["S1"]


def test_weak_signals_classify_chaotic_regime() -> None:
    trigger = _make_trigger()
    result = trigger.detect_market_regime(
        MarketRegimeInputs(
            social_spike_intensity=0.20,
            price_dispersion=0.21,
            wallet_activity_strength=0.18,
            trade_frequency=0.25,
            volatility=0.22,
        )
    )

    assert result.regime_type == "LOW_ACTIVITY_CHAOTIC"
    assert result.strategy_weight_modifiers == {"S1": 0.9, "S2": 0.9, "S3": 0.9}


def test_deterministic_classification() -> None:
    trigger_a = _make_trigger()
    trigger_b = _make_trigger()
    inputs = MarketRegimeInputs(
        social_spike_intensity=0.82,
        price_dispersion=0.31,
        wallet_activity_strength=0.44,
        trade_frequency=0.64,
        volatility=0.61,
    )

    assert trigger_a.detect_market_regime(inputs) == trigger_b.detect_market_regime(inputs)


def test_aggregation_exposes_required_regime_outputs() -> None:
    trigger = _make_trigger()
    result = trigger.aggregate_strategy_decisions(
        s1_decision=StrategyDecision(
            decision="ENTER",
            reason="social momentum",
            edge=0.06,
        ),
        s2_decision=CrossExchangeArbitrageDecision(
            decision="ENTER",
            reason="spread",
            edge=0.03,
            matched_markets_info={},
        ),
        s3_decision=SmartMoneyCopyTradingDecision(
            decision="ENTER",
            reason="wallet",
            confidence=0.7,
            wallet_info={},
        ),
        market_regime_inputs=MarketRegimeInputs(
            social_spike_intensity=0.85,
            price_dispersion=0.30,
            wallet_activity_strength=0.40,
            trade_frequency=0.56,
            volatility=0.60,
        ),
    )

    assert result.current_regime == "NEWS_DRIVEN"
    assert 0.0 <= result.regime_confidence <= 1.0
    assert isinstance(result.strategy_weight_modifiers, dict)
    assert set(result.strategy_weight_modifiers.keys()) == {"S1", "S2", "S3"}
