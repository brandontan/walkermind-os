from __future__ import annotations

from projects.polymarket.polyquantbot.execution.strategy_trigger import (
    CrossExchangeMarket,
    StrategyConfig,
    StrategyTrigger,
)


class _NoopEngine:
    async def snapshot(self):  # pragma: no cover - not used in this suite
        raise NotImplementedError


def _make_trigger() -> StrategyTrigger:
    config = StrategyConfig(
        market_id="m-arb-1",
        min_liquidity_usd=10_000.0,
        cross_exchange_min_net_edge=0.02,
        cross_exchange_min_actionable_spread=0.005,
        cross_exchange_min_mapping_confidence=0.55,
        cross_exchange_min_overlap_tokens=2,
    )
    return StrategyTrigger(engine=_NoopEngine(), config=config)


def _poly_market(probability: float = 0.62, liquidity_usd: float = 20_000.0) -> CrossExchangeMarket:
    return CrossExchangeMarket(
        exchange="polymarket",
        market_id="poly-btc-60k",
        title="Will BTC close above 60000 by end of April 2026",
        probability=probability,
        liquidity_usd=liquidity_usd,
        fee_bps=10.0,
        slippage_bps=8.0,
        timeframe="2026-04",
        resolution_criteria="btc-close-above-60000",
        event_key="btc-above-60k-apr-2026",
    )


def _kalshi_market(
    probability: float = 0.56,
    *,
    fee_bps: float = 8.0,
    slippage_bps: float = 7.0,
    liquidity_usd: float = 22_000.0,
) -> CrossExchangeMarket:
    return CrossExchangeMarket(
        exchange="kalshi",
        market_id="KXBTCAPR60",
        title="Will bitcoin settle above 60000 at April close 2026",
        probability=probability,
        liquidity_usd=liquidity_usd,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        timeframe="2026-04",
        resolution_criteria="btc-close-above-60000",
        event_key="btc-above-60k-apr-2026",
    )


def test_matched_markets_edge_detected() -> None:
    trigger = _make_trigger()

    decision = trigger.evaluate_cross_exchange_arbitrage(
        polymarket=_poly_market(probability=0.62),
        kalshi_markets=[_kalshi_market(probability=0.56)],
    )

    assert decision.decision == "ENTER"
    assert decision.edge > 0.02
    assert decision.matched_markets_info["polymarket"] == "poly-btc-60k"
    assert decision.matched_markets_info["kalshi"] == "KXBTCAPR60"


def test_no_match_is_skipped() -> None:
    trigger = _make_trigger()

    decision = trigger.evaluate_cross_exchange_arbitrage(
        polymarket=_poly_market(),
        kalshi_markets=[],
    )

    assert decision.decision == "SKIP"
    assert "no equivalent market" in decision.reason


def test_edge_below_threshold_is_skipped() -> None:
    trigger = _make_trigger()

    decision = trigger.evaluate_cross_exchange_arbitrage(
        polymarket=_poly_market(probability=0.62),
        kalshi_markets=[_kalshi_market(probability=0.61, fee_bps=0.0, slippage_bps=0.0)],
    )

    assert decision.decision == "SKIP"
    assert "below threshold" in decision.reason


def test_fees_eliminate_edge_is_skipped() -> None:
    trigger = _make_trigger()

    decision = trigger.evaluate_cross_exchange_arbitrage(
        polymarket=_poly_market(probability=0.62),
        kalshi_markets=[_kalshi_market(probability=0.59, fee_bps=120.0, slippage_bps=120.0)],
    )

    assert decision.decision == "SKIP"
    assert "below threshold" in decision.reason


def test_non_actionable_spread_is_skipped() -> None:
    trigger = _make_trigger()

    decision = trigger.evaluate_cross_exchange_arbitrage(
        polymarket=_poly_market(probability=0.6200),
        kalshi_markets=[_kalshi_market(probability=0.6210, fee_bps=0.0, slippage_bps=0.0)],
    )

    assert decision.decision == "SKIP"
    assert "spread not actionable" in decision.reason


def test_valid_arbitrage_is_enter() -> None:
    trigger = _make_trigger()

    decision = trigger.evaluate_cross_exchange_arbitrage(
        polymarket=_poly_market(probability=0.64),
        kalshi_markets=[_kalshi_market(probability=0.58)],
    )

    assert decision.decision == "ENTER"
    assert decision.edge > 0.02
    assert "arbitrage opportunity" in decision.reason
