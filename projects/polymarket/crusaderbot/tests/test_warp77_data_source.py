"""WARP-77 Phase 1.4 — factor_vectors provenance column tests.

Covers the runtime data-regime resolver (`resolve_data_source`) and that the
recorder appends the `data_source` value as the final INSERT column, aligned with
the SQL. Hermetic — no DB, no network: a fake asyncpg pool/conn captures the SQL +
bound args; the resolver is tested against lightweight fake settings objects.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from projects.polymarket.crusaderbot.domain.research import factor_dataset as fd
from projects.polymarket.crusaderbot.domain.research.factor_dataset import (
    DATA_SOURCE_LIVE_REAL,
    DATA_SOURCE_PAPER_REAL,
    DATA_SOURCE_PAPER_SYNTHETIC,
    record_factor_vector,
    resolve_data_source,
)
from projects.polymarket.crusaderbot.domain.signal.factors import FactorVector


# ── fake asyncpg pool/conn ────────────────────────────────────────────────
class _Conn:
    def __init__(self):
        self.calls: list[tuple] = []  # (sql, args)

    async def execute(self, sql, *args):
        self.calls.append((sql, args))


class _Pool:
    def __init__(self, conn):
        self._c = conn

    def acquire(self):
        c = self._c

        class _Ctx:
            async def __aenter__(self_inner):
                return c

            async def __aexit__(self_inner, *a):
                return False

        return _Ctx()


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _reset_throttle():
    fd._last_write.clear()
    yield
    fd._last_write.clear()


def _fv(condition_id="0xC1", **over) -> FactorVector:
    base = dict(
        market_id=condition_id, condition_id=condition_id, slug="btc-updown-5m-1",
        asset="btc", timeframe="5m", evaluated_rule="close_sweep",
        momentum=0.001, momentum_delta=0.05, momentum_span_sec=30.0, momentum_samples=3,
        volatility_sigma=0.0001, liquidity_usdc=1234.0, spread=0.98,
        orderbook_depth_usdc=1234.0, ttl_sec=20.0, oracle_edge=0.03,
        oracle_edge_status="computed", oracle_would_pass=True, oracle_delta=0.001,
        fav_side="YES", entry_side="YES", fav_price=0.65, entry_price=0.65,
        ask_diff=0.45, complete_set_edge=0.02, underdog_mode=False,
        realized_outcome="UP", realized_delta=0.001, outcome_source="provisional",
        outcome_observed_rem_sec=20.0, candle_open_epoch=1.0, candle_close_epoch=301.0,
    )
    base.update(over)
    return FactorVector(**base)


# ── resolver: runtime data regime → provenance tag ────────────────────────
def test_resolve_live_real():
    s = SimpleNamespace(ENABLE_LIVE_TRADING=True, USE_PYSDK_CLOB=True)
    assert resolve_data_source(s) == DATA_SOURCE_LIVE_REAL


def test_resolve_paper_real():
    s = SimpleNamespace(ENABLE_LIVE_TRADING=False, USE_PYSDK_CLOB=True)
    assert resolve_data_source(s) == DATA_SOURCE_PAPER_REAL


def test_resolve_paper_synthetic_default():
    s = SimpleNamespace(ENABLE_LIVE_TRADING=False, USE_PYSDK_CLOB=False)
    assert resolve_data_source(s) == DATA_SOURCE_PAPER_SYNTHETIC


def test_resolve_missing_attrs_defaults_synthetic():
    # An object with neither flag → conservative historical default.
    assert resolve_data_source(SimpleNamespace()) == DATA_SOURCE_PAPER_SYNTHETIC


def test_resolve_failsoft_on_raising_settings():
    class _Boom:
        @property
        def ENABLE_LIVE_TRADING(self):  # noqa: N802
            raise RuntimeError("config blew up")

    assert resolve_data_source(_Boom()) == DATA_SOURCE_PAPER_SYNTHETIC


def test_live_takes_precedence_over_pysdk():
    # ENABLE_LIVE_TRADING dominates even if the data backend flag is off.
    s = SimpleNamespace(ENABLE_LIVE_TRADING=True, USE_PYSDK_CLOB=False)
    assert resolve_data_source(s) == DATA_SOURCE_LIVE_REAL


# ── recorder: data_source is the final INSERT column, aligned with values ──
def test_record_appends_data_source_arg():
    conn = _Conn()
    ok = _run(
        record_factor_vector(
            _fv(), pool=_Pool(conn), now=1000.0, data_source=DATA_SOURCE_PAPER_REAL
        )
    )
    assert ok is True
    sql, args = conn.calls[0]
    # Column present in the INSERT list and the ON CONFLICT refresh set.
    assert "data_source" in sql
    assert "data_source = EXCLUDED.data_source" in sql
    # Arg count matches the full INSERT column list and the tag is the LAST arg.
    assert len(args) == len(fd._INSERT_COLS)
    assert args[-1] == DATA_SOURCE_PAPER_REAL
    # Placeholder count in the VALUES clause matches the arg count.
    assert f"${len(fd._INSERT_COLS)}" in sql
    assert f"${len(fd._INSERT_COLS) + 1}" not in sql


def test_record_default_synthetic_when_no_injection_and_no_settings(monkeypatch):
    # With get_settings unavailable, the recorder fail-softs to paper_synthetic
    # rather than raising — provenance never breaks a write.
    import projects.polymarket.crusaderbot.config as cfg

    def _boom():
        raise RuntimeError("no settings in sandbox")

    monkeypatch.setattr(cfg, "get_settings", _boom)
    conn = _Conn()
    ok = _run(record_factor_vector(_fv(), pool=_Pool(conn), now=1000.0))
    assert ok is True
    _sql, args = conn.calls[0]
    assert args[-1] == DATA_SOURCE_PAPER_SYNTHETIC
