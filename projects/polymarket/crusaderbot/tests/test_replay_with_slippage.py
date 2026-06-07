"""Unit tests for the slippage replay engine (WARP-83 Sub-Lane B).

Drives synthetic trades through a KNOWN injected slippage model and asserts the
exact slippage-adjusted P&L per trade and the per-cell aggregation, plus the
>50% catastrophic gate. No DB, no network — pure functions only.
"""
from __future__ import annotations

import pytest

from projects.polymarket.crusaderbot.scripts.replay_with_slippage import (
    CellAggregate,
    DefaultSlippageModel,
    SlippageInputs,
    SlippageModel,
    aggregate_by_cell,
    normalize_cell,
    overall_gate,
    parse_cells,
    replay_trade,
    SLIPPAGE_PNL_GATE_FRAC,
)


class _FixedBpsModel:
    """A deterministic slippage model returning a constant bps — the KNOWN model.

    Satisfies the :class:`SlippageModel` Protocol structurally.
    """

    def __init__(self, bps: float) -> None:
        self.bps = bps

    def __call__(self, x: SlippageInputs) -> float:
        return self.bps


def _inputs(size_usdc: float, side: str = "YES") -> SlippageInputs:
    return SlippageInputs(
        side=side,
        entry_price=0.50,
        size_usdc=size_usdc,
        liquidity_usdc=1000.0,
        spread=0.01,
        volatility_sigma=0.0,
        orderbook_depth_usdc=1000.0,
    )


def test_model_protocol_satisfied() -> None:
    assert isinstance(_FixedBpsModel(10.0), SlippageModel)
    assert isinstance(DefaultSlippageModel(), SlippageModel)


def test_winning_trade_exact_adjusted_pnl() -> None:
    # 100 bps on a 200 USDC notional = 2.00 USDC cost.
    model = _FixedBpsModel(100.0)
    rec = replay_trade(
        market_id="mkt-win",
        cell="BTC/5m",
        inputs=_inputs(200.0),
        paper_pnl_usdc=10.0,
        model=model,
    )
    assert rec.slippage_bps == 100.0
    assert rec.slippage_cost_usdc == pytest.approx(2.0)
    assert rec.adjusted_pnl_usdc == pytest.approx(8.0)  # 10 - 2
    assert rec.adjusted_pnl_usdc > 0  # still a winner after slippage


def test_losing_trade_exact_adjusted_pnl() -> None:
    # A losing trade gets MORE negative: -5 paper, 50 bps on 400 = 2.00 cost.
    model = _FixedBpsModel(50.0)
    rec = replay_trade(
        market_id="mkt-loss",
        cell="ETH/5m",
        inputs=_inputs(400.0),
        paper_pnl_usdc=-5.0,
        model=model,
    )
    assert rec.slippage_cost_usdc == pytest.approx(2.0)
    assert rec.adjusted_pnl_usdc == pytest.approx(-7.0)  # -5 - 2


def test_negative_bps_clamped_to_zero() -> None:
    # A misbehaving model returning negative bps must never credit the trade.
    rec = replay_trade(
        market_id="mkt-neg",
        cell="BTC/5m",
        inputs=_inputs(100.0),
        paper_pnl_usdc=3.0,
        model=_FixedBpsModel(-25.0),
    )
    assert rec.slippage_bps == 0.0
    assert rec.slippage_cost_usdc == 0.0
    assert rec.adjusted_pnl_usdc == pytest.approx(3.0)


def test_multi_cell_aggregation_exact() -> None:
    model = _FixedBpsModel(100.0)  # 1% of notional per trade
    records = [
        # BTC/5m: two winners
        replay_trade(market_id="b1", cell="BTC/5m", inputs=_inputs(100.0),
                     paper_pnl_usdc=10.0, model=model),   # cost 1.0 -> adj 9.0
        replay_trade(market_id="b2", cell="BTC/5m", inputs=_inputs(200.0),
                     paper_pnl_usdc=6.0, model=model),    # cost 2.0 -> adj 4.0
        # ETH/5m: a winner + a loser
        replay_trade(market_id="e1", cell="ETH/5m", inputs=_inputs(300.0),
                     paper_pnl_usdc=20.0, model=model),   # cost 3.0 -> adj 17.0
        replay_trade(market_id="e2", cell="ETH/5m", inputs=_inputs(100.0),
                     paper_pnl_usdc=-4.0, model=model),   # cost 1.0 -> adj -5.0
    ]
    agg = aggregate_by_cell(records)
    assert set(agg) == {"BTC/5m", "ETH/5m"}

    btc = agg["BTC/5m"]
    assert isinstance(btc, CellAggregate)
    assert btc.n_trades == 2
    assert btc.gross_paper_pnl_usdc == pytest.approx(16.0)
    assert btc.total_slippage_usdc == pytest.approx(3.0)
    assert btc.adjusted_pnl_usdc == pytest.approx(13.0)
    assert btc.slippage_fraction == pytest.approx(3.0 / 16.0)
    assert btc.gate_breached is False

    eth = agg["ETH/5m"]
    assert eth.n_trades == 2
    assert eth.gross_paper_pnl_usdc == pytest.approx(16.0)  # 20 - 4
    assert eth.total_slippage_usdc == pytest.approx(4.0)    # 3 + 1
    assert eth.adjusted_pnl_usdc == pytest.approx(12.0)     # 17 - 5
    assert eth.slippage_fraction == pytest.approx(4.0 / 16.0)
    assert eth.gate_breached is False

    frac, breached = overall_gate(agg)
    # total slip 7.0 over total |gross| (16 + 16) = 32 -> 0.21875
    assert frac == pytest.approx(7.0 / 32.0)
    assert breached is False


def test_gate_breach_when_slippage_exceeds_half_pnl() -> None:
    # Slippage cost > 50% of |gross paper P&L| trips the catastrophic gate.
    model = _FixedBpsModel(600.0)  # 6% of notional
    records = [
        replay_trade(market_id="g1", cell="BTC/5m", inputs=_inputs(100.0),
                     paper_pnl_usdc=10.0, model=model),  # cost 6.0 -> adj 4.0
    ]
    agg = aggregate_by_cell(records)
    btc = agg["BTC/5m"]
    assert btc.total_slippage_usdc == pytest.approx(6.0)
    assert btc.slippage_fraction == pytest.approx(0.6)
    assert btc.slippage_fraction > SLIPPAGE_PNL_GATE_FRAC
    assert btc.gate_breached is True

    frac, breached = overall_gate(agg)
    assert breached is True


def test_zero_gross_pnl_cell_never_breaches() -> None:
    # Offsetting +/- P&L netting to zero gross must not divide-by-zero or breach.
    model = _FixedBpsModel(100.0)
    records = [
        replay_trade(market_id="z1", cell="SOL/15m", inputs=_inputs(100.0),
                     paper_pnl_usdc=5.0, model=model),
        replay_trade(market_id="z2", cell="SOL/15m", inputs=_inputs(100.0),
                     paper_pnl_usdc=-5.0, model=model),
    ]
    agg = aggregate_by_cell(records)
    sol = agg["SOL/15m"]
    assert sol.gross_paper_pnl_usdc == pytest.approx(0.0)
    assert sol.slippage_fraction == 0.0
    assert sol.gate_breached is False


def test_normalize_and_parse_cells() -> None:
    assert normalize_cell("btc", "5M") == "BTC/5m"
    assert parse_cells("BTC/5m, eth/5m ,,bad") == ("BTC/5m", "ETH/5m")
    assert parse_cells("btc/5m,BTC/5m") == ("BTC/5m",)  # dedupe


def test_default_model_is_nonneg_and_capped() -> None:
    model = DefaultSlippageModel()
    # Tiny order, no vol -> small but positive (base floor).
    small = model(SlippageInputs("YES", 0.5, 1.0, 1_000_000.0, 0.0, 0.0, 1_000_000.0))
    assert small >= 0.0
    # Order far larger than depth + high vol -> capped at max_bps.
    huge = model(SlippageInputs("YES", 0.5, 10_000.0, 1.0, 100.0, 1.0, 1.0))
    assert huge == pytest.approx(model.max_bps)
