"""Regression: BNB monitor-only asset hygiene
(WARP/R00T/bnb-monitor-only, ref Polybot directive Part 4 Tier 3).

Polymarket BNB candle books are too thin for the current spread / edge
/ fill-rate thresholds, so the directive recommends BNB → monitor-only
until 30-day edge stats validate re-enabling. This lane:

1. Removes BNB from the tradable asset set
   (``webtrader/backend/router._CRYPTO_SHORT_ASSETS``).
2. Removes BNB from the user-facing selector
   (``webtrader/frontend/src/pages/AutoTradePage.CRYPTO_ASSETS`` +
   ``components/AdminUserDrawer.CRYPTO_ASSETS``).
3. Adds a scan-job defensive filter that strips legacy BNB entries
   from a user's persisted ``selected_assets`` JSONB array so
   pre-lane rows don't leak BNB markets into the signal universe.

The router validator already rejects BNB at preset-activation time
once it's out of ``_VALID_ASSETS``, but existing users may have BNB
persisted from a prior activation — the scan-job filter is the
belt-and-braces guarantee.

The whitelist for asset-text matching
(``domain.strategy.eligibility.ASSET_ALIASES``) is deliberately
UNCHANGED — BNB markets can still be observed in market_data for the
30-day stats collection the directive calls for; they're just no
longer eligible to fire a trade.

Guard:
  ``services.signal_scan.signal_scan_job._filter_monitor_only_assets``
Constant:
  ``services.signal_scan.signal_scan_job._MONITOR_ONLY_ASSETS``
Tradable set:
  ``webtrader/backend/router._CRYPTO_SHORT_ASSETS``
"""
from __future__ import annotations

import inspect

import pytest

from projects.polymarket.crusaderbot.services.signal_scan import (
    signal_scan_job as ssj,
)
from projects.polymarket.crusaderbot.webtrader.backend import router as r


# ---------------------------------------------------------------------
# Tradable-set assertions — fail closed if BNB sneaks back in.
# ---------------------------------------------------------------------


def test_bnb_removed_from_tradable_set():
    """BNB must NOT appear in the router's tradable asset tuple. A
    regression that re-added BNB would silently allow preset activation
    on a market the bot can't reliably fill."""
    assert "BNB" not in r._CRYPTO_SHORT_ASSETS, (
        "Regression: BNB is back in _CRYPTO_SHORT_ASSETS. Re-enable "
        "only after the 30-day edge stats validate (directive Part 4 "
        "Phase 2)."
    )


def test_bnb_removed_from_valid_assets():
    """Derived `_VALID_ASSETS` frozenset must also exclude BNB."""
    assert "BNB" not in r._VALID_ASSETS


def test_default_assets_unchanged():
    """Default-active set (BTC + ETH) must NOT be affected by the BNB
    removal — guards against accidental edits to the default tuple."""
    assert tuple(r._DEFAULT_CRYPTO_SHORT_ASSETS) == ("BTC", "ETH")


def test_tradable_set_is_exactly_btc_eth_sol():
    """Post-lane the tradable set must be exactly the three Tier-1 + opt-in
    assets — no surprise additions, no surprise removals.

    This pins the directive-aligned universe: Tier 1 = BTC, ETH; Tier 2
    (conditional, opt-in) = SOL. BNB / XRP / DOGE / HYPE are NOT in this
    set and must not be re-added without explicit operator authorization.
    """
    assert tuple(r._CRYPTO_SHORT_ASSETS) == ("BTC", "ETH", "SOL")


# ---------------------------------------------------------------------
# Monitor-only filter — defensive against stale DB rows.
# ---------------------------------------------------------------------


def test_monitor_only_set_contains_bnb():
    """The monitor-only constant must list BNB. If a future edit emptied
    the set, the filter would no-op and stale rows would re-enable
    BNB scanning."""
    assert "BNB" in ssj._MONITOR_ONLY_ASSETS


def test_filter_drops_bnb_from_stale_row():
    """Defensive: a user whose persisted row contains BNB (selected
    before this lane shipped) must have BNB stripped at scan-time so
    the scanner never queues a BNB market for them."""
    assert ssj._filter_monitor_only_assets(["BTC", "BNB", "ETH"]) == ["BTC", "ETH"]


def test_filter_preserves_tradable_assets():
    """All tradable assets must pass through the filter unchanged."""
    assert ssj._filter_monitor_only_assets(["BTC", "ETH", "SOL"]) == [
        "BTC", "ETH", "SOL",
    ]


def test_filter_case_insensitive():
    """DB rows may have been written before the router normalised to
    uppercase. Filter must catch lowercase / mixed-case BNB."""
    assert ssj._filter_monitor_only_assets(["btc", "bnb", "Eth"]) == ["BTC", "ETH"]


@pytest.mark.parametrize("inp", [None, [], (), {}, ""])
def test_filter_handles_empty(inp):
    """Empty / None / falsy input must yield an empty list (the
    downstream code treats empty as 'all default assets')."""
    assert ssj._filter_monitor_only_assets(inp) == []


def test_filter_drops_blank_entries():
    """Blank strings in the persisted array (corruption / partial
    writes) must be dropped — they would otherwise turn into ""
    entries that confuse the market-text matcher."""
    assert ssj._filter_monitor_only_assets(["BTC", "", "  ", "ETH"]) == [
        "BTC", "ETH",
    ]


def test_filter_returns_list_type():
    """Call sites unpack the result into ``list[str]`` /
    ``tuple(...)`` constructions. The filter MUST return a list (not
    a generator) so downstream `len(...)` / repeated iteration works."""
    out = ssj._filter_monitor_only_assets(["BTC", "BNB"])
    assert isinstance(out, list)


def test_filter_handles_stringified_json():
    """Defensive: if asyncpg ever returns the column as a JSON string
    (current schema is TEXT[] but a future migration to JSONB or a
    misconfigured codec would silently flip the type), the filter
    must parse the string rather than iterating its characters.
    Iterating the raw '["BTC", "BNB"]' would yield '[', '"', 'B', ...
    and produce a nonsense output. Parse, then filter.
    """
    assert ssj._filter_monitor_only_assets('["BTC", "BNB", "ETH"]') == [
        "BTC", "ETH",
    ]


def test_filter_rejects_invalid_json_string():
    """Malformed JSON must yield empty list (not raise) — corruption
    in the persisted row is the operator's problem to fix, not a reason
    to crash the entire scan loop."""
    assert ssj._filter_monitor_only_assets("not valid json") == []


def test_filter_rejects_json_non_list():
    """A JSON-decoded BARE STRING (e.g. `'"BTC"'`) decodes to the str
    'BTC' — which IS iterable but iteration would yield characters
    'B', 'T', 'C'. Reject any decoded non-list defensively so the
    filter never falls through to character iteration."""
    assert ssj._filter_monitor_only_assets('"BTC"') == []
    assert ssj._filter_monitor_only_assets('42') == []
    assert ssj._filter_monitor_only_assets('{"BTC": true}') == []


def test_filter_rejects_unexpected_type():
    """Non-iterable / non-string inputs (int, float, bool) must yield
    empty list rather than raising a TypeError mid-scan."""
    assert ssj._filter_monitor_only_assets(42) == []
    assert ssj._filter_monitor_only_assets(3.14) == []
    assert ssj._filter_monitor_only_assets(True) == []


# ---------------------------------------------------------------------
# Source-level pin — fail closed if a future edit reads
# `row["selected_assets"]` directly without filtering.
# ---------------------------------------------------------------------


def test_build_user_context_uses_filter():
    """`_build_user_context` must route the persisted `selected_assets`
    through `_filter_monitor_only_assets`. A regression that read the
    raw row would skip the monitor-only guard on the main scan path.
    """
    src = inspect.getsource(ssj._build_user_context)
    assert "_filter_monitor_only_assets" in src, (
        "Regression: _build_user_context bypassed the monitor-only "
        "filter — stale BNB rows can now reach the scanner."
    )
