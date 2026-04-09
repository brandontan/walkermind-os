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
    )


def _assert_output_contract(decision: SmartMoneyCopyTradingDecision) -> None:
    assert set(decision.__dict__.keys()) == {"decision", "reason", "confidence", "wallet_info"}
    assert decision.decision in {"ENTER", "SKIP"}
    assert isinstance(decision.reason, str)
    assert isinstance(decision.confidence, float)
    assert isinstance(decision.wallet_info, dict)


def test_high_quality_wallet_triggers_entry() -> None:
    trigger = _make_trigger()
    signal = _signal()

    decision = trigger.evaluate_smart_money_copy_trading(
        signal=signal,
        related_wallet_signals=[signal, _signal(wallet_address="0xsmart2", size_usd=12_000.0)],
    )

    _assert_output_contract(decision)
    assert decision.decision == "ENTER"
    assert "smart-money signal" in decision.reason
    assert decision.confidence > 0.65


def test_low_quality_wallet_is_skipped() -> None:
    trigger = _make_trigger()

    decision = trigger.evaluate_smart_money_copy_trading(
        signal=_signal(wallet_success_rate=0.52, wallet_activity_count=8),
        related_wallet_signals=[_signal(wallet_success_rate=0.52, wallet_activity_count=8)],
    )

    _assert_output_contract(decision)
    assert decision.decision == "SKIP"
    assert decision.reason == "low-quality wallet"


def test_late_entry_is_skipped() -> None:
    trigger = _make_trigger()

    decision = trigger.evaluate_smart_money_copy_trading(
        signal=_signal(market_move_pct=0.05),
        related_wallet_signals=[_signal(wallet_address="0xsmart2", market_move_pct=0.04)],
    )

    _assert_output_contract(decision)
    assert decision.decision == "SKIP"
    assert decision.reason == "late entry"


def test_conflicting_signals_are_skipped() -> None:
    trigger = _make_trigger()
    anchor = _signal(action="buy")

    decision = trigger.evaluate_smart_money_copy_trading(
        signal=anchor,
        related_wallet_signals=[
            anchor,
            _signal(wallet_address="0xsmart2", action="sell"),
            _signal(wallet_address="0xsmart3", action="buy"),
        ],
    )

    _assert_output_contract(decision)
    assert decision.decision == "SKIP"
    assert decision.reason == "conflicting signals"


def test_valid_early_signal_is_enter() -> None:
    trigger = _make_trigger()
    signal = _signal(size_usd=18_000.0, market_move_pct=0.004)

    decision = trigger.evaluate_smart_money_copy_trading(
        signal=signal,
        related_wallet_signals=[
            signal,
            _signal(wallet_address="0xsmart2", size_usd=20_000.0, market_move_pct=0.003),
            _signal(wallet_address="0xsmart3", size_usd=16_000.0, market_move_pct=0.005),
        ],
    )

    _assert_output_contract(decision)
    assert decision.decision == "ENTER"
    assert decision.reason == "high-quality early smart-money signal"
    assert decision.wallet_info["wallet_address"] == "0xsmart1"
