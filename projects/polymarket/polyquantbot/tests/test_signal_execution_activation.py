"""Tests for core/signal/signal_engine.py and core/execution/executor.py.

Test IDs: SEA-01 – SEA-30

Coverage:
  - Signal generation (edge filter, liquidity filter, EV, Kelly, logging)
  - Executor (dedup, paper mode, risk gate, concurrent cap, retry logic)
  - Pipeline: markets → signals → execute_trade
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from projects.polymarket.polyquantbot.core.signal.signal_engine import (
    SignalResult,
    _calculate_ev,
    _calculate_kelly,
    _position_size,
    generate_signals,
)
from projects.polymarket.polyquantbot.core.execution.executor import (
    ExecutionResult,
    TradeExecutor,
    _generate_trade_id,
    execute_trade,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _market(
    market_id: str = "0xabc",
    p_market: float = 0.40,
    p_model: float = 0.55,
    liquidity_usd: float = 15_000.0,
    bankroll: float = 10_000.0,
    side: str = "YES",
) -> dict:
    return {
        "market_id": market_id,
        "p_market": p_market,
        "p_model": p_model,
        "liquidity_usd": liquidity_usd,
        "bankroll": bankroll,
        "side": side,
    }


def _signal(
    market_id: str = "0xabc",
    side: str = "YES",
    price: float = 0.40,
    size_usd: float = 100.0,
    edge: float = 0.15,
    ev: float = 0.25,
    liquidity_usd: float = 15_000.0,
) -> dict:
    return {
        "market_id": market_id,
        "side": side,
        "price": price,
        "size_usd": size_usd,
        "edge": edge,
        "ev": ev,
        "liquidity_usd": liquidity_usd,
    }


# ── SEA-01 to SEA-10: Signal generation helpers ───────────────────────────────


def test_sea01_calculate_ev_positive():
    """SEA-01: EV is positive when p_model > p_market."""
    ev = _calculate_ev(p_model=0.60, p_market=0.40)
    assert ev > 0.0


def test_sea02_calculate_ev_zero_market_price():
    """SEA-02: EV returns 0.0 when p_market is 0."""
    ev = _calculate_ev(p_model=0.5, p_market=0.0)
    assert ev == 0.0


def test_sea03_calculate_ev_formula():
    """SEA-03: EV = p_model * b - (1 - p_model) where b = 1/p_market - 1."""
    p_model, p_market = 0.6, 0.4
    b = 1.0 / p_market - 1.0
    expected = p_model * b - (1.0 - p_model)
    assert abs(_calculate_ev(p_model, p_market) - expected) < 1e-9


def test_sea04_calculate_kelly_positive_edge():
    """SEA-04: Kelly fraction is positive when p * b > q."""
    b = 1.5
    kelly = _calculate_kelly(p=0.6, b=b)
    assert kelly > 0.0
    assert kelly <= 1.0


def test_sea05_calculate_kelly_zero_odds():
    """SEA-05: Kelly returns 0 when b <= 0."""
    assert _calculate_kelly(p=0.6, b=0.0) == 0.0


def test_sea06_calculate_kelly_clamped():
    """SEA-06: Kelly is always in [0, 1]."""
    for p, b in [(0.99, 100.0), (0.01, 0.01), (0.5, 1.5)]:
        k = _calculate_kelly(p, b)
        assert 0.0 <= k <= 1.0


def test_sea07_position_size_applies_kelly_fraction():
    """SEA-07: Final size = bankroll * 0.25 * kelly_f, capped at 10%."""
    bankroll = 10_000.0
    kelly_f = 0.50
    size = _position_size(bankroll, kelly_f, kelly_fraction=0.25, max_position_pct=0.10)
    expected = bankroll * 0.25 * kelly_f  # = 1250
    cap = bankroll * 0.10  # = 1000
    assert size == min(expected, cap)


def test_sea08_position_size_clamped_at_max():
    """SEA-08: Size never exceeds bankroll * max_position_pct."""
    size = _position_size(10_000.0, kelly_f=1.0, kelly_fraction=1.0, max_position_pct=0.10)
    assert size == 1_000.0


def test_sea09_position_size_zero_kelly():
    """SEA-09: Zero kelly_f yields zero size."""
    assert _position_size(10_000.0, kelly_f=0.0) == 0.0


# ── SEA-10 to SEA-20: generate_signals ───────────────────────────────────────


async def test_sea10_generate_signals_basic():
    """SEA-10: Market with positive edge and sufficient liquidity generates a signal."""
    markets = [_market()]
    signals = await generate_signals(markets)
    assert len(signals) == 1
    sig = signals[0]
    assert isinstance(sig, SignalResult)
    assert sig.market_id == "0xabc"
    assert sig.edge > 0


async def test_sea11_skip_low_edge():
    """SEA-11: Market with edge <= threshold is skipped."""
    markets = [_market(p_market=0.50, p_model=0.51)]  # edge = 0.01 < default 0.02
    signals = await generate_signals(markets, edge_threshold=0.02)
    assert len(signals) == 0


async def test_sea12_skip_zero_edge():
    """SEA-12: Market with zero edge is skipped."""
    markets = [_market(p_market=0.50, p_model=0.50)]
    signals = await generate_signals(markets)
    assert len(signals) == 0


async def test_sea13_skip_negative_edge():
    """SEA-13: Market with negative edge (p_model < p_market) is skipped."""
    markets = [_market(p_market=0.60, p_model=0.40)]
    signals = await generate_signals(markets)
    assert len(signals) == 0


async def test_sea14_skip_low_liquidity():
    """SEA-14: Market below liquidity threshold is skipped."""
    markets = [_market(liquidity_usd=5_000.0)]
    signals = await generate_signals(markets, min_liquidity_usd=10_000.0)
    assert len(signals) == 0


async def test_sea15_ev_positive_for_valid_signal():
    """SEA-15: EV is positive for every generated signal."""
    markets = [_market(p_market=0.40, p_model=0.60)]
    signals = await generate_signals(markets)
    assert all(s.ev > 0.0 for s in signals)


async def test_sea16_size_within_max_position():
    """SEA-16: size_usd is <= 10% of bankroll for each signal."""
    bankroll = 10_000.0
    markets = [_market(bankroll=bankroll, p_market=0.40, p_model=0.70)]
    signals = await generate_signals(markets, max_position_pct=0.10)
    for sig in signals:
        assert sig.size_usd <= bankroll * 0.10 + 1e-6


async def test_sea17_multiple_markets_filtered():
    """SEA-17: Multiple markets — only those passing filters appear in output."""
    markets = [
        _market(market_id="0x1", p_market=0.40, p_model=0.60, liquidity_usd=20_000),
        _market(market_id="0x2", p_market=0.50, p_model=0.51, liquidity_usd=20_000),  # low edge
        _market(market_id="0x3", p_market=0.40, p_model=0.60, liquidity_usd=5_000),   # low liq
        _market(market_id="0x4", p_market=0.35, p_model=0.65, liquidity_usd=50_000),
    ]
    signals = await generate_signals(markets, edge_threshold=0.02, min_liquidity_usd=10_000)
    assert len(signals) == 2
    ids = {s.market_id for s in signals}
    assert ids == {"0x1", "0x4"}


async def test_sea18_price_out_of_range_skipped():
    """SEA-18: Market price outside [0.05, 0.95] is skipped."""
    markets = [_market(p_market=0.01, p_model=0.04)]  # p_market < 0.05
    signals = await generate_signals(markets)
    assert len(signals) == 0


async def test_sea19_extra_keys_passed_through():
    """SEA-19: Extra keys in market dict appear in SignalResult.extra."""
    market = _market()
    market["token_id"] = "tok123"
    market["title"] = "Will X happen?"
    signals = await generate_signals([market])
    assert len(signals) == 1
    assert signals[0].extra["token_id"] == "tok123"
    assert signals[0].extra["title"] == "Will X happen?"


async def test_sea20_empty_market_list():
    """SEA-20: Empty input returns empty signal list."""
    signals = await generate_signals([])
    assert signals == []


# ── SEA-21 to SEA-30: TradeExecutor ──────────────────────────────────────────


async def test_sea21_paper_trade_executes():
    """SEA-21: Paper mode executes successfully and returns success=True."""
    executor = TradeExecutor(mode="paper")
    result = await executor.execute_trade(_signal())
    assert result.success is True
    assert result.mode == "paper"


async def test_sea22_dedup_blocks_duplicate():
    """SEA-22: Identical signal executed twice — second is rejected as duplicate."""
    executor = TradeExecutor(mode="paper")
    sig = _signal()
    r1 = await executor.execute_trade(sig)
    r2 = await executor.execute_trade(sig)
    assert r1.success is True
    assert r2.success is False
    assert "duplicate" in r2.reason


async def test_sea23_trade_id_deterministic():
    """SEA-23: Same inputs always produce the same trade_id."""
    t1 = _generate_trade_id("0xabc", "YES", 0.40, 100.0)
    t2 = _generate_trade_id("0xabc", "YES", 0.40, 100.0)
    assert t1 == t2


async def test_sea24_different_market_different_id():
    """SEA-24: Different market IDs produce different trade IDs."""
    t1 = _generate_trade_id("0xabc", "YES", 0.40, 100.0)
    t2 = _generate_trade_id("0xdef", "YES", 0.40, 100.0)
    assert t1 != t2


async def test_sea25_skip_no_edge():
    """SEA-25: Signal with edge=0 is skipped at execution time."""
    executor = TradeExecutor(mode="paper", min_edge=0.0)
    sig = _signal(edge=0.0)
    result = await executor.execute_trade(sig)
    assert result.success is False
    assert "no_positive_edge" in result.reason


async def test_sea26_skip_low_liquidity():
    """SEA-26: Signal with insufficient liquidity is skipped."""
    executor = TradeExecutor(mode="paper")
    sig = _signal(liquidity_usd=500.0)
    result = await executor.execute_trade(sig)
    assert result.success is False
    assert "insufficient_liquidity" in result.reason


async def test_sea27_skip_kill_switch():
    """SEA-27: Kill switch active on risk_guard blocks execution."""
    risk_guard = MagicMock()
    risk_guard.disabled = True
    executor = TradeExecutor(mode="paper", risk_guard=risk_guard)
    result = await executor.execute_trade(_signal())
    assert result.success is False
    assert "kill_switch" in result.reason


async def test_sea28_max_concurrent_respected():
    """SEA-28: Max concurrent limit blocks additional trades."""
    executor = TradeExecutor(mode="paper", max_concurrent=0)
    result = await executor.execute_trade(_signal())
    assert result.success is False
    assert "max_concurrent" in result.reason


async def test_sea29_paper_balance_decreases():
    """SEA-29: Paper wallet balance decreases by size_usd after execution."""
    executor = TradeExecutor(mode="paper")
    initial = executor.paper_balance
    sig = _signal(size_usd=200.0)
    result = await executor.execute_trade(sig)
    assert result.success is True
    assert executor.paper_balance == initial - 200.0


async def test_sea30_pipeline_markets_to_execution():
    """SEA-30: Full pipeline — generate_signals then execute_trade for each signal."""
    markets = [
        _market(market_id="0x1", p_market=0.40, p_model=0.60, liquidity_usd=20_000),
        _market(market_id="0x2", p_market=0.50, p_model=0.51, liquidity_usd=20_000),  # low edge
    ]
    signals = await generate_signals(markets, edge_threshold=0.02)
    assert len(signals) == 1

    executor = TradeExecutor(mode="paper")
    results = []
    for sig in signals:
        payload = {
            "market_id": sig.market_id,
            "side": sig.side,
            "price": sig.p_market,
            "size_usd": sig.size_usd,
            "edge": sig.edge,
            "ev": sig.ev,
            "liquidity_usd": sig.liquidity_usd,
        }
        results.append(await executor.execute_trade(payload))

    assert len(results) == 1
    assert results[0].success is True
    assert results[0].market_id == "0x1"
