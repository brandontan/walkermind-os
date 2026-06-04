"""WARP-64 Chunk 3 — advisory oracle-edge wiring into late_entry_v3.

Verifies the ADVISORY observation path (no network): symbol parsing, the
per-candidate edge metadata (warmup / no-baseline / computed / error), that it
NEVER blocks or raises, and the signal_scan_job lazy-singleton oracle wiring
(flag gating, start-once reuse, best-effort stop).
"""
from __future__ import annotations

from typing import Any, Optional

import pytest

from projects.polymarket.crusaderbot import config as crusaderbot_config
from projects.polymarket.crusaderbot.domain.strategy.oracle import (
    DEFAULT_SIGMA_PER_SQRT_SEC,
)
from projects.polymarket.crusaderbot.domain.strategy.strategies import late_entry_v3 as lev3
from projects.polymarket.crusaderbot.domain.strategy.strategies.late_entry_v3 import (
    OracleEdgeConfig,
    _asset_base_from_slug,
    _candle_open_epoch,
    _observe_oracle_edge,
)
from projects.polymarket.crusaderbot.services.signal_scan import signal_scan_job as ssj


# ---------------------------------------------------------------------
# Symbol parsing
# ---------------------------------------------------------------------


def test_asset_base_from_slug():
    assert _asset_base_from_slug("btc-updown-5m-1771511700") == "btc"
    assert _asset_base_from_slug("eth-updown-15m-1771511700") == "eth"
    assert _asset_base_from_slug("sol-updown-5m-1") == "sol"
    assert _asset_base_from_slug("btc-other-slug") is None  # non-candle slug
    assert _asset_base_from_slug("some-random-market") is None
    assert _asset_base_from_slug("") is None


def _cfg(**over: Any) -> OracleEdgeConfig:
    base = dict(
        enabled=True,
        price_provider=lambda sym: 104_500.0,
        sigma_map=DEFAULT_SIGMA_PER_SQRT_SEC,
        min_dist=0.0005,
        max_dist=0.02,
        min_edge=0.02,
        trend=False,
    )
    base.update(over)
    return OracleEdgeConfig(**base)


_MKT = {"slug": "btc-updown-5m-1771511700", "priceToBeat": 104_000.0}


# ---------------------------------------------------------------------
# Advisory observation — never blocks, never raises
# ---------------------------------------------------------------------


def test_observe_disabled_returns_empty():
    assert _observe_oracle_edge(None, market=_MKT, slug=_MKT["slug"], seconds_left=120, yes_ask=0.6, no_ask=0.4) == {}
    off = _cfg(enabled=False)
    assert _observe_oracle_edge(off, market=_MKT, slug=_MKT["slug"], seconds_left=120, yes_ask=0.6, no_ask=0.4) == {}
    nopp = _cfg(price_provider=None)
    assert _observe_oracle_edge(nopp, market=_MKT, slug=_MKT["slug"], seconds_left=120, yes_ask=0.6, no_ask=0.4) == {}


def test_observe_warmup_none_price_is_not_an_error():
    cfg = _cfg(price_provider=lambda sym: None)  # warmup / stale -> None
    meta = _observe_oracle_edge(cfg, market=_MKT, slug=_MKT["slug"], seconds_left=120, yes_ask=0.6, no_ask=0.4)
    assert meta["oracle_edge_status"] == "warming_up"
    assert meta["oracle_symbol"] == "btc/usd"
    assert "oracle_edge_would_pass" not in meta  # no decision during warmup


def test_observe_no_price_to_beat():
    cfg = _cfg()
    meta = _observe_oracle_edge(cfg, market={"slug": _MKT["slug"]}, slug=_MKT["slug"], seconds_left=120, yes_ask=0.6, no_ask=0.4)
    assert meta["oracle_edge_status"] == "no_price_to_beat"


def test_observe_computed_stamps_edge_and_would_pass_true():
    cfg = _cfg(price_provider=lambda sym: 104_500.0)  # +0.48% above price_to_beat
    meta = _observe_oracle_edge(cfg, market=_MKT, slug=_MKT["slug"], seconds_left=120, yes_ask=0.6, no_ask=0.4)
    assert meta["oracle_edge_status"] == "computed"
    assert meta["oracle_symbol"] == "btc/usd"
    assert meta["oracle_delta"] == pytest.approx((104_500.0 - 104_000.0) / 104_000.0)
    assert meta["oracle_fair_up"] > 0.99          # strong Up lean, short time
    assert meta["oracle_edge_up"] == pytest.approx(meta["oracle_fair_up"] - 0.6)
    assert meta["oracle_edge_down"] == pytest.approx((1.0 - meta["oracle_fair_up"]) - 0.4)
    assert meta["oracle_edge_would_pass"] is True  # advisory only


def test_observe_would_pass_false_when_distance_below_min():
    # oracle == price_to_beat -> delta 0 -> distance 0 < min_dist -> would_pass False
    cfg = _cfg(price_provider=lambda sym: 104_000.0)
    meta = _observe_oracle_edge(cfg, market=_MKT, slug=_MKT["slug"], seconds_left=120, yes_ask=0.6, no_ask=0.4)
    assert meta["oracle_edge_status"] == "computed"
    assert meta["oracle_fair_up"] == pytest.approx(0.5)
    assert meta["oracle_edge_would_pass"] is False


def test_observe_swallows_provider_errors_non_blocking():
    def _boom(sym: str) -> Optional[float]:
        raise RuntimeError("provider blew up")

    cfg = _cfg(price_provider=_boom)
    meta = _observe_oracle_edge(cfg, market=_MKT, slug=_MKT["slug"], seconds_left=120, yes_ask=0.6, no_ask=0.4)
    assert meta["oracle_edge_status"] == "error"  # logged + swallowed, no raise


# ---------------------------------------------------------------------
# WARP-68 — derive price_to_beat from the Chainlink buffer at candle open
# ---------------------------------------------------------------------


def test_candle_open_epoch_from_slug_and_event_start():
    # Slug trailing unix ts IS the candle open (2026-06-04T05:25:00Z).
    assert _candle_open_epoch({}, "btc-updown-5m-1780550700") == 1780550700.0
    assert _candle_open_epoch({"slug": "x"}, "sol-updown-15m-1780551000") == 1780551000.0
    # Non-candle slug -> fall back to an explicit eventStartTime (ISO or epoch).
    assert _candle_open_epoch({"eventStartTime": "2026-06-04T05:25:00Z"}, "x") == pytest.approx(1780550700.0)
    assert _candle_open_epoch({"event_start_time": 1780550700}, "x") == pytest.approx(1780550700.0)
    # Nothing usable -> None (stays no_price_to_beat, never a bogus instant).
    assert _candle_open_epoch({}, "some-random-market") is None
    assert _candle_open_epoch({"eventStartTime": "not-a-date"}, "x") is None


_MKT_NO_PTB = {"slug": "btc-updown-5m-1780550700"}  # no price-to-beat field at all


def test_observe_derives_price_to_beat_from_oracle_buffer():
    # Market carries NO price-to-beat; the buffer supplies the candle-open price.
    seen = {}

    def _price_at(sym: str, epoch: float, *, tolerance_sec: float = 2.0):
        seen.update(sym=sym, epoch=epoch, tol=tolerance_sec)
        return 63_800.0

    cfg = _cfg(price_provider=lambda s: 63_900.0, price_at_provider=_price_at, ptb_tolerance_sec=2.0)
    meta = _observe_oracle_edge(
        cfg, market=_MKT_NO_PTB, slug=_MKT_NO_PTB["slug"], seconds_left=120, yes_ask=0.55, no_ask=0.47
    )
    assert meta["oracle_edge_status"] == "computed"
    assert meta["oracle_price_to_beat"] == pytest.approx(63_800.0)
    assert meta["oracle_price_to_beat_source"] == "oracle_buffer"
    assert meta["oracle_delta"] == pytest.approx((63_900.0 - 63_800.0) / 63_800.0)
    # Looked up the right symbol + candle-open epoch with the configured tolerance.
    assert seen == {"sym": "btc/usd", "epoch": 1780550700.0, "tol": 2.0}


def test_observe_no_price_to_beat_when_buffer_misses():
    cfg = _cfg(price_provider=lambda s: 63_900.0, price_at_provider=lambda *a, **k: None)
    meta = _observe_oracle_edge(
        cfg, market=_MKT_NO_PTB, slug=_MKT_NO_PTB["slug"], seconds_left=120, yes_ask=0.55, no_ask=0.47
    )
    assert meta["oracle_edge_status"] == "no_price_to_beat"


def test_observe_prefers_explicit_metadata_over_buffer():
    # When the market DOES carry a baseline, the buffer is not consulted.
    cfg = _cfg(price_provider=lambda s: 104_500.0, price_at_provider=lambda *a, **k: 999.0)
    meta = _observe_oracle_edge(cfg, market=_MKT, slug=_MKT["slug"], seconds_left=120, yes_ask=0.6, no_ask=0.4)
    assert meta["oracle_edge_status"] == "computed"
    assert meta["oracle_price_to_beat"] == pytest.approx(104_000.0)
    assert meta["oracle_price_to_beat_source"] == "metadata"


# ---------------------------------------------------------------------
# signal_scan_job lazy-singleton oracle + flag gating
# ---------------------------------------------------------------------


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("OPERATOR_CHAT_ID", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("WALLET_HD_SEED", "seed")
    monkeypatch.setenv("WALLET_ENCRYPTION_KEY", "k")
    monkeypatch.setenv("POLYGON_RPC_URL", "https://rpc")
    monkeypatch.setenv("ALCHEMY_POLYGON_WS_URL", "wss://ws")


@pytest.fixture(autouse=True)
def _reset_settings_and_singleton(monkeypatch):
    crusaderbot_config.get_settings.cache_clear()
    ssj._candle_oracle = None
    yield
    crusaderbot_config.get_settings.cache_clear()
    ssj._candle_oracle = None


class _FakeOracle:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0
        self.symbols = ["btc/usd", "eth/usd", "sol/usd"]

    async def start(self) -> None:
        self.started += 1

    async def stop(self) -> None:
        self.stopped += 1

    def get_price(self, symbol: str) -> Optional[float]:
        return None

    def price_at(self, symbol: str, epoch_sec: float, *, tolerance_sec: float = 2.0) -> Optional[float]:
        return None


@pytest.mark.asyncio
async def test_build_edge_cfg_none_when_flag_off(monkeypatch):
    _set_required_env(monkeypatch)
    # ORACLE_EDGE_GATE_ENABLED defaults False -> no observation.
    assert await ssj._build_oracle_edge_cfg("close_sweep") is None


@pytest.mark.asyncio
async def test_build_edge_cfg_none_when_oracle_disabled(monkeypatch):
    _set_required_env(monkeypatch)
    monkeypatch.setenv("ORACLE_EDGE_GATE_ENABLED", "true")
    # ORACLE_ENABLED still off -> oracle_from_settings raises -> advisory inert.
    assert await ssj._build_oracle_edge_cfg("close_sweep") is None


@pytest.mark.asyncio
async def test_lazy_singleton_starts_once_and_reuses(monkeypatch):
    _set_required_env(monkeypatch)
    monkeypatch.setenv("ORACLE_EDGE_GATE_ENABLED", "true")
    monkeypatch.setenv("ORACLE_ENABLED", "true")
    fake = _FakeOracle()
    import projects.polymarket.crusaderbot.domain.strategy.oracle as oracle_pkg
    monkeypatch.setattr(oracle_pkg, "oracle_from_settings", lambda **_: fake)

    cfg1 = await ssj._build_oracle_edge_cfg("close_sweep")
    cfg2 = await ssj._build_oracle_edge_cfg("flip_hunter")
    assert cfg1 is not None and cfg2 is not None
    assert fake.started == 1  # started once, reused across scans (no reconnect)
    # Per-preset edge params flow through.
    assert (cfg1.min_edge, cfg1.trend) == (0.02, False)
    assert (cfg2.min_edge, cfg2.trend) == (0.03, True)
    assert cfg1.price_provider.__self__ is fake  # bound to the singleton oracle
    # WARP-68: price_at + tolerance wired from the same singleton + settings.
    assert cfg1.price_at_provider.__self__ is fake
    assert cfg1.ptb_tolerance_sec == 2.0

    await ssj.stop_candle_oracle()
    assert fake.stopped == 1
    assert ssj._candle_oracle is None


@pytest.mark.asyncio
async def test_stop_candle_oracle_safe_when_never_started():
    ssj._candle_oracle = None
    await ssj.stop_candle_oracle()  # must not raise
