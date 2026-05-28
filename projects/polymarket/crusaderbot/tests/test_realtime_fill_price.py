"""Realtime-fill-price lane regression tests.

WARP🔹CMD direction (2026-05-28): "Now fix strategy safe close and flip
hunter, ensure trades use realtime price, no more fake price."

Two surgical changes verified by these tests:

1. **Entry side** — ``signal_scan_job._process_candidate`` now prefers
   ``cand.metadata["entry_price"]`` (real CLOB /book best-ask from
   strategy scan time) over re-fetching via ``get_live_market_price``
   (which can route through Gamma's seed/midpoint fallback). Candidates
   without metadata still fall back to the helper, so signal_following
   et al on longshot markets continue to work.

2. **Exit side** — ``exit_watcher.evaluate`` returns the live mark
   (``cur``) as ``current_price`` on TP_HIT / SL_HIT instead of the
   synthetic ``entry × (1 ± pct)`` formula. The synthetic was the
   visible "fake exits" symptom: distinct coins with identical entries
   produced identical synthetic exits (entry × 1.15 = 0.58075). Falls
   back to the synthetic when ``cur`` is None (no live price available).
"""
from __future__ import annotations

import asyncio
import inspect

import pytest

from projects.polymarket.crusaderbot.services.signal_scan import (
    signal_scan_job as ssj,
)
from projects.polymarket.crusaderbot.domain.execution import exit_watcher


# ---------------------------------------------------------------------
# Entry side — source-level pin
# ---------------------------------------------------------------------

def test_process_candidate_prefers_metadata_entry_price_over_live_fetch():
    """``_process_candidate`` must source ``_live_fill_price`` from
    ``cand.metadata["entry_price"]`` first, falling back to
    ``get_live_market_price`` only when the metadata is absent or
    malformed. Source-level pin: a future edit that flips the priority
    fails this test.
    """
    src = inspect.getsource(ssj._process_candidate)
    # Locate the live-price-resolution block.
    block_start = src.find("_meta_entry = cand.metadata.get(\"entry_price\")")
    block_end = src.find("_live_fill_price = await get_live_market_price")
    assert block_start != -1, (
        "Regression: _process_candidate no longer reads "
        "cand.metadata[\"entry_price\"] — late_entry_v3 entry-price source "
        "must be the real CLOB /book best-ask from scan, not a re-fetched "
        "value that can fall through to Gamma seed."
    )
    assert block_end != -1, (
        "Regression: get_live_market_price fallback path missing — "
        "non-candle strategies (signal_following etc.) need this fallback."
    )
    assert block_start < block_end, (
        "Regression: metadata-first ordering inverted. Metadata read must "
        "occur BEFORE the get_live_market_price fallback."
    )


# ---------------------------------------------------------------------
# Exit side — live mark, not synthetic
# ---------------------------------------------------------------------

class _StubPosition:
    """Minimal stand-in for OpenPositionForExit so we can drive evaluate()
    deterministically without the full registry plumbing."""

    def __init__(
        self,
        *,
        side: str,
        entry_price: float,
        applied_tp_pct: float | None = None,
        applied_sl_pct: float | None = None,
        live_mark: float = 0.0,
        force_close_intent: bool = False,
    ) -> None:
        self.side = side
        self.entry_price = entry_price
        self.applied_tp_pct = applied_tp_pct
        self.applied_sl_pct = applied_sl_pct
        self._mark = live_mark
        self.market_resolved = False
        self.force_close_intent = force_close_intent
        self.strategy_type = None
        self.resolution_at = None
        self.risk_profile = "balanced"

    def current_price(self) -> float:
        return self._mark


async def _noop_evaluator(position, current_price):
    return False


def test_evaluate_tp_hit_uses_live_mark_not_synthetic_yes():
    """YES side: entry=0.50, applied_tp=0.20, live=0.62. Synthetic exit
    would be 0.60 (0.50 × 1.20). Live mark 0.62 is the realistic fill
    and must be what gets returned.
    """
    pos = _StubPosition(
        side="yes", entry_price=0.50, applied_tp_pct=0.20, live_mark=0.62,
    )
    decision = asyncio.run(exit_watcher.evaluate(pos, strategy_evaluator=_noop_evaluator))
    assert decision.should_exit
    assert decision.reason == exit_watcher.ExitReason.TP_HIT.value
    # Live mark, NOT synthetic 0.60
    assert decision.current_price == pytest.approx(0.62)


def test_evaluate_sl_hit_uses_live_mark_not_synthetic_yes():
    """YES side: entry=0.50, applied_sl=0.20, live=0.35 (-30%). Synthetic
    exit would be 0.40 (0.50 × 0.80). Live mark 0.35 must be returned.
    """
    pos = _StubPosition(
        side="yes",
        entry_price=0.50,
        applied_sl_pct=0.20,
        applied_tp_pct=0.50,
        live_mark=0.35,
    )
    decision = asyncio.run(exit_watcher.evaluate(pos, strategy_evaluator=_noop_evaluator))
    assert decision.should_exit
    assert decision.reason == exit_watcher.ExitReason.SL_HIT.value
    # Live mark, NOT synthetic 0.40
    assert decision.current_price == pytest.approx(0.35)


def test_evaluate_distinct_markets_produce_distinct_exits():
    """Two positions with the SAME entry price but DIFFERENT live marks
    (e.g. BTC and ETH after the same 5m candle resolves) must produce
    DIFFERENT exit prices. The old synthetic formula made them identical;
    the realtime fill must surface the per-market variance.
    """
    btc = _StubPosition(side="yes", entry_price=0.50, applied_tp_pct=0.20, live_mark=0.61)
    eth = _StubPosition(side="yes", entry_price=0.50, applied_tp_pct=0.20, live_mark=0.67)

    btc_decision = asyncio.run(exit_watcher.evaluate(btc, strategy_evaluator=_noop_evaluator))
    eth_decision = asyncio.run(exit_watcher.evaluate(eth, strategy_evaluator=_noop_evaluator))

    assert btc_decision.current_price != eth_decision.current_price, (
        "Regression: distinct live marks produced identical exits — the "
        "synthetic fill is back and the bot is faking exit prices again."
    )
    assert btc_decision.current_price == pytest.approx(0.61)
    assert eth_decision.current_price == pytest.approx(0.67)


def test_evaluate_synthetic_fallback_when_live_mark_unavailable():
    """Source-level pin: the evaluator must still wire `_tp_exit_price` /
    `_sl_exit_price` as a fallback for callers that pass no live_price.

    In production `OpenPositionForExit.current_price()` never returns
    None (it falls back to entry_price), so the synthetic-fallback
    branch never runs at runtime — but the code path must remain so a
    future refactor that surfaces None doesn't crash the watcher.
    """
    src = inspect.getsource(exit_watcher.evaluate)
    assert "_tp_exit_price" in src, (
        "Regression: _tp_exit_price fallback no longer wired in evaluate()."
    )
    assert "_sl_exit_price" in src, (
        "Regression: _sl_exit_price fallback no longer wired in evaluate()."
    )
    # Both branches use the new pattern: live mark first, synthetic fallback.
    assert src.count("cur if cur is not None else _tp_exit_price") >= 1
    assert src.count("cur if cur is not None else _sl_exit_price") >= 1
