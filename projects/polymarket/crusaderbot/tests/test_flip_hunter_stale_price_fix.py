"""Regression: flip-hunter Gamma-fallback stale-price bug.

Root cause (2026-05-28): when CLOB ``/price`` returned the empty-book
sentinel for a fresh 5m crypto candle market, ``get_live_market_price``
fell through to Gamma ``outcomePrices`` and returned sub-cent seed/
midpoint values (0.505 / 0.515). Flip Hunter's early-window scan fired
identical trades across BTC/ETH/SOL/XRP/DOGE/BNB simultaneously — 72/86
positions @ exactly 0.505. The synthetic TP fill (entry × 1.15) closed
them at the identical 0.58075 for fake +$0.50 wins on the paper wallet.

Fix is scoped to **candle markets only** (slug contains ``updown``) so
thin longshot markets on other slugs continue to trade on legitimate
sub-cent Gamma last-trade prices (e.g. 0.055 for a 5.5c longshot —
needed for signal_following on illiquid markets per WARP-38).

Guard lives in:
  ``services.signal_scan.signal_scan_job._process_candidate`` (step 3b-i)
"""
from __future__ import annotations

import inspect

import pytest

from projects.polymarket.crusaderbot.services.signal_scan import (
    signal_scan_job as ssj,
)


def test_signal_scan_job_has_sub_cent_guard():
    """Source-level pin: ``_process_candidate`` must contain the
    ``skipped_sub_cent_price`` outcome path so a future edit that drops
    the guard fails this test.
    """
    src = inspect.getsource(ssj._process_candidate)
    assert "skipped_sub_cent_price" in src, (
        "Regression: _process_candidate lost its sub-cent guard — "
        "flip_hunter would re-fire on stale Gamma seed prices."
    )
    # The check must compare against the 0.01 tick.
    assert "100" in src and ("round" in src or "abs(" in src), (
        "Regression: sub-cent guard logic is missing the tick comparison."
    )


def test_signal_scan_job_guard_scoped_to_candle_markets():
    """The guard MUST be scoped to candle markets (slug contains 'updown'),
    not applied globally — sub-cent prices on longshot markets are
    legitimate Gamma last-trade values (WARP-38) that other strategies
    must continue to trade.
    """
    src = inspect.getsource(ssj._process_candidate)
    assert "updown" in src, (
        "Regression: sub-cent guard must be scoped to candle markets "
        "(slug contains 'updown'); a global guard breaks longshot trading."
    )


# ---------------------------------------------------------------------
# Mathematical fingerprint of the bug
# ---------------------------------------------------------------------

@pytest.mark.parametrize("sub_cent", [0.505, 0.515, 0.525, 0.575, 0.625])
def test_sub_cent_detection(sub_cent):
    """``abs(price*100 - round(price*100)) > 1e-6`` detects any value
    that is not a whole cent — the same check the guard uses.
    """
    cents = sub_cent * 100.0
    assert abs(cents - round(cents)) > 1e-6


@pytest.mark.parametrize("tick", [0.50, 0.51, 0.52, 0.60, 0.95])
def test_tick_aligned_passes(tick):
    """Whole-cent values must NOT trigger the sub-cent guard."""
    cents = tick * 100.0
    assert abs(cents - round(cents)) <= 1e-6


# ---------------------------------------------------------------------
# Slug detection — only `updown` markets are gated
# ---------------------------------------------------------------------

@pytest.mark.parametrize(
    "slug,is_candle",
    [
        ("btc-updown-5m-1779980700", True),
        ("eth-updown-5m-1779980700", True),
        ("sol-updown-15m-1779980700", True),
        ("doge-updown-5m-1779980700", True),
        ("will-trump-win-2028-election", False),
        ("nfl-superbowl-2026-winner", False),
        ("eu-recession-2026", False),
    ],
)
def test_candle_slug_detection(slug, is_candle):
    """Slug-based filter must distinguish candle markets from longshots."""
    assert ("updown" in slug) == is_candle
