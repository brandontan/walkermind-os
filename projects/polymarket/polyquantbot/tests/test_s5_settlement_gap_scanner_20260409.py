from __future__ import annotations

from projects.polymarket.polyquantbot.execution.strategy_trigger import (
    KalshiResolvedMarket,
    PolymarketSettlementMarket,
    StrategyConfig,
    StrategyTrigger,
)


class _NoopEngine:
    async def snapshot(self):  # pragma: no cover - not used in this suite
        raise NotImplementedError


def _make_trigger() -> StrategyTrigger:
    config = StrategyConfig(
        market_id="m-settlement-gap-1",
        min_liquidity_usd=10_000.0,
        settlement_gap_underpriced_threshold=0.95,
        settlement_gap_min_mapping_confidence=0.60,
        cross_exchange_min_overlap_tokens=2,
    )
    return StrategyTrigger(engine=_NoopEngine(), config=config)


def _resolved_kalshi_market(*, outcome: str = "YES") -> KalshiResolvedMarket:
    return KalshiResolvedMarket(
        market_id="KXELECT2026NY",
        title="Will candidate A win New York governor election 2026",
        resolved=True,
        resolved_outcome=outcome,
        event_key="ny-governor-2026-candidate-a",
        timeframe="2026",
        resolution_criteria="winner-candidate-a",
    )


def _polymarket_market(
    *,
    yes_price: float,
    liquidity_usd: float = 20_000.0,
    orderbook_depth_usd: float = 18_000.0,
    is_open: bool = True,
) -> PolymarketSettlementMarket:
    return PolymarketSettlementMarket(
        market_id="poly-ny-gov-2026-a",
        title="Will candidate A win NY governor race in 2026",
        yes_price=yes_price,
        liquidity_usd=liquidity_usd,
        orderbook_depth_usd=orderbook_depth_usd,
        is_open=is_open,
        event_key="ny-governor-2026-candidate-a",
        timeframe="2026",
        resolution_criteria="winner-candidate-a",
    )


def test_resolved_market_with_price_gap_enters() -> None:
    trigger = _make_trigger()

    decision = trigger.evaluate_settlement_gap_scanner(
        kalshi_market=_resolved_kalshi_market(outcome="YES"),
        polymarket_markets=[_polymarket_market(yes_price=0.87)],
    )

    assert decision.decision == "ENTER"
    assert decision.edge == 0.13
    assert decision.source == "settlement_gap"


def test_resolved_market_without_gap_skips() -> None:
    trigger = _make_trigger()

    decision = trigger.evaluate_settlement_gap_scanner(
        kalshi_market=_resolved_kalshi_market(outcome="YES"),
        polymarket_markets=[_polymarket_market(yes_price=0.98)],
    )

    assert decision.decision == "SKIP"
    assert decision.reason == "already converged"
    assert decision.source == "settlement_gap"


def test_mapping_failure_skips() -> None:
    trigger = _make_trigger()
    uncertain_map = PolymarketSettlementMarket(
        market_id="poly-unrelated-market",
        title="Will it snow in Miami in August 2026",
        yes_price=0.60,
        liquidity_usd=25_000.0,
        orderbook_depth_usd=25_000.0,
        is_open=True,
        event_key="",
        timeframe="",
        resolution_criteria="",
    )

    decision = trigger.evaluate_settlement_gap_scanner(
        kalshi_market=_resolved_kalshi_market(outcome="YES"),
        polymarket_markets=[uncertain_map],
    )

    assert decision.decision == "SKIP"
    assert decision.reason == "mapping uncertain"
    assert decision.source == "settlement_gap"


def test_low_liquidity_skips() -> None:
    trigger = _make_trigger()

    decision = trigger.evaluate_settlement_gap_scanner(
        kalshi_market=_resolved_kalshi_market(outcome="YES"),
        polymarket_markets=[_polymarket_market(yes_price=0.84, liquidity_usd=9_000.0, orderbook_depth_usd=8_500.0)],
    )

    assert decision.decision == "SKIP"
    assert decision.reason == "liquidity insufficient"
    assert decision.source == "settlement_gap"


def test_decision_is_deterministic() -> None:
    trigger = _make_trigger()
    kalshi = _resolved_kalshi_market(outcome="NO")
    poly = _polymarket_market(yes_price=0.03)

    first = trigger.evaluate_settlement_gap_scanner(
        kalshi_market=kalshi,
        polymarket_markets=[poly],
    )
    second = trigger.evaluate_settlement_gap_scanner(
        kalshi_market=kalshi,
        polymarket_markets=[poly],
    )

    assert first == second
    assert first.decision == "SKIP"
    assert first.reason == "already converged"
