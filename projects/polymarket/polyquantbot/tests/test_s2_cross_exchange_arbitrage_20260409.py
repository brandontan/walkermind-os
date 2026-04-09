from __future__ import annotations

from projects.polymarket.polyquantbot.execution.strategy_trigger import (
    CrossExchangeMarketInput,
    StrategyConfig,
    StrategyTrigger,
)


class _NoopEngine:
    async def snapshot(self):  # pragma: no cover - not used by this suite
        raise NotImplementedError


def _make_trigger() -> StrategyTrigger:
    config = StrategyConfig(
        market_id="m-cross-exchange",
        min_liquidity_usd=10_000.0,
        cross_exchange_min_mapping_confidence=0.60,
        cross_exchange_min_net_edge=0.02,
    )
    return StrategyTrigger(engine=_NoopEngine(), config=config)


def _market(
    *,
    exchange: str,
    market_id: str,
    title: str,
    timeframe: str = "2026-12-31",
    resolution_criteria: str = "close_above_60000",
    yes_probability: float,
    liquidity_usd: float,
    fee_rate: float,
    slippage_rate: float,
) -> CrossExchangeMarketInput:
    return CrossExchangeMarketInput(
        exchange=exchange,
        market_id=market_id,
        title=title,
        timeframe=timeframe,
        resolution_criteria=resolution_criteria,
        yes_probability=yes_probability,
        liquidity_usd=liquidity_usd,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
    )


def test_matched_markets_edge_detected() -> None:
    trigger = _make_trigger()
    poly = _market(
        exchange="polymarket",
        market_id="poly-btc-60k",
        title="Will BTC close above 60k by 2026?",
        yes_probability=0.43,
        liquidity_usd=25_000.0,
        fee_rate=0.003,
        slippage_rate=0.002,
    )
    kalshi = _market(
        exchange="kalshi",
        market_id="kalshi-btc-60k",
        title="BTC above 60k settlement by 2026 close",
        yes_probability=0.52,
        liquidity_usd=22_000.0,
        fee_rate=0.003,
        slippage_rate=0.002,
    )

    decision = trigger.evaluate_cross_exchange_arbitrage(polymarket=poly, kalshi=kalshi)

    assert decision.decision == "ENTER"
    assert decision.edge > 0.02
    assert decision.matched_markets["polymarket_id"] == "poly-btc-60k"
    assert decision.matched_markets["kalshi_id"] == "kalshi-btc-60k"


def test_no_match_skipped() -> None:
    trigger = _make_trigger()
    poly = _market(
        exchange="polymarket",
        market_id="poly-btc-60k",
        title="Will BTC close above 60k by 2026?",
        yes_probability=0.43,
        liquidity_usd=25_000.0,
        fee_rate=0.002,
        slippage_rate=0.002,
    )
    kalshi = _market(
        exchange="kalshi",
        market_id="kalshi-weather-rain",
        title="Will New York rainfall exceed 4 inches next week?",
        timeframe="2026-05-01",
        resolution_criteria="rainfall_inches_gt_4",
        yes_probability=0.56,
        liquidity_usd=30_000.0,
        fee_rate=0.002,
        slippage_rate=0.002,
    )

    decision = trigger.evaluate_cross_exchange_arbitrage(polymarket=poly, kalshi=kalshi)

    assert decision.decision == "SKIP"
    assert "mapping confidence too low" in decision.reason


def test_edge_below_threshold_skipped() -> None:
    trigger = _make_trigger()
    poly = _market(
        exchange="polymarket",
        market_id="poly-btc-60k",
        title="Will BTC close above 60k by 2026?",
        yes_probability=0.49,
        liquidity_usd=20_000.0,
        fee_rate=0.003,
        slippage_rate=0.002,
    )
    kalshi = _market(
        exchange="kalshi",
        market_id="kalshi-btc-60k",
        title="BTC above 60k settlement by 2026 close",
        yes_probability=0.50,
        liquidity_usd=20_000.0,
        fee_rate=0.003,
        slippage_rate=0.002,
    )

    decision = trigger.evaluate_cross_exchange_arbitrage(polymarket=poly, kalshi=kalshi)

    assert decision.decision == "SKIP"
    assert decision.edge == 0.0
    assert "net edge below actionable threshold" in decision.reason


def test_fees_reduce_edge_skipped() -> None:
    trigger = _make_trigger()
    poly = _market(
        exchange="polymarket",
        market_id="poly-btc-60k",
        title="Will BTC close above 60k by 2026?",
        yes_probability=0.45,
        liquidity_usd=20_000.0,
        fee_rate=0.008,
        slippage_rate=0.007,
    )
    kalshi = _market(
        exchange="kalshi",
        market_id="kalshi-btc-60k",
        title="BTC above 60k settlement by 2026 close",
        yes_probability=0.48,
        liquidity_usd=20_000.0,
        fee_rate=0.008,
        slippage_rate=0.007,
    )

    decision = trigger.evaluate_cross_exchange_arbitrage(polymarket=poly, kalshi=kalshi)

    assert decision.decision == "SKIP"
    assert decision.edge == 0.0
    assert "net edge below actionable threshold" in decision.reason


def test_valid_arbitrage_enters() -> None:
    trigger = _make_trigger()
    poly = _market(
        exchange="polymarket",
        market_id="poly-btc-60k",
        title="Will BTC close above 60k by 2026?",
        yes_probability=0.41,
        liquidity_usd=18_000.0,
        fee_rate=0.002,
        slippage_rate=0.001,
    )
    kalshi = _market(
        exchange="kalshi",
        market_id="kalshi-btc-60k",
        title="BTC above 60k settlement by 2026 close",
        yes_probability=0.49,
        liquidity_usd=17_000.0,
        fee_rate=0.002,
        slippage_rate=0.001,
    )

    decision = trigger.evaluate_cross_exchange_arbitrage(polymarket=poly, kalshi=kalshi)

    assert decision.decision == "ENTER"
    assert decision.edge == 0.074
    assert "arbitrage opportunity" in decision.reason
