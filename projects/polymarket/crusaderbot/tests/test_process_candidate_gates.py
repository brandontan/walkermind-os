"""Hermetic tests for the extracted gate helpers (Lane 4 / C-4 closure).

`_process_candidate` was decomposed into named gate helpers. These tests
exercise each helper in isolation — pure unit tests, no DB, no broker, no
TradeEngine. The behavioural integration of each gate against
`_process_candidate` is still covered by the legacy test files
(`test_tob_freshness_gate.py`, `test_complete_set_edge_gate.py`, etc.); the
tests here pin the helpers' own contracts so a future caller (or refactor)
cannot regress them.

Every helper returns ``str | None`` — None to continue, a skip-reason string
to short-circuit. The caller logs telemetry and returns when the helper
returns a string.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from projects.polymarket.crusaderbot.services.signal_scan import (
    signal_scan_job as ssj,
)


# --------------------------------------------------------------------------- log stub


def _log() -> MagicMock:
    """Stub logger that swallows .info / .warning calls without state."""
    log = MagicMock()
    log.info = MagicMock()
    log.warning = MagicMock()
    return log


# --------------------------------------------------------------------------- _gate_signal_freshness


def test_signal_freshness_passes_when_pub_uuid_is_none():
    # Lib-strategy candidate (pub_uuid=None) always passes — signal_ts=now.
    assert ssj._gate_signal_freshness(
        pub_uuid=None, signal_ts=datetime(2000, 1, 1, tzinfo=timezone.utc), log=_log(),
    ) is None


def test_signal_freshness_passes_when_within_threshold():
    from uuid import uuid4
    fresh = datetime.now(timezone.utc) - timedelta(seconds=60)
    assert ssj._gate_signal_freshness(pub_uuid=uuid4(), signal_ts=fresh, log=_log()) is None


def test_signal_freshness_rejects_when_over_threshold():
    from uuid import uuid4
    stale = datetime.now(timezone.utc) - timedelta(seconds=ssj._MAX_SIGNAL_AGE_SECONDS + 60)
    assert ssj._gate_signal_freshness(
        pub_uuid=uuid4(), signal_ts=stale, log=_log(),
    ) == "skipped_signal_stale"


# --------------------------------------------------------------------------- _gate_target_price_drift


def test_target_price_drift_passes_when_pub_uuid_none():
    assert ssj._gate_target_price_drift(
        pub_uuid=None, side="yes", market={"yes_price": 0.99}, metadata={"target_price": 0.5}, log=_log(),
    ) is None


def test_target_price_drift_passes_when_target_unset():
    from uuid import uuid4
    assert ssj._gate_target_price_drift(
        pub_uuid=uuid4(), side="yes", market={"yes_price": 0.5}, metadata={}, log=_log(),
    ) is None


def test_target_price_drift_passes_when_within_threshold():
    from uuid import uuid4
    # target=0.50, current=0.55 → drift 10% < 25%
    assert ssj._gate_target_price_drift(
        pub_uuid=uuid4(), side="yes",
        market={"yes_price": 0.55}, metadata={"target_price": 0.5}, log=_log(),
    ) is None


def test_target_price_drift_rejects_when_over_threshold():
    from uuid import uuid4
    # target=0.50, current=0.70 → drift 40% > 25%
    assert ssj._gate_target_price_drift(
        pub_uuid=uuid4(), side="yes",
        market={"yes_price": 0.70}, metadata={"target_price": 0.5}, log=_log(),
    ) == "skipped_price_drifted"


def test_target_price_drift_uses_side_fallback_when_primary_missing():
    from uuid import uuid4
    # yes_price missing → falls back to no_price
    assert ssj._gate_target_price_drift(
        pub_uuid=uuid4(), side="yes",
        market={"no_price": 0.7}, metadata={"target_price": 0.5}, log=_log(),
    ) == "skipped_price_drifted"


# --------------------------------------------------------------------------- _gate_liquidity_filter


def test_liquidity_filter_passes_when_threshold_zero():
    assert ssj._gate_liquidity_filter(
        market={"liquidity_usdc": 0.0}, min_liquidity_threshold=0.0, log=_log(),
    ) is None


def test_liquidity_filter_passes_when_above_threshold():
    assert ssj._gate_liquidity_filter(
        market={"liquidity_usdc": 50000.0}, min_liquidity_threshold=10000.0, log=_log(),
    ) is None


def test_liquidity_filter_rejects_when_below_threshold():
    assert ssj._gate_liquidity_filter(
        market={"liquidity_usdc": 5000.0}, min_liquidity_threshold=10000.0, log=_log(),
    ) == "skipped_liquidity"


# --------------------------------------------------------------------------- _gate_tob_freshness


def test_tob_freshness_passes_when_no_stamp():
    assert ssj._gate_tob_freshness(
        metadata={}, side="yes", market_id="m1", strategy_name="signal_following", log=_log(),
    ) is None


def test_tob_freshness_passes_when_disabled_via_zero(monkeypatch):
    import projects.polymarket.crusaderbot.config as cfg
    monkeypatch.setattr(cfg, "get_settings",
                        lambda: SimpleNamespace(TOB_STALE_MS=0))
    now_ts = datetime.now(timezone.utc).timestamp()
    assert ssj._gate_tob_freshness(
        metadata={"entry_price_ts": now_ts - 1000.0},
        side="yes", market_id="m1", strategy_name="late_entry_v3", log=_log(),
    ) is None


def test_tob_freshness_passes_when_fresh(monkeypatch):
    import projects.polymarket.crusaderbot.config as cfg
    monkeypatch.setattr(cfg, "get_settings",
                        lambda: SimpleNamespace(TOB_STALE_MS=2000))
    now_ts = datetime.now(timezone.utc).timestamp()
    assert ssj._gate_tob_freshness(
        metadata={"entry_price_ts": now_ts - 0.5},
        side="yes", market_id="m1", strategy_name="late_entry_v3", log=_log(),
    ) is None


def test_tob_freshness_rejects_when_stale(monkeypatch):
    import projects.polymarket.crusaderbot.config as cfg
    monkeypatch.setattr(cfg, "get_settings",
                        lambda: SimpleNamespace(TOB_STALE_MS=2000))
    now_ts = datetime.now(timezone.utc).timestamp()
    assert ssj._gate_tob_freshness(
        metadata={"entry_price_ts": now_ts - 5.0},
        side="yes", market_id="m1", strategy_name="late_entry_v3", log=_log(),
    ) == "skipped_stale_tob"


def test_tob_freshness_falls_back_on_config_error(monkeypatch):
    import projects.polymarket.crusaderbot.config as cfg
    def boom():
        raise RuntimeError("boom")
    monkeypatch.setattr(cfg, "get_settings", boom)
    now_ts = datetime.now(timezone.utc).timestamp()
    log = _log()
    # Fallback default is 2000ms; a 5s-old stamp still rejects.
    assert ssj._gate_tob_freshness(
        metadata={"entry_price_ts": now_ts - 5.0},
        side="yes", market_id="m1", strategy_name="late_entry_v3", log=log,
    ) == "skipped_stale_tob"
    log.warning.assert_called()  # config-read failure must be logged


# --------------------------------------------------------------------------- _gate_complete_set_edge


def test_complete_set_edge_passes_when_no_stamp():
    assert ssj._gate_complete_set_edge(
        metadata={}, side="yes", market_id="m1", strategy_name="signal_following", log=_log(),
    ) is None


def test_complete_set_edge_passes_when_disabled(monkeypatch):
    import projects.polymarket.crusaderbot.config as cfg
    monkeypatch.setattr(cfg, "get_settings",
                        lambda: SimpleNamespace(MIN_COMPLETE_SET_EDGE=0.0))
    assert ssj._gate_complete_set_edge(
        metadata={"complete_set_edge": -0.01},
        side="yes", market_id="m1", strategy_name="late_entry_v3", log=_log(),
    ) is None


def test_complete_set_edge_passes_when_above_threshold(monkeypatch):
    import projects.polymarket.crusaderbot.config as cfg
    monkeypatch.setattr(cfg, "get_settings",
                        lambda: SimpleNamespace(MIN_COMPLETE_SET_EDGE=0.005))
    assert ssj._gate_complete_set_edge(
        metadata={"complete_set_edge": 0.02},
        side="yes", market_id="m1", strategy_name="late_entry_v3", log=_log(),
    ) is None


def test_complete_set_edge_rejects_when_below_threshold(monkeypatch):
    import projects.polymarket.crusaderbot.config as cfg
    monkeypatch.setattr(cfg, "get_settings",
                        lambda: SimpleNamespace(MIN_COMPLETE_SET_EDGE=0.005))
    assert ssj._gate_complete_set_edge(
        metadata={"complete_set_edge": 0.001},
        side="yes", market_id="m1", strategy_name="late_entry_v3", log=_log(),
    ) == "skipped_negative_arb"


def test_complete_set_edge_bypasses_on_unparseable_stamp(monkeypatch):
    import projects.polymarket.crusaderbot.config as cfg
    monkeypatch.setattr(cfg, "get_settings",
                        lambda: SimpleNamespace(MIN_COMPLETE_SET_EDGE=0.005))
    log = _log()
    # Garbage stamp → log warning and bypass (caller must NOT silently reject).
    assert ssj._gate_complete_set_edge(
        metadata={"complete_set_edge": "not-a-number"},
        side="yes", market_id="m1", strategy_name="late_entry_v3", log=log,
    ) is None
    log.warning.assert_called()


# --------------------------------------------------------------------------- _gate_candle_tick_alignment


def test_candle_tick_alignment_passes_when_no_live_price():
    assert ssj._gate_candle_tick_alignment(
        live_fill_price=None, market={"slug": "btc-updown-5m-x"},
        side="yes", strategy_name="flip_hunter", market_id="m1", log=_log(),
    ) is None


def test_candle_tick_alignment_passes_on_non_candle_market():
    # Longshot slug → sub-cent prices are legitimate.
    assert ssj._gate_candle_tick_alignment(
        live_fill_price=0.055, market={"slug": "election-trump-2028"},
        side="yes", strategy_name="signal_following", market_id="m1", log=_log(),
    ) is None


def test_candle_tick_alignment_passes_when_aligned():
    assert ssj._gate_candle_tick_alignment(
        live_fill_price=0.65, market={"slug": "btc-updown-5m-x"},
        side="yes", strategy_name="flip_hunter", market_id="m1", log=_log(),
    ) is None


def test_candle_tick_alignment_rejects_when_off_tick():
    # 0.505 on a candle market = Gamma seed/midpoint, not real CLOB fill.
    assert ssj._gate_candle_tick_alignment(
        live_fill_price=0.505, market={"slug": "btc-updown-5m-x"},
        side="yes", strategy_name="flip_hunter", market_id="m1", log=_log(),
    ) == "skipped_sub_cent_price"


# --------------------------------------------------------------------------- _gate_fill_band


def test_fill_band_passes_when_no_live_price():
    assert ssj._gate_fill_band(
        live_fill_price=None,
        metadata={"fav_price_min": 0.6, "fav_price_max": 0.7},
        side="yes", strategy_name="safe_close", log=_log(),
    ) is None


def test_fill_band_passes_when_no_band_metadata():
    assert ssj._gate_fill_band(
        live_fill_price=0.55, metadata={},
        side="yes", strategy_name="signal_following", log=_log(),
    ) is None


def test_fill_band_passes_when_inside_band():
    assert ssj._gate_fill_band(
        live_fill_price=0.65,
        metadata={"fav_price_min": 0.6, "fav_price_max": 0.7},
        side="yes", strategy_name="safe_close", log=_log(),
    ) is None


def test_fill_band_rejects_when_below_band():
    assert ssj._gate_fill_band(
        live_fill_price=0.55,
        metadata={"fav_price_min": 0.6, "fav_price_max": 0.7},
        side="yes", strategy_name="safe_close", log=_log(),
    ) == "skipped_fill_drifted"


def test_fill_band_rejects_when_at_or_above_band_max():
    # band is [min, max) so equal to max is REJECT.
    assert ssj._gate_fill_band(
        live_fill_price=0.7,
        metadata={"fav_price_min": 0.6, "fav_price_max": 0.7},
        side="yes", strategy_name="safe_close", log=_log(),
    ) == "skipped_fill_drifted"


# --------------------------------------------------------------------------- _gate_safe_close_direction


def test_safe_close_direction_passes_when_preset_not_safe_close():
    from uuid import uuid4
    assert ssj._gate_safe_close_direction(
        user_id=uuid4(), side="yes", market_id="m1",
        active_preset="close_sweep", log=_log(),
    ) is None


def test_safe_close_direction_passes_when_limit_zero(monkeypatch):
    from uuid import uuid4
    import projects.polymarket.crusaderbot.config as cfg
    monkeypatch.setattr(cfg, "get_settings",
                        lambda: SimpleNamespace(SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR=0))
    assert ssj._gate_safe_close_direction(
        user_id=uuid4(), side="yes", market_id="m1",
        active_preset="safe_close", log=_log(),
    ) is None


def test_safe_close_direction_rejects_when_at_limit(monkeypatch):
    from uuid import uuid4
    import projects.polymarket.crusaderbot.config as cfg
    monkeypatch.setattr(cfg, "get_settings",
                        lambda: SimpleNamespace(SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR=2))
    uid = uuid4()
    # Seed two recent entries on YES.
    ssj._safe_close_reset_for_tests()
    now_ts = datetime.now(timezone.utc).timestamp()
    ssj._safe_close_record_entry(str(uid), "yes", now_ts)
    ssj._safe_close_record_entry(str(uid), "yes", now_ts)
    assert ssj._gate_safe_close_direction(
        user_id=uid, side="yes", market_id="m1",
        active_preset="safe_close", log=_log(),
    ) == "skipped_safe_close_direction_concentration"


def test_safe_close_direction_passes_when_under_limit(monkeypatch):
    from uuid import uuid4
    import projects.polymarket.crusaderbot.config as cfg
    monkeypatch.setattr(cfg, "get_settings",
                        lambda: SimpleNamespace(SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR=8))
    ssj._safe_close_reset_for_tests()
    assert ssj._gate_safe_close_direction(
        user_id=uuid4(), side="yes", market_id="m1",
        active_preset="safe_close", log=_log(),
    ) is None
