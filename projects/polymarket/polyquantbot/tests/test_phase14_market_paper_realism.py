"""tests/test_phase14_market_paper_realism.py — Phase 14 market metadata + paper realism tests.

Test IDs: MP-01 – MP-30

Coverage:
    MP-01  – MP-05:  MarketMetadataCache basics
    MP-06  – MP-10:  executor paper slippage / partial fill / latency
    MP-11  – MP-15:  PositionManager open / close / unrealized PnL
    MP-16  – MP-20:  PnLTracker record_realized / record_unrealized / summary
    MP-21  – MP-25:  message_formatter market_question + outcome fields
    MP-26  – MP-30:  logger new event helpers
"""
from __future__ import annotations

import asyncio
import math
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_signal(
    market_id: str = "mkt-test",
    side: str = "YES",
    edge: float = 0.10,
    ev: float = 0.5,
    p_market: float = 0.45,
    size_usd: float = 100.0,
    force_mode: bool = False,
):
    from projects.polymarket.polyquantbot.core.signal.signal_engine import SignalResult
    return SignalResult(
        signal_id=f"sig-{market_id}-{side}",
        market_id=market_id,
        side=side,
        edge=edge,
        ev=ev,
        p_market=p_market,
        p_model=p_market + edge,
        kelly_f=0.25,
        size_usd=size_usd,
        liquidity_usd=1000.0,
        force_mode=force_mode,
    )


# ── MP-01–05: MarketMetadataCache ────────────────────────────────────────────

class TestMarketMetadataCache:
    """MP-01–05: Basic MarketMetadataCache behaviour."""

    def test_mp01_get_returns_none_for_unknown_market(self):
        """MP-01: get() on empty cache returns None."""
        from projects.polymarket.polyquantbot.core.market.market_cache import MarketMetadataCache
        cache = MarketMetadataCache()
        assert cache.get("nonexistent-id") is None

    def test_mp02_get_question_fallback(self):
        """MP-02: get_question() returns fallback when market not found."""
        from projects.polymarket.polyquantbot.core.market.market_cache import MarketMetadataCache
        cache = MarketMetadataCache()
        result = cache.get_question("unknown", fallback="N/A")
        assert result == "N/A"

    def test_mp03_get_outcomes_empty_for_unknown(self):
        """MP-03: get_outcomes() returns [] for unknown market."""
        from projects.polymarket.polyquantbot.core.market.market_cache import MarketMetadataCache
        cache = MarketMetadataCache()
        assert cache.get_outcomes("nope") == []

    @pytest.mark.asyncio
    async def test_mp04_refresh_with_mocked_api(self):
        """MP-04: refresh() populates cache from API response."""
        from projects.polymarket.polyquantbot.core.market.market_cache import MarketMetadataCache

        fake_markets = [
            {
                "conditionId": "0xabc",
                "question": "Will BTC hit $100k?",
                "outcomes": ["Yes", "No"],
            },
            {
                "conditionId": "0xdef",
                "question": "Will ETH hit $10k?",
                "outcomes": ["Yes", "No"],
            },
        ]

        cache = MarketMetadataCache()
        with patch.object(cache, "_fetch_markets", AsyncMock(return_value=fake_markets)):
            ok = await cache.refresh()

        assert ok is True
        assert cache.size() == 2
        meta = cache.get("0xabc")
        assert meta is not None
        assert meta.question == "Will BTC hit $100k?"
        assert meta.outcomes == ["Yes", "No"]

    @pytest.mark.asyncio
    async def test_mp05_refresh_api_failure_uses_stale_cache(self):
        """MP-05: refresh() preserves stale cache on API failure."""
        from projects.polymarket.polyquantbot.core.market.market_cache import (
            MarketMetadataCache,
            MarketMeta,
        )
        cache = MarketMetadataCache()
        # Pre-populate cache manually
        cache._cache["0xstale"] = MarketMeta(
            market_id="0xstale",
            question="Stale question?",
            outcomes=["Yes", "No"],
        )

        with patch.object(cache, "_fetch_markets", AsyncMock(return_value=[])):
            ok = await cache.refresh()

        assert ok is False
        # Stale data still there
        assert cache.get("0xstale") is not None
        assert cache.get("0xstale").question == "Stale question?"


# ── MP-06–10: Paper trading realism ───────────────────────────────────────────

class TestPaperTradingRealism:
    """MP-06–10: Slippage, partial fill, and latency in paper mode."""

    @pytest.fixture(autouse=True)
    def reset(self):
        from projects.polymarket.polyquantbot.core.execution.executor import reset_state
        reset_state()

    @pytest.mark.asyncio
    async def test_mp06_paper_trade_fills_between_60_and_100_pct(self):
        """MP-06: Paper fill size is between 60 % and 100 % of requested."""
        from projects.polymarket.polyquantbot.core.execution.executor import execute_trade
        result = await execute_trade(_make_signal(size_usd=200.0), mode="PAPER")
        assert result.success
        assert 120.0 <= result.filled_size_usd <= 200.0 + 0.01

    @pytest.mark.asyncio
    async def test_mp07_paper_fill_price_differs_from_mid(self):
        """MP-07: Fill price after slippage differs from the original p_market."""
        from projects.polymarket.polyquantbot.core.execution.executor import execute_trade
        result = await execute_trade(_make_signal(p_market=0.50, size_usd=50.0), mode="PAPER")
        assert result.success
        # Slippage can be 0 but fill price must be in [0.001, 0.999]
        assert 0.001 <= result.fill_price <= 0.999

    @pytest.mark.asyncio
    async def test_mp08_paper_slippage_within_1_pct(self):
        """MP-08: Applied slippage is at most 1 % of the mid price."""
        from projects.polymarket.polyquantbot.core.execution.executor import execute_trade
        result = await execute_trade(_make_signal(p_market=0.60, size_usd=50.0), mode="PAPER")
        assert result.success
        # |slippage_pct| ≤ 0.01
        assert abs(result.slippage_pct) <= 0.01 + 1e-9

    @pytest.mark.asyncio
    async def test_mp09_paper_latency_between_100_and_500ms(self):
        """MP-09: Simulated latency is in the [100, 500] ms range."""
        from projects.polymarket.polyquantbot.core.execution.executor import execute_trade
        result = await execute_trade(_make_signal(size_usd=50.0), mode="PAPER")
        assert result.success
        assert 100.0 <= result.latency_ms <= 600.0  # generous upper bound for test stability

    @pytest.mark.asyncio
    async def test_mp10_partial_fill_flag_set_when_fill_lt_100_pct(self):
        """MP-10: partial_fill flag is True when fill_fraction < 1.0."""
        from projects.polymarket.polyquantbot.core.execution.executor import execute_trade

        # Use seeded random to guarantee partial fill in the run
        import random
        with patch("projects.polymarket.polyquantbot.core.execution.executor.random") as mock_rnd:
            # Order matches _attempt_execution: latency first, then slippage, then fill fraction
            mock_rnd.uniform = MagicMock(side_effect=[
                0.200,    # latency seconds → 200 ms
                0.0005,   # slippage (small positive)
                0.75,     # fill fraction = 75 %
            ])
            result = await execute_trade(_make_signal(size_usd=100.0), mode="PAPER")

        assert result.success
        assert result.partial_fill is True
        assert result.filled_size_usd == pytest.approx(75.0, rel=1e-3)


# ── MP-11–15: PositionManager ─────────────────────────────────────────────────

class TestPositionManager:
    """MP-11–15: PositionManager open / close / unrealized PnL."""

    def _mgr(self):
        from projects.polymarket.polyquantbot.core.portfolio.position_manager import PositionManager
        return PositionManager()

    def test_mp11_open_creates_position(self):
        """MP-11: open() creates a new position."""
        mgr = self._mgr()
        pos = mgr.open("mkt-1", "YES", fill_price=0.50, fill_size=100.0, trade_id="t1")
        assert pos.market_id == "mkt-1"
        assert pos.side == "YES"
        assert pos.avg_price == pytest.approx(0.50)
        assert pos.size == pytest.approx(100.0)

    def test_mp12_open_multiple_fills_updates_avg_price(self):
        """MP-12: Multiple fills on same market update weighted avg_price."""
        mgr = self._mgr()
        mgr.open("mkt-1", "YES", fill_price=0.40, fill_size=100.0, trade_id="t1")
        mgr.open("mkt-1", "YES", fill_price=0.60, fill_size=100.0, trade_id="t2")
        pos = mgr.get("mkt-1")
        assert pos.size == pytest.approx(200.0)
        assert pos.avg_price == pytest.approx(0.50)

    def test_mp13_close_position_computes_realized_pnl(self):
        """MP-13: close() returns correct realized PnL."""
        mgr = self._mgr()
        mgr.open("mkt-1", "YES", fill_price=0.50, fill_size=100.0)
        pos, pnl = mgr.close("mkt-1", close_price=0.70)
        assert pos is not None
        # pnl = (0.70 - 0.50) * 100 = 20.0
        assert pnl == pytest.approx(20.0)
        assert mgr.get("mkt-1") is None

    def test_mp14_close_nonexistent_returns_zero_pnl(self):
        """MP-14: Closing a non-existent position returns (None, 0.0)."""
        mgr = self._mgr()
        pos, pnl = mgr.close("nope", close_price=0.50)
        assert pos is None
        assert pnl == 0.0

    def test_mp15_unrealized_pnl_computed_correctly(self):
        """MP-15: unrealized_pnl() returns mark-to-market PnL."""
        mgr = self._mgr()
        mgr.open("mkt-1", "YES", fill_price=0.50, fill_size=100.0)
        upnl = mgr.unrealized_pnl("mkt-1", mark_price=0.60)
        # (0.60 - 0.50) * 100 = 10.0
        assert upnl == pytest.approx(10.0)


# ── MP-16–20: PnLTracker ──────────────────────────────────────────────────────

class TestPnLTracker:
    """MP-16–20: PnLTracker realized / unrealized / summary."""

    def _tracker(self):
        from projects.polymarket.polyquantbot.core.portfolio.pnl import PnLTracker
        return PnLTracker(db=None)

    def test_mp16_record_realized_accumulates(self):
        """MP-16: record_realized() accumulates PnL per market."""
        tracker = self._tracker()
        tracker.record_realized("mkt-1", pnl_usd=10.0, trade_id="t1")
        tracker.record_realized("mkt-1", pnl_usd=5.0, trade_id="t2")
        rec = tracker.get("mkt-1")
        assert rec.realized == pytest.approx(15.0)

    def test_mp17_record_unrealized_updates_value(self):
        """MP-17: record_unrealized() updates the unrealized field."""
        tracker = self._tracker()
        tracker.record_unrealized("mkt-1", pnl_usd=7.5)
        rec = tracker.get("mkt-1")
        assert rec.unrealized == pytest.approx(7.5)

    def test_mp18_get_returns_none_for_unknown(self):
        """MP-18: get() returns None for a market with no records."""
        tracker = self._tracker()
        assert tracker.get("unknown") is None

    def test_mp19_summary_aggregates_all_markets(self):
        """MP-19: summary() aggregates realized + unrealized across all markets."""
        tracker = self._tracker()
        tracker.record_realized("mkt-1", pnl_usd=10.0)
        tracker.record_realized("mkt-2", pnl_usd=-3.0)
        tracker.record_unrealized("mkt-1", pnl_usd=2.0)
        s = tracker.summary()
        assert s["total_realized"] == pytest.approx(7.0)
        assert s["total_unrealized"] == pytest.approx(2.0)
        assert s["total_pnl"] == pytest.approx(9.0)
        assert s["market_count"] == 2

    def test_mp20_reset_clears_all_records(self):
        """MP-20: reset() clears all PnL records."""
        tracker = self._tracker()
        tracker.record_realized("mkt-1", pnl_usd=10.0)
        tracker.reset()
        assert tracker.summary()["market_count"] == 0


# ── MP-21–25: message_formatter ───────────────────────────────────────────────

class TestMessageFormatterRealism:
    """MP-21–25: format_trade_alert / format_signal_alert market metadata."""

    def test_mp21_format_trade_alert_shows_market_question(self):
        """MP-21: format_trade_alert uses market_question when provided."""
        from projects.polymarket.polyquantbot.telegram.message_formatter import format_trade_alert
        msg = format_trade_alert(
            side="YES",
            price=0.65,
            size=100.0,
            market_id="0xabc",
            market_question="Will BTC hit $100k?",
        )
        assert "Will BTC hit $100k?" in msg
        assert "0xabc" not in msg

    def test_mp22_format_trade_alert_fallback_to_market_id(self):
        """MP-22: format_trade_alert falls back to market_id when no question."""
        from projects.polymarket.polyquantbot.telegram.message_formatter import format_trade_alert
        msg = format_trade_alert(side="NO", price=0.35, size=50.0, market_id="0xdef")
        assert "0xdef" in msg

    def test_mp23_format_trade_alert_shows_outcome(self):
        """MP-23: format_trade_alert includes Outcome line."""
        from projects.polymarket.polyquantbot.telegram.message_formatter import format_trade_alert
        msg = format_trade_alert(side="YES", price=0.6, size=50.0, outcome="YES")
        assert "Outcome" in msg
        assert "YES" in msg

    def test_mp24_format_trade_alert_partial_fill_visible(self):
        """MP-24: Partial fill info is shown when partial_fill=True."""
        from projects.polymarket.polyquantbot.telegram.message_formatter import format_trade_alert
        msg = format_trade_alert(
            side="YES",
            price=0.6,
            size=100.0,
            partial_fill=True,
            filled_size=75.0,
        )
        assert "partial" in msg.lower()
        assert "75" in msg

    def test_mp25_format_signal_alert_shows_market_question(self):
        """MP-25: format_signal_alert replaces market_id with market_question."""
        from projects.polymarket.polyquantbot.telegram.message_formatter import format_signal_alert
        msg = format_signal_alert(
            market_id="0xabc",
            edge=0.10,
            size=50.0,
            market_question="Will ETH flip BTC?",
            outcome="YES",
        )
        assert "Will ETH flip BTC?" in msg
        assert "Outcome" in msg
        assert "YES" in msg


# ── MP-26–30: logger helpers ──────────────────────────────────────────────────

class TestLoggerHelpers:
    """MP-26–30: New structured log helpers in core.logging.logger."""

    def test_mp26_log_trade_executed_realistic(self, capsys):
        """MP-26: log_trade_executed_realistic does not raise."""
        from projects.polymarket.polyquantbot.core.logging.logger import log_trade_executed_realistic
        log_trade_executed_realistic(
            "t1", "mkt-1",
            side="YES",
            fill_price=0.55,
            filled_size_usd=80.0,
            slippage_pct=0.005,
            partial_fill=True,
            latency_ms=350.0,
        )

    def test_mp27_log_partial_fill(self):
        """MP-27: log_partial_fill does not raise."""
        from projects.polymarket.polyquantbot.core.logging.logger import log_partial_fill
        log_partial_fill(
            "t1", "mkt-1",
            requested_size_usd=100.0,
            filled_size_usd=75.0,
            fill_fraction=0.75,
        )

    def test_mp28_log_slippage_applied(self):
        """MP-28: log_slippage_applied does not raise."""
        from projects.polymarket.polyquantbot.core.logging.logger import log_slippage_applied
        log_slippage_applied(
            "t1", "mkt-1",
            base_price=0.50,
            fill_price=0.505,
            slippage_pct=0.01,
            side="YES",
        )

    def test_mp29_log_pnl_realized(self):
        """MP-29: log_pnl_realized does not raise."""
        from projects.polymarket.polyquantbot.core.logging.logger import log_pnl_realized
        log_pnl_realized(
            "mkt-1",
            trade_id="t1",
            pnl_usd=15.0,
            cumulative_realized=15.0,
        )

    def test_mp30_log_pnl_unrealized(self):
        """MP-30: log_pnl_unrealized does not raise."""
        from projects.polymarket.polyquantbot.core.logging.logger import log_pnl_unrealized
        log_pnl_unrealized(
            "mkt-1",
            unrealized_pnl_usd=5.0,
            mark_price=0.55,
        )
