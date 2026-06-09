"""WARP-85 — STRATEGY-owned exit default.

Pins the CLAUDE.md SYSTEM PIPELINE boundary: the defensive TP/SL default applied
when ``user_settings`` is NULL must come FROM the active strategy's
``default_tp_sl()`` hook (STRATEGY stage), not a hardcoded scan-job constant.

Proves:
  (a) the default is sourced from ``default_tp_sl()`` — a stub strategy with a
      sentinel default drives the built signal;
  (b) crypto/late_entry_v3 resolves to (1.5, 0.5) — byte-identical regression;
  (c) a literal ``user_settings`` value still overrides the strategy default
      (E.2 invariant preserved);
  (d) an unresolvable strategy falls back to the logged last-resort guard.

Pure-unit over ``_build_trade_signal`` and ``_strategy_default_tp_sl`` — no DB,
no network.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from projects.polymarket.crusaderbot.domain.strategy.base import BaseStrategy
from projects.polymarket.crusaderbot.domain.strategy.registry import (
    StrategyRegistry,
    bootstrap_default_strategies,
)
from projects.polymarket.crusaderbot.domain.strategy.types import (
    ExitDecision,
    SignalCandidate,
)
from projects.polymarket.crusaderbot.services.signal_scan import signal_scan_job as ssj


# ---------------------------------------------------------------------------
# A stub strategy whose default_tp_sl() returns a sentinel no real strategy uses,
# so an assertion on those exact numbers proves the value flowed THROUGH the hook.
# ---------------------------------------------------------------------------

_SENTINEL_TP = 0.77
_SENTINEL_SL = 0.11


class _StubExitDefaultStrategy(BaseStrategy):
    name = "stub_exit_default"
    version = "1.0.0"
    risk_profile_compatibility = ["balanced"]

    async def scan(self, market_filters, user_context):  # pragma: no cover - unused
        return []

    async def evaluate_exit(self, position):  # pragma: no cover - unused
        return ExitDecision(should_exit=False, reason="hold")

    def default_tp_sl(self) -> tuple[float, float]:
        return (_SENTINEL_TP, _SENTINEL_SL)


@pytest.fixture
def registry():
    """Isolated registry with the defaults + the stub; restored afterwards."""
    StrategyRegistry._reset_for_tests()
    reg = StrategyRegistry.instance()
    bootstrap_default_strategies(reg)
    reg.register(_StubExitDefaultStrategy())
    yield reg
    # Restore a clean, fully-bootstrapped shared singleton for later tests.
    StrategyRegistry._reset_for_tests()
    bootstrap_default_strategies()


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def _cand(strategy_name: str) -> SignalCandidate:
    return SignalCandidate(
        market_id="MKT",
        condition_id="MKT",
        side="YES",
        confidence=0.6,
        suggested_size_usdc=5.0,
        strategy_name=strategy_name,
        signal_ts=datetime.now(timezone.utc),
        metadata={},
    )


def _row(*, tp_pct, sl_pct) -> dict:
    return {
        "user_id": uuid4(),
        "telegram_user_id": 12345,
        "role": "user",
        "auto_trade_on": True,
        "paused": False,
        "resolved_profile": "balanced",
        "trading_mode": "paper",
        "tp_pct": tp_pct,
        "sl_pct": sl_pct,
        "daily_loss_override": None,
        "min_liquidity_threshold": 0.0,
        "max_drawdown_pct": None,
        "active_preset": "candle_auto",
        "max_concurrent_override": None,
        "balance_usdc": 100.0,
    }


def _market() -> dict:
    return {
        "question": "Will it?",
        "yes_token_id": "yt",
        "no_token_id": "nt",
        "status": "active",
        "liquidity_usdc": 1000.0,
    }


def _build(monkeypatch, *, strategy_name, tp_pct, sl_pct):
    monkeypatch.setattr(ssj, "_bankroll_multiplier", lambda *a, **k: 1.0)
    return ssj._build_trade_signal(
        row=_row(tp_pct=tp_pct, sl_pct=sl_pct),
        cand=_cand(strategy_name),
        market=_market(),
        idempotency_key="idem-1",
        live_price_override=0.42,
    )


# ---------------------------------------------------------------------------
# _strategy_default_tp_sl — the resolver
# ---------------------------------------------------------------------------

def test_resolver_reads_from_strategy_hook(registry):
    assert ssj._strategy_default_tp_sl("stub_exit_default") == (_SENTINEL_TP, _SENTINEL_SL)


def test_resolver_crypto_is_byte_identical(registry):
    # late_entry_v3 (the only strategy the candle presets fire) must default to
    # the proven E.1/E.2 Balanced baseline — unchanged runtime.
    assert ssj._strategy_default_tp_sl("late_entry_v3") == (1.5, 0.5)


def test_resolver_last_resort_when_unresolvable(caplog):
    StrategyRegistry._reset_for_tests()  # empty registry → no strategy resolvable
    try:
        tp, sl = ssj._strategy_default_tp_sl("late_entry_v3")
    finally:
        StrategyRegistry._reset_for_tests()
        bootstrap_default_strategies()
    assert (tp, sl) == (ssj._LAST_RESORT_TP_PCT, ssj._LAST_RESORT_SL_PCT)
    assert (tp, sl) == (1.5, 0.5)


# ---------------------------------------------------------------------------
# _build_trade_signal — end-to-end through the builder
# ---------------------------------------------------------------------------

def test_null_settings_default_flows_from_strategy_hook(monkeypatch, registry):
    # (a) NULL user_settings → the sentinel default proves the value came from
    # the strategy's default_tp_sl(), not a scan-job constant.
    sig = _build(monkeypatch, strategy_name="stub_exit_default", tp_pct=None, sl_pct=None)
    assert sig.tp_pct == pytest.approx(_SENTINEL_TP)
    assert sig.sl_pct == pytest.approx(_SENTINEL_SL)


def test_null_settings_crypto_resolves_to_150_50(monkeypatch, registry):
    # (b) regression: crypto path byte-identical to the pre-WARP-85 constant.
    sig = _build(monkeypatch, strategy_name="late_entry_v3", tp_pct=None, sl_pct=None)
    assert sig.tp_pct == pytest.approx(1.5)
    assert sig.sl_pct == pytest.approx(0.5)


def test_user_settings_literal_overrides_strategy_default(monkeypatch, registry):
    # (c) E.2 invariant: a configured user value wins over the strategy default.
    sig = _build(monkeypatch, strategy_name="stub_exit_default", tp_pct=0.20, sl_pct=0.10)
    assert sig.tp_pct == pytest.approx(0.20)
    assert sig.sl_pct == pytest.approx(0.10)
    # Not the sentinel default.
    assert sig.tp_pct != pytest.approx(_SENTINEL_TP)


def test_removed_legacy_constants_are_gone():
    # The pre-WARP-85 scan-job exit constant must not silently linger.
    assert not hasattr(ssj, "_DEFAULT_STRATEGY_TP_PCT")
    assert not hasattr(ssj, "_DEFAULT_STRATEGY_SL_PCT")
