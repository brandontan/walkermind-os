"""Hermetic tests for WARP-61 — WebTrader confluence_scalper exposure.

Verifies the four done-criteria gates declared in issue #1269:
  1. Preset catalog exposure: bot/presets.py PRESET_CONFIG carries the
     ``confluence_scalper`` entry and the WebTrader router accepts it.
  2. Selection mapping: ``/autotrade/preset`` accepts preset_key
     ``confluence_scalper`` and existing preset ids remain wired.
  3. Full Auto inclusion: signal_scan_job._PRESET_ALLOWED["full_auto"]
     contains "confluence_scalper" so Full Auto picks it up automatically.
  4. Non-crypto skip + asset whitelist: _is_crypto_eligible_for_confluence
     gates by Crypto category AND BTC/ETH/SOL/XRP/DOGE/BNB/HYPE asset
     whitelist; Politics/Sports/Weather/Finance markets must skip.

No DB, no Telegram, no Polymarket HTTP.
"""
from __future__ import annotations

import pytest

from projects.polymarket.crusaderbot.bot.presets import (
    PRESET_CONFIG,
    PRESET_ORDER,
    get_preset,
)
from projects.polymarket.crusaderbot.services.signal_scan import signal_scan_job as job
from projects.polymarket.crusaderbot.webtrader.backend.router import _PRESET_PARAMS


# ---------------------------------------------------------------------------
# 1. Preset catalog exposure
# ---------------------------------------------------------------------------


def test_confluence_scalper_in_preset_catalog():
    cfg = get_preset("confluence_scalper")
    assert cfg is not None, "confluence_scalper missing from bot/presets PRESET_CONFIG"
    assert cfg["name"] == "Crypto Scalper"
    assert cfg["strategies"] == ["confluence_scalper"]
    assert cfg["has_copy_trade"] is False


def test_confluence_scalper_in_preset_order():
    assert "confluence_scalper" in PRESET_ORDER
    # Card positioned in the advanced strategy block — adjacent to ensemble
    # / full_auto per the issue's UI layout requirement.
    assert PRESET_ORDER.index("confluence_scalper") > PRESET_ORDER.index("pair_arb")
    assert PRESET_ORDER.index("confluence_scalper") < PRESET_ORDER.index("full_auto")


def test_existing_preset_keys_unchanged():
    # Regression guard — existing presets must remain in the catalog after
    # the new card was added.
    for key in (
        "whale_mirror", "trend_breakout", "contrarian", "value_hunter",
        "close_sweep", "pair_arb", "ensemble", "full_auto",
    ):
        assert key in PRESET_CONFIG, f"existing preset {key} dropped from catalog"


# ---------------------------------------------------------------------------
# 2. Selection mapping (WebTrader /autotrade/preset endpoint)
# ---------------------------------------------------------------------------


def test_router_accepts_confluence_scalper_preset_key():
    assert "confluence_scalper" in _PRESET_PARAMS
    params = _PRESET_PARAMS["confluence_scalper"]
    # Scalp targets are tight — TP 8%, SL 4% per backend strategy contract.
    assert params["tp_pct"] == pytest.approx(0.08)
    assert params["sl_pct"] == pytest.approx(0.04)
    # Risk profile compatibility excludes "conservative" — balanced default.
    assert params["risk_profile"] == "balanced"


def test_router_preserves_existing_preset_param_ids():
    for key in (
        "whale_mirror", "trend_breakout", "contrarian", "value_hunter",
        "close_sweep", "pair_arb", "ensemble", "full_auto",
        "signal_sniper", "hybrid",  # legacy keys
    ):
        assert key in _PRESET_PARAMS, f"existing preset_key {key} dropped"


# ---------------------------------------------------------------------------
# 3. Full Auto inclusion
# ---------------------------------------------------------------------------


def test_full_auto_includes_confluence_scalper():
    assert "confluence_scalper" in job._PRESET_ALLOWED["full_auto"]


def test_default_preset_includes_confluence_scalper():
    # No preset set → full_auto behaviour. Ensure parity.
    assert "confluence_scalper" in job._PRESET_ALLOWED[None]


def test_confluence_scalper_preset_isolated():
    # Selecting the new preset alone runs ONLY the confluence_scalper engine.
    assert job._PRESET_ALLOWED["confluence_scalper"] == frozenset({"confluence_scalper"})


def test_non_confluence_presets_do_not_enable_scalper():
    # No regression — other preset keys must not silently activate the new
    # strategy.
    for key in (
        "whale_mirror", "trend_breakout", "contrarian", "value_hunter",
        "close_sweep", "pair_arb", "ensemble",
    ):
        assert "confluence_scalper" not in job._PRESET_ALLOWED[key], (
            f"preset {key} unexpectedly activates confluence_scalper"
        )


def test_preset_allows_function_routes_correctly():
    assert job._preset_allows("confluence_scalper", "confluence_scalper") is True
    assert job._preset_allows("full_auto", "confluence_scalper") is True
    assert job._preset_allows("whale_mirror", "confluence_scalper") is False
    # Existing presets keep their existing routing.
    assert job._preset_allows("ensemble", "trend_breakout") is True
    assert job._preset_allows("pair_arb", "pair_arb") is True


# ---------------------------------------------------------------------------
# 4. Crypto eligibility gate (category + asset whitelist)
# ---------------------------------------------------------------------------


def _market(category: str, question: str, market_id: str = "m-1") -> dict:
    return {
        "id": market_id,
        "category": category,
        "question": question,
        "slug": question.lower().replace(" ", "-"),
    }


@pytest.mark.parametrize("asset_phrase", [
    "Will BTC hit $200k by EOY?",
    "Bitcoin all time high before July?",
    "ETH above $5k?",
    "Ethereum gas fees below 10 gwei?",
    "SOL > $300 by EOY?",
    "Solana TVL > $20B?",
    "XRP $5 ETA?",
    "DOGE moon shot?",
    "Dogecoin > $1?",
    "BNB above $800?",
    "HYPE above $20?",
    "Hyperliquid TVL crosses $10B?",
])
def test_crypto_markets_pass_eligibility(asset_phrase: str):
    m = _market("Crypto", asset_phrase)
    assert job._is_crypto_eligible_for_confluence(m) is True


@pytest.mark.parametrize("category,question", [
    ("Politics", "Will BTC be banned by the next administration?"),
    ("Sports", "Will the BTC team win the championship?"),
    ("Weather", "Will Bitcoin Beach see rain in May?"),
    ("Finance", "Stock market crash before June?"),
    ("Entertainment", "Best film of 2026?"),
    ("World", "Election outcome in 2026?"),
    ("Science", "Mars landing this decade?"),
])
def test_non_crypto_categories_rejected(category: str, question: str):
    # Even if the question mentions a crypto asset, the category gate blocks
    # the strategy so Politics/Sports/etc. markets keep running their own
    # eligible strategies untouched.
    m = _market(category, question)
    assert job._is_crypto_eligible_for_confluence(m) is False


def test_crypto_category_without_whitelisted_asset_rejected():
    # Crypto-tagged market that does NOT mention a whitelisted asset.
    m = _market("Crypto", "Will an altcoin index outperform stocks?")
    assert job._is_crypto_eligible_for_confluence(m) is False


def test_word_boundary_prevents_substring_false_positive():
    # "hyperventilate" must not match HYPE; "hyperliquid" must.
    miss = _market("Crypto", "Will the hyperventilating pundit retire?")
    assert job._is_crypto_eligible_for_confluence(miss) is False


def test_crypto_eligible_market_ids_filter():
    markets = [
        _market("Crypto", "Will BTC hit $200k?", market_id="m-btc"),
        _market("Politics", "BTC ban?", market_id="m-pol"),
        _market("Crypto", "Random altcoin moon?", market_id="m-alt"),
        _market("Crypto", "ETH gas low?", market_id="m-eth"),
    ]
    ids = job._crypto_eligible_market_ids(markets)
    assert ids == {"m-btc", "m-eth"}


def test_invalid_market_dict_safe():
    assert job._is_crypto_eligible_for_confluence(None) is False  # type: ignore[arg-type]
    assert job._is_crypto_eligible_for_confluence({"category": None}) is False
    # Missing question/title falls through cleanly.
    assert job._is_crypto_eligible_for_confluence({"category": "Crypto"}) is False
