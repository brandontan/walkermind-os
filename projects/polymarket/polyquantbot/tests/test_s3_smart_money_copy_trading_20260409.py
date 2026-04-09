from __future__ import annotations

from projects.polymarket.polyquantbot.execution.strategy_trigger import (
    SmartMoneyCopyTradingDecision,
    StrategyConfig,
    StrategyTrigger,
    WalletTradeSignal,
)


class _NoopEngine:
    async def snapshot(self):  # pragma: no cover - not used by this suite
        raise NotImplementedError


def _make_trigger() -> StrategyTrigger:
    config = StrategyConfig(
        market_id="m-smart-money-1",
        min_liquidity_usd=10_000.0,
    )
    return StrategyTrigger(engine=_NoopEngine(), config=config)


def _signal(
    *,
    wallet_address: str = "0xsmart1",
    action: str = "buy",
    size_usd: float = 15_000.0,
    liquidity_usd: float = 40_000.0,
    timestamp_ms: int = 1_746_000_000_000,
    market_move_pct: float = 0.01,
    wallet_success_rate: float = 0.71,
    wallet_activity_count: int = 28,
    h_score: float = 84.0,
    consistency_score: float = 0.83,
    discipline_score: float = 0.78,
    trade_frequency_score: float = 0.55,
    market_diversity_score: float = 0.72,
) -> WalletTradeSignal:
    return WalletTradeSignal(
        wallet_address=wallet_address,
        action=action,
        size_usd=size_usd,
        liquidity_usd=liquidity_usd,
        timestamp_ms=timestamp_ms,
        market_move_pct=market_move_pct,
        wallet_success_rate=wallet_success_rate,
        wallet_activity_count=wallet_activity_count,
        h_score=h_score,
        consistency_score=consistency_score,
        discipline_score=discipline_score,
        trade_frequency_score=trade_frequency_score,
        market_diversity_score=market_diversity_score,
    )


def _assert_output_contract(decision: SmartMoneyCopyTradingDecision) -> None:
    assert set(decision.__dict__.keys()) == {"decision", "reason", "confidence", "wallet_info"}
    assert decision.decision in {"ENTER", "SKIP"}
    assert isinstance(decision.reason, str)
    assert isinstance(decision.confidence, float)
    assert isinstance(decision.wallet_info, dict)
    assert "wallet_quality_score" in decision.wallet_info


def test_high_h_score_wallet_is_accepted() -> None:
    trigger = _make_trigger()
    signal = _signal(h_score=88.0)

    decision = trigger.evaluate_smart_money_copy_trading(
        signal=signal,
        related_wallet_signals=[signal, _signal(wallet_address="0xsmart2", h_score=86.0)],
    )

    _assert_output_contract(decision)
    assert decision.decision == "ENTER"
    assert decision.wallet_info["h_score"] >= 88.0


def test_low_h_score_wallet_is_rejected() -> None:
    trigger = _make_trigger()

    decision = trigger.evaluate_smart_money_copy_trading(
        signal=_signal(h_score=51.0),
        related_wallet_signals=[_signal(wallet_address="0xsmart2", h_score=58.0)],
    )

    _assert_output_contract(decision)
    assert decision.decision == "SKIP"
    assert decision.reason == "wallet quality skip: h-score below threshold"


def test_high_quality_wallet_boosts_confidence() -> None:
    trigger = _make_trigger()
    high_quality = _signal(
        h_score=91.0,
        consistency_score=0.90,
        discipline_score=0.86,
        market_diversity_score=0.82,
    )
    baseline = _signal(
        wallet_address="0xbaseline",
        h_score=76.0,
        consistency_score=0.72,
        discipline_score=0.67,
        market_diversity_score=0.61,
    )

    high_quality_decision = trigger.evaluate_smart_money_copy_trading(
        signal=high_quality,
        related_wallet_signals=[high_quality, _signal(wallet_address="0xsmart2")],
    )
    baseline_decision = trigger.evaluate_smart_money_copy_trading(
        signal=baseline,
        related_wallet_signals=[baseline, _signal(wallet_address="0xsmart3")],
    )

    _assert_output_contract(high_quality_decision)
    _assert_output_contract(baseline_decision)
    assert high_quality_decision.decision == "ENTER"
    assert baseline_decision.decision == "ENTER"
    assert high_quality_decision.confidence > baseline_decision.confidence


def test_poor_consistency_wallet_is_skipped() -> None:
    trigger = _make_trigger()

    decision = trigger.evaluate_smart_money_copy_trading(
        signal=_signal(consistency_score=0.41),
        related_wallet_signals=[_signal(wallet_address="0xsmart2", consistency_score=0.66)],
    )

    _assert_output_contract(decision)
    assert decision.decision == "SKIP"
    assert decision.reason == "wallet quality skip: poor consistency"


def test_wallet_quality_scoring_is_deterministic() -> None:
    trigger = _make_trigger()
    signal = _signal()

    first = trigger.evaluate_smart_money_copy_trading(
        signal=signal,
        related_wallet_signals=[signal, _signal(wallet_address="0xsmart2")],
    )
    second = trigger.evaluate_smart_money_copy_trading(
        signal=signal,
        related_wallet_signals=[signal, _signal(wallet_address="0xsmart2")],
    )

    _assert_output_contract(first)
    _assert_output_contract(second)
    assert first.wallet_info["wallet_quality_score"] == second.wallet_info["wallet_quality_score"]
    assert first.confidence == second.confidence
