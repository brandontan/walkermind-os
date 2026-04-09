from __future__ import annotations

from projects.polymarket.polyquantbot.execution.strategy_trigger import (
    CrossExchangeArbitrageDecision,
    SmartMoneyCopyTradingDecision,
    StrategyConfig,
    StrategyDecision,
    StrategyTrigger,
)
from projects.polymarket.polyquantbot.strategy.falcon_alpha_strategy import (
    build_falcon_signal_context,
)


class _NoopEngine:
    async def snapshot(self):  # pragma: no cover - not used in this suite
        raise NotImplementedError


def _make_trigger() -> StrategyTrigger:
    return StrategyTrigger(
        engine=_NoopEngine(),
        config=StrategyConfig(
            market_id="m-p14-3-falcon-alpha",
            min_edge=0.02,
            min_liquidity_usd=10_000.0,
        ),
    )


def test_smart_money_detection_works() -> None:
    context = build_falcon_signal_context(
        trades=[
            {"wallet": "0xaaa", "size": 2500},
            {"wallet": "0xaaa", "size": 2600},
            {"wallet": "0xbbb", "size": 2100},
            {"wallet": "0xaaa", "size": 2400},
        ],
        candles=[{"close": 0.49}, {"close": 0.50}, {"close": 0.52}],
        orderbook=[
            {"side": "bid", "price": 0.51, "depth": 12000},
            {"side": "ask", "price": 0.52, "depth": 14000},
        ],
    )

    assert context.smart_money_signal.strength > 0.6
    assert context.smart_money_signal.confidence > 0.6


def test_momentum_detection_works() -> None:
    context = build_falcon_signal_context(
        trades=[],
        candles=[{"close": 0.40}, {"close": 0.43}, {"close": 0.47}, {"close": 0.54}],
        orderbook=[],
    )

    assert context.momentum_signal.direction == "UP"
    assert context.momentum_signal.strength > 0.0


def test_liquidity_filter_applied() -> None:
    rich_context = build_falcon_signal_context(
        trades=[],
        candles=[],
        orderbook=[
            {"side": "bid", "price": 0.61, "depth": 15000},
            {"side": "ask", "price": 0.62, "depth": 15000},
        ],
    )
    thin_context = build_falcon_signal_context(
        trades=[],
        candles=[],
        orderbook=[
            {"side": "bid", "price": 0.58, "depth": 500},
            {"side": "ask", "price": 0.65, "depth": 500},
        ],
    )

    assert rich_context.liquidity_score > thin_context.liquidity_score
    assert 0.0 <= rich_context.liquidity_score <= 1.0


def test_falcon_signals_are_deterministic() -> None:
    payload = {
        "trades": [
            {"wallet": "0x111", "size": 1700},
            {"wallet": "0x111", "size": 1900},
            {"wallet": "0x222", "size": 900},
        ],
        "candles": [{"close": 0.50}, {"close": 0.53}, {"close": 0.55}],
        "orderbook": [
            {"side": "bid", "price": 0.54, "depth": 11000},
            {"side": "ask", "price": 0.55, "depth": 13000},
        ],
    }

    result_a = build_falcon_signal_context(**payload)
    result_b = build_falcon_signal_context(**payload)

    assert result_a == result_b


def test_falcon_fallback_when_data_is_insufficient() -> None:
    context = build_falcon_signal_context(
        trades=[],
        candles=[{"open": 0.48}, {"high": 0.51}],  # no close values
        orderbook=[],
    )

    assert context.data_sufficient is False
    assert context.insufficiency_reason == "insufficient_falcon_data"
    assert context.falcon_signal is None


def test_noisy_inputs_do_not_produce_external_weight_drift() -> None:
    context = build_falcon_signal_context(
        trades=[
            {"wallet": "0xnoise-a", "size": 20},
            {"wallet": "0xnoise-b", "size": 18},
        ],
        candles=[{"close": 0.500}, {"close": 0.501}, {"close": 0.5005}],
        orderbook=[
            {"side": "bid", "price": 0.49, "depth": 100},
            {"side": "ask", "price": 0.53, "depth": 120},
        ],
    )

    assert context.data_sufficient is True
    assert context.falcon_signal is not None
    assert context.falcon_signal.external_signal_weight == 1.0
    assert context.falcon_signal.strength == 0.0
    assert context.falcon_signal.confidence == 0.0


def test_integration_with_s4_uses_external_signal_weight_without_override() -> None:
    trigger = _make_trigger()
    falcon_context = build_falcon_signal_context(
        trades=[
            {"wallet": "0xsm1", "size": 2800},
            {"wallet": "0xsm1", "size": 3000},
            {"wallet": "0xsm2", "size": 2600},
        ],
        candles=[{"close": 0.48}, {"close": 0.50}, {"close": 0.53}, {"close": 0.56}],
        orderbook=[
            {"side": "bid", "price": 0.55, "depth": 17000},
            {"side": "ask", "price": 0.56, "depth": 18000},
        ],
    )
    assert falcon_context.falcon_signal is not None

    baseline = trigger.aggregate_strategy_decisions(
        s1_decision=StrategyDecision(decision="ENTER", reason="news", edge=0.040),
        s2_decision=CrossExchangeArbitrageDecision(
            decision="ENTER",
            reason="arb",
            edge=0.030,
            matched_markets_info={"exchange": "kalshi", "market_id": "k1"},
        ),
        s3_decision=SmartMoneyCopyTradingDecision(
            decision="ENTER",
            reason="wallet",
            confidence=0.80,
            wallet_info={"wallet": "0xsm1"},
        ),
    )

    integrated = trigger.aggregate_strategy_decisions(
        s1_decision=StrategyDecision(decision="ENTER", reason="news", edge=0.040),
        s2_decision=CrossExchangeArbitrageDecision(
            decision="ENTER",
            reason="arb",
            edge=0.030,
            matched_markets_info={"exchange": "kalshi", "market_id": "k1"},
        ),
        s3_decision=SmartMoneyCopyTradingDecision(
            decision="ENTER",
            reason="wallet",
            confidence=0.80,
            wallet_info={"wallet": "0xsm1"},
        ),
        falcon_signal=falcon_context.falcon_signal,
    )

    # Existing strategy ranking remains authoritative and deterministic.
    assert baseline.selected_trade == integrated.selected_trade == "S1"
    assert 0.90 <= integrated.external_signal_weight <= 1.15
    assert integrated.falcon_signal is not None
    assert integrated.falcon_signal["type"] in {"SMART_MONEY", "MOMENTUM"}

    # Runtime proof artifacts required by task.
    assert falcon_context.smart_money_signal.strength > 0.0
    assert falcon_context.momentum_signal.direction == "UP"
    assert integrated.falcon_signal["liquidity_score"] > 0.0


def test_runtime_proof_examples() -> None:
    context = build_falcon_signal_context(
        trades=[
            {"wallet": "0xproof-1", "size": 3200},
            {"wallet": "0xproof-1", "size": 2900},
            {"wallet": "0xproof-2", "size": 2700},
        ],
        candles=[{"close": 0.45}, {"close": 0.47}, {"close": 0.50}, {"close": 0.54}],
        orderbook=[
            {"side": "bid", "price": 0.53, "depth": 17000},
            {"side": "ask", "price": 0.54, "depth": 18000},
        ],
    )
    assert context.falcon_signal is not None
    assert context.smart_money_signal.strength > 0.60
    assert context.momentum_signal.direction == "UP"
    assert context.falcon_signal.signal_type in {"SMART_MONEY", "MOMENTUM"}
    assert 0.90 <= context.falcon_signal.external_signal_weight <= 1.15
