"""Smart Strike market-universe admin gating (#1797, owner-locked).

The universe is locked to Polymarket short-duration crypto Up/Down candle
markets: BTC + ETH on 5m + 15m enabled by default, SOL present but DISABLED
by default, with admin runtime controls (master / per-pair / per-timeframe).
A disabled bucket must emit an explicit skip reason and can never produce a
candidate — hence no order intent, paper or live, regardless of Auto-Trade.
"""
from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from projects.polymarket.crusaderbot.services.signal_scan import signal_scan_job as ssj


def _settings(**over):
    base = dict(
        SMART_STRIKE_ENABLED=True,
        SMART_STRIKE_BTC_ENABLED=True,
        SMART_STRIKE_ETH_ENABLED=True,
        SMART_STRIKE_SOL_ENABLED=False,
        SMART_STRIKE_5M_ENABLED=True,
        SMART_STRIKE_15M_ENABLED=True,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _resolve(tf, assets, *, settings=None, overrides=None):
    """Drive the helper with env defaults from ``settings`` and optional
    admin runtime overrides (dict key->bool)."""
    s = settings or _settings()
    ov = overrides or {}

    async def fake_resolve_bool(key, env_default):
        return ov.get(key, env_default)

    with patch("projects.polymarket.crusaderbot.config.get_settings",
               return_value=s), \
         patch.object(ssj._runtime_config, "resolve_bool",
                      AsyncMock(side_effect=fake_resolve_bool)):
        return asyncio.run(ssj._smart_strike_admin_universe(tf, assets))


# ── default universe ─────────────────────────────────────────────────────────

def test_default_universe_is_btc_eth_with_sol_disabled():
    allowed, reason, assets = _resolve("5m", None)
    assert allowed is True and reason is None
    assert assets == ["BTC", "ETH"], "SOL must be dropped by default"


def test_default_universe_constants_locked():
    from projects.polymarket.crusaderbot.domain.strategy import (
        smart_strike_universe as ssu,
    )
    # The scan job re-exports the shared single-source-of-truth constants.
    assert ssj._SMART_STRIKE_DEFAULT_ASSETS == ("BTC", "ETH", "SOL")
    assert ssu.DEFAULT_ASSETS == ("BTC", "ETH", "SOL")
    assert set(ssu.PAIR_FLAGS) == {"BTC", "ETH", "SOL"}
    assert set(ssu.TIMEFRAME_FLAGS) == {"5m", "15m"}


def test_15m_enabled_by_default():
    allowed, reason, assets = _resolve("15m", ["BTC", "ETH"])
    assert allowed is True and assets == ["BTC", "ETH"]


def test_sol_only_selection_with_sol_disabled_blocks_with_reason():
    allowed, reason, assets = _resolve("5m", ["SOL"])
    assert allowed is False
    assert reason == "smart_strike_assets_disabled"
    assert assets == []


def test_empty_selection_does_not_resurrect_sol():
    """An empty/None selection falls back to the default universe BEFORE the
    per-pair filter — SOL must not sneak back in via the downstream
    tradeable-coins default."""
    allowed, _reason, assets = _resolve("5m", [])
    assert allowed is True
    assert "SOL" not in assets


# ── admin controls ───────────────────────────────────────────────────────────

def test_master_off_blocks_everything_with_reason():
    allowed, reason, assets = _resolve(
        "5m", ["BTC", "ETH"], overrides={"SMART_STRIKE_ENABLED": False},
    )
    assert allowed is False
    assert reason == "smart_strike_admin_disabled"
    assert assets == []


def test_timeframe_disable_blocks_that_bucket_only():
    allowed, reason, _ = _resolve(
        "5m", ["BTC"], overrides={"SMART_STRIKE_5M_ENABLED": False},
    )
    assert allowed is False
    assert reason == "smart_strike_timeframe_disabled:5m"
    # the 15m bucket is unaffected
    allowed15, reason15, assets15 = _resolve(
        "15m", ["BTC"], overrides={"SMART_STRIKE_5M_ENABLED": False},
    )
    assert allowed15 is True and reason15 is None and assets15 == ["BTC"]


def test_admin_can_disable_btc_or_eth_individually():
    _, _, assets = _resolve(
        "5m", None, overrides={"SMART_STRIKE_BTC_ENABLED": False},
    )
    assert assets == ["ETH"]
    _, _, assets = _resolve(
        "5m", None, overrides={"SMART_STRIKE_ETH_ENABLED": False},
    )
    assert assets == ["BTC"]


def test_admin_can_explicitly_enable_sol():
    allowed, _, assets = _resolve(
        "5m", None, overrides={"SMART_STRIKE_SOL_ENABLED": True},
    )
    assert allowed is True
    assert assets == ["BTC", "ETH", "SOL"]


def test_env_defaults_match_owner_lock():
    """config.py env defaults: master/BTC/ETH/5m/15m ON, SOL OFF."""
    import re
    from pathlib import Path
    src = (Path(ssj.__file__).resolve().parents[2] / "config.py").read_text(
        encoding="utf-8",
    )
    assert re.search(r"SMART_STRIKE_ENABLED: bool = True", src)
    assert re.search(r"SMART_STRIKE_BTC_ENABLED: bool = True", src)
    assert re.search(r"SMART_STRIKE_ETH_ENABLED: bool = True", src)
    assert re.search(r"SMART_STRIKE_SOL_ENABLED: bool = False", src)
    assert re.search(r"SMART_STRIKE_5M_ENABLED: bool = True", src)
    assert re.search(r"SMART_STRIKE_15M_ENABLED: bool = True", src)


def test_runtime_admin_overlays_exist_for_all_six_flags():
    from projects.polymarket.crusaderbot.domain.ops.runtime_config import (
        RUNTIME_SETTINGS,
    )
    for key in (
        "SMART_STRIKE_ENABLED", "SMART_STRIKE_BTC_ENABLED",
        "SMART_STRIKE_ETH_ENABLED", "SMART_STRIKE_SOL_ENABLED",
        "SMART_STRIKE_5M_ENABLED", "SMART_STRIKE_15M_ENABLED",
    ):
        assert key in RUNTIME_SETTINGS, f"missing admin overlay: {key}"
        assert RUNTIME_SETTINGS[key].kind == "bool"


# ── wiring: both scan loops consult the gate; blocked bucket = no candidates ─

def test_run_once_loop_gates_candle_scan_on_admin_universe():
    src = inspect.getsource(ssj.run_once)
    assert "_smart_strike_admin_universe(" in src
    # explicit skip reason — never a silent disappearance
    assert "smart_strike_admin_skip" in src
    # blocked bucket skips the late_entry scan entirely (no candidates ->
    # no order intent, paper OR live, regardless of Auto-Trade state).
    assert "late_entry_strat is not None and ss_allowed" in src
    # the admin-filtered asset list drives both the window fetch and the
    # strategy's own eligibility (UserContext) — SOL can't leak back in.
    assert 'get_crypto_window_markets(\n                        selected_timeframe or "5m", ss_assets' in src
    assert "_build_user_context(row, assets_override=ss_assets)" in src


def test_fast_loop_gates_candle_scan_on_admin_universe():
    src = inspect.getsource(ssj.run_close_sweep_fast)
    assert "_smart_strike_admin_universe(" in src
    assert "smart_strike_admin_skip" in src
    assert "_build_user_context(row, assets_override=ss_assets)" in src


def test_user_context_assets_override_threads_filtered_universe():
    row = {
        "user_id": "00000000-0000-0000-0000-000000000001",
        "selected_timeframe": "5m",
        "selected_assets": ["BTC", "ETH", "SOL"],
        "balance_usdc": 100.0,
    }
    ctx = ssj._build_user_context(row, assets_override=["BTC", "ETH"])
    assert ctx.selected_assets == ("BTC", "ETH")
    # legacy behaviour intact without the override
    ctx2 = ssj._build_user_context(row)
    assert ctx2.selected_assets == ("BTC", "ETH", "SOL")


def test_admin_enablement_does_not_bypass_user_or_live_gates():
    """The universe gate is scan-level only: the risk gate's live-guard set
    and the shared $5 Auto-Trade start guard are untouched by this lane."""
    from projects.polymarket.crusaderbot.domain.risk import gate as gate_mod
    src = inspect.getsource(gate_mod._passes_live_guards)
    for guard in (
        "ENABLE_LIVE_TRADING", "EXECUTION_PATH_VALIDATED",
        "CAPITAL_MODE_CONFIRMED", "USE_REAL_CLOB",
    ):
        assert guard in src
    assert "SMART_STRIKE" not in src  # universe flags never weaken live guards
    from projects.polymarket.crusaderbot.domain.activation import live_mode
    assert live_mode.MIN_LIVE_AUTOTRADE_BALANCE_USDC == 5
