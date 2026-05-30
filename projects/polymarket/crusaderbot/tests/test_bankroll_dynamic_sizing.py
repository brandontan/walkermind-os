"""Bankroll dynamic sizing multiplier
(WARP/R00T/bankroll-dynamic-sizing, Lane 5/5 Polybot directive).

Scales the candidate's base size in ``_build_trade_signal`` by the
user's bankroll deviation from its EMA-smoothed baseline:
  - recent winners get larger entries (bounded by MULTIPLIER_MAX)
  - recent losers get smaller entries (bounded by MULTIPLIER_MIN)
  - first observation seeds the baseline → multiplier = 1.0 (no change)

Fail-safe layers (any one returns 1.0):
  - BANKROLL_DYNAMIC_SIZING_ENABLED=false (operator escape hatch)
  - User has no prior baseline (first scan after restart)
  - current_balance <= 0 or non-finite
  - config read raises (logged as warning, fall back to base size)

Risk gate (Kelly + position caps) inside the engine remains
authoritative — this layer only scales the INPUT to that gate.

State + helpers + multiplier:
  ``services.signal_scan.signal_scan_job._bankroll_multiplier``
Apply site:
  ``services.signal_scan.signal_scan_job._build_trade_signal``
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from projects.polymarket.crusaderbot import config as crusaderbot_config
from projects.polymarket.crusaderbot.domain.strategy.types import SignalCandidate
from projects.polymarket.crusaderbot.services.signal_scan import (
    signal_scan_job as ssj,
)


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("OPERATOR_CHAT_ID", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("WALLET_HD_SEED", "seed")
    monkeypatch.setenv("WALLET_ENCRYPTION_KEY", "k")
    monkeypatch.setenv("POLYGON_RPC_URL", "https://rpc")
    monkeypatch.setenv("ALCHEMY_POLYGON_WS_URL", "wss://ws")


@pytest.fixture(autouse=True)
def _isolated_state():
    ssj._bankroll_reset_for_tests()
    crusaderbot_config.get_settings.cache_clear()
    yield
    ssj._bankroll_reset_for_tests()
    crusaderbot_config.get_settings.cache_clear()


# ---------------------------------------------------------------------
# Helper math + fail-safe contract.
# ---------------------------------------------------------------------


_MIN = 0.5
_MAX = 1.5
_ALPHA = 0.05


def _mult(user_id: str, balance: float, *, throttle: float = 0.0) -> float:
    """Helper-test wrapper that defaults `min_update_interval_sec=0` so
    helper-math tests get deterministic per-call baseline updates.
    Tests that specifically validate the throttle pass `throttle=5.0`.
    """
    return ssj._bankroll_multiplier(
        user_id,
        balance,
        multiplier_min=_MIN,
        multiplier_max=_MAX,
        ema_alpha=_ALPHA,
        min_update_interval_sec=throttle,
    )


def test_first_observation_seeds_baseline_and_returns_one():
    """A brand-new user has no prior baseline — the first scan must
    return multiplier 1.0 (no scaling) and seed the EMA at the current
    balance so the NEXT scan has something to compare against."""
    m = _mult("user-A", 1000.0)
    assert m == 1.0
    assert ssj._bankroll_ema_baseline["user-A"] == pytest.approx(1000.0)


def test_growth_above_baseline_scales_up():
    """Balance grew from baseline → multiplier > 1.0 (bounded by MAX)."""
    # Seed baseline at 1000.
    _mult("user-A", 1000.0)
    # Now balance is 1200 (20% growth). Multiplier should be 1.2.
    m = _mult("user-A", 1200.0)
    assert m == pytest.approx(1.2)


def test_drawdown_scales_down():
    """Balance below baseline → multiplier < 1.0 (bounded by MIN)."""
    _mult("user-A", 1000.0)
    # Down to 800 → multiplier 0.8.
    m = _mult("user-A", 800.0)
    assert m == pytest.approx(0.8)


def test_upper_bound_caps_at_max():
    """Even a 5x growth must not exceed MULTIPLIER_MAX."""
    _mult("user-A", 1000.0)
    m = _mult("user-A", 5000.0)
    assert m == pytest.approx(_MAX)


def test_lower_bound_floors_at_min():
    """Even a 90% drawdown must not go below MULTIPLIER_MIN."""
    _mult("user-A", 1000.0)
    m = _mult("user-A", 100.0)
    assert m == pytest.approx(_MIN)


def test_non_positive_balance_returns_one():
    """A zero or negative balance must fail safe → no scaling. Avoid
    creating a baseline of 0 that would NaN every subsequent ratio."""
    assert _mult("user-A", 0.0) == 1.0
    assert _mult("user-A", -100.0) == 1.0
    assert "user-A" not in ssj._bankroll_ema_baseline


def test_non_finite_balance_returns_one():
    """NaN / +Inf / -Inf must fail safe — never write a non-finite
    baseline into the EMA, never return a non-finite multiplier."""
    for bad in (math.nan, math.inf, -math.inf):
        ssj._bankroll_reset_for_tests()
        assert _mult("user-A", bad) == 1.0
        assert "user-A" not in ssj._bankroll_ema_baseline


def test_baseline_drifts_with_ema_alpha():
    """Baseline must move slowly toward current_balance per the alpha;
    after one update at +20% the baseline shifts ~alpha * delta.
    Throttle disabled here so each call updates the baseline."""
    _mult("user-A", 1000.0)
    _mult("user-A", 1200.0)
    # Expected baseline: alpha * 1200 + (1 - alpha) * 1000 = 1010 for alpha=0.05
    assert ssj._bankroll_ema_baseline["user-A"] == pytest.approx(1010.0)


def test_throttle_blocks_intra_tick_drift():
    """Within the throttle window, subsequent calls for the same user
    must NOT update the baseline — defends the multiplier against the
    multi-candidate-per-tick case where each candidate would otherwise
    drift the baseline toward the static balance, collapsing the
    multiplier to ~1.0 for later candidates in the same tick."""
    # Seed at 1000 (this call always updates because no prior `last_update`).
    _mult("user-A", 1000.0, throttle=5.0)
    seeded_baseline = ssj._bankroll_ema_baseline["user-A"]
    # 5 rapid intra-tick calls at +20% balance — all return raw multiplier
    # from the seeded baseline, none drift it.
    for _ in range(5):
        m = _mult("user-A", 1200.0, throttle=5.0)
        assert m == pytest.approx(1.2), (
            "Throttle bypassed: intra-tick calls must use the prior "
            f"baseline so multiplier stays at 1.2 (got {m})."
        )
    # Baseline must remain at the seeded value across all 5 calls.
    assert ssj._bankroll_ema_baseline["user-A"] == pytest.approx(seeded_baseline)


def test_post_update_intra_tick_uses_active_baseline():
    """After a throttle-allowed EMA update fires, subsequent intra-tick calls
    for the same user must use the pre-update baseline (B0), not the newly
    advanced EMA value (B1).

    Regression for: intra-tick candidates computed multiplier from B1 because
    _bankroll_ema_baseline was updated before all candidates had been evaluated.
    Fix: _bankroll_ema_baseline_active freezes B0 so every call within the
    throttle window uses the same reference.
    """
    import time as _time

    # Seed at 1000 (first observation — no prior baseline).
    _mult("user-A", 1000.0, throttle=5.0)

    # Force last_update 10s into the past so the next call triggers an EMA update.
    ssj._bankroll_ema_last_update["user-A"] = _time.monotonic() - 10.0

    # Call A: elapsed >= 5s → EMA update fires. active_baseline frozen at B0=1000.
    # EMA: 0.05*1200 + 0.95*1000 = 1010 (B1, stored in _bankroll_ema_baseline).
    m_a = _mult("user-A", 1200.0, throttle=5.0)
    assert m_a == pytest.approx(1.2), (
        f"Call A must use B0=1000 → mult=1.2, got {m_a}"
    )

    # Call B: immediately after (elapsed << 5s) — throttle blocks. active_baseline
    # is still B0=1000. Without the fix it would read B1=1010 and return 1500/1010 ≈ 1.485.
    m_b = _mult("user-A", 1500.0, throttle=5.0)
    assert m_b == pytest.approx(1.5), (
        f"Call B must use frozen B0=1000 → mult=1.5, got {m_b}. "
        "If this fails (~1.485) the active-baseline fix is missing."
    )


def test_throttle_zero_disables(monkeypatch):
    """throttle=0 must update on every call (the test-fixture default
    path used by every other helper-math test)."""
    _mult("user-A", 1000.0, throttle=0.0)
    seeded = ssj._bankroll_ema_baseline["user-A"]
    _mult("user-A", 1200.0, throttle=0.0)
    after = ssj._bankroll_ema_baseline["user-A"]
    assert after != seeded, "throttle=0 must allow baseline drift on the next call."


def test_per_user_isolation():
    """Two users with independent histories must not share a baseline."""
    _mult("user-A", 1000.0)
    _mult("user-B", 500.0)
    # A's growth doesn't move B's multiplier.
    _mult("user-A", 1500.0)
    assert ssj._bankroll_ema_baseline["user-A"] != ssj._bankroll_ema_baseline["user-B"]
    m_b = _mult("user-B", 500.0)
    # B unchanged from its baseline → multiplier 1.0.
    assert m_b == pytest.approx(1.0)


def test_baseline_seeded_to_current_then_returns_one_next_call():
    """After the first call seeds the baseline at the current balance,
    if the next call has the SAME balance the multiplier must be 1.0."""
    _mult("user-A", 1000.0)
    m2 = _mult("user-A", 1000.0)
    assert m2 == pytest.approx(1.0)


# ---------------------------------------------------------------------
# Config knob — defaults + validators.
# ---------------------------------------------------------------------


def test_default_enabled_is_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ship disabled — operator must explicitly opt in after reviewing
    how the multiplier interacts with their bankroll distribution."""
    _set_required_env(monkeypatch)
    monkeypatch.delenv("BANKROLL_DYNAMIC_SIZING_ENABLED", raising=False)
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert s.BANKROLL_DYNAMIC_SIZING_ENABLED is False


def test_default_bounds_are_polybot_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert s.BANKROLL_MULTIPLIER_MIN == pytest.approx(0.5)
    assert s.BANKROLL_MULTIPLIER_MAX == pytest.approx(1.5)


def test_default_alpha_is_slow_tracking(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert s.BANKROLL_EMA_ALPHA == pytest.approx(0.05)


@pytest.mark.parametrize("knob", ["BANKROLL_MULTIPLIER_MIN", "BANKROLL_MULTIPLIER_MAX"])
@pytest.mark.parametrize("bad", ["0", "-0.1", "nan", "inf", "-inf"])
def test_bound_validator_rejects_zero_negative_and_non_finite(
    monkeypatch: pytest.MonkeyPatch, knob: str, bad: str,
) -> None:
    """Both bounds must be > 0 AND finite — non-positive would zero out
    every trade, non-finite would NaN them. Fail fast at load."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv(knob, bad)
    with pytest.raises(ValidationError) as excinfo:
        crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert "BANKROLL_MULTIPLIER" in str(excinfo.value)


@pytest.mark.parametrize("bad", ["0", "-0.1", "1.5", "nan", "inf"])
def test_alpha_validator_rejects_out_of_range(
    monkeypatch: pytest.MonkeyPatch, bad: str,
) -> None:
    """alpha must be in (0, 1] — alpha=0 freezes the baseline (no
    tracking), alpha>1 overshoots and oscillates."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("BANKROLL_EMA_ALPHA", bad)
    with pytest.raises(ValidationError) as excinfo:
        crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert "BANKROLL_EMA_ALPHA" in str(excinfo.value)


def test_alpha_upper_boundary_one_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    """alpha=1 is the inclusive upper bound (tracks current balance
    exactly, no smoothing) and must be accepted."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("BANKROLL_EMA_ALPHA", "1.0")
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert s.BANKROLL_EMA_ALPHA == pytest.approx(1.0)


def test_min_greater_than_max_rejected_at_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cross-field invariant: MIN must not exceed MAX, otherwise the
    runtime `max(MIN, min(MAX, raw))` clamp degenerates to a constant
    multiplier of MIN regardless of bankroll. Fail fast at load."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("BANKROLL_MULTIPLIER_MIN", "2.0")
    monkeypatch.setenv("BANKROLL_MULTIPLIER_MAX", "1.0")
    with pytest.raises(ValidationError) as excinfo:
        crusaderbot_config.Settings()  # type: ignore[call-arg]
    msg = str(excinfo.value)
    assert "BANKROLL_MULTIPLIER_MIN" in msg
    assert "BANKROLL_MULTIPLIER_MAX" in msg


def test_min_equal_to_max_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    """MIN == MAX is a legitimate operator config (effectively pins
    the multiplier at one value); accepted at load."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("BANKROLL_MULTIPLIER_MIN", "1.0")
    monkeypatch.setenv("BANKROLL_MULTIPLIER_MAX", "1.0")
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert s.BANKROLL_MULTIPLIER_MIN == pytest.approx(1.0)
    assert s.BANKROLL_MULTIPLIER_MAX == pytest.approx(1.0)


def test_baseline_throttle_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert s.BANKROLL_BASELINE_UPDATE_MIN_INTERVAL_SEC == pytest.approx(5.0)


def test_baseline_throttle_rejects_negative(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("BANKROLL_BASELINE_UPDATE_MIN_INTERVAL_SEC", "-1.0")
    with pytest.raises(ValidationError) as excinfo:
        crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert "BANKROLL_BASELINE_UPDATE_MIN_INTERVAL_SEC" in str(excinfo.value)


# ---------------------------------------------------------------------
# Behavioural integration — _build_trade_signal applies the multiplier.
# ---------------------------------------------------------------------


_USER_UUID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def _user_row(*, balance: float = 1000.0) -> dict:
    return {
        "user_id": _USER_UUID,
        "telegram_user_id": 42,
        "auto_trade_on": True,
        "paused": False,
        "balance_usdc": balance,
        "risk_profile": "balanced",
        "trading_mode": "paper",
        "tp_pct": 0.20,
        "sl_pct": 0.08,
        "daily_loss_override": None,
        "capital_allocation_pct": 0.10,
        "sub_account_id": uuid4(),
        "resolved_profile": "balanced",
    }


def _market() -> dict:
    return {
        "id": "m-1",
        "slug": "test-market",
        "question": "Will X?",
        "status": "active",
        "yes_price": 0.55,
        "no_price": 0.45,
        "yes_token_id": "tok_y",
        "no_token_id": "tok_n",
        "liquidity_usdc": 20000.0,
    }


def _cand(size: float = 10.0) -> SignalCandidate:
    return SignalCandidate(
        market_id="m-1",
        condition_id="m-1",
        side="YES",
        confidence=0.7,
        suggested_size_usdc=size,
        strategy_name="signal_following",
        signal_ts=datetime.now(timezone.utc),
        metadata={},
    )


def test_disabled_passes_base_size_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """When BANKROLL_DYNAMIC_SIZING_ENABLED=false, the multiplier path
    must be skipped entirely — proposed_size == base size, baseline
    EMA never seeded."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("BANKROLL_DYNAMIC_SIZING_ENABLED", "false")

    signal = ssj._build_trade_signal(
        row=_user_row(balance=2000.0),
        cand=_cand(size=10.0),
        market=_market(),
        idempotency_key="test",
    )
    assert signal.proposed_size_usdc == Decimal("10")
    # Disabled path must not pollute the EMA dict either.
    assert str(_USER_UUID) not in ssj._bankroll_ema_baseline


def test_enabled_first_call_seeds_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    """First call with the gate enabled: baseline seeds, multiplier
    = 1.0, proposed_size == base."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("BANKROLL_DYNAMIC_SIZING_ENABLED", "true")

    signal = ssj._build_trade_signal(
        row=_user_row(balance=1000.0),
        cand=_cand(size=10.0),
        market=_market(),
        idempotency_key="test",
    )
    assert signal.proposed_size_usdc == Decimal("10")
    assert ssj._bankroll_ema_baseline[str(_USER_UUID)] == pytest.approx(1000.0)


def test_enabled_second_call_scales_size_on_growth(monkeypatch: pytest.MonkeyPatch) -> None:
    """First call seeds at 1000. Second call at balance=1500 → ratio 1.5
    → multiplier capped at 1.5 → 10 * 1.5 = 15."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("BANKROLL_DYNAMIC_SIZING_ENABLED", "true")

    ssj._build_trade_signal(
        row=_user_row(balance=1000.0),
        cand=_cand(size=10.0),
        market=_market(),
        idempotency_key="seed",
    )
    signal = ssj._build_trade_signal(
        row=_user_row(balance=1500.0),
        cand=_cand(size=10.0),
        market=_market(),
        idempotency_key="grow",
    )
    assert signal.proposed_size_usdc == Decimal("15.00")


def test_enabled_second_call_scales_size_on_drawdown(monkeypatch: pytest.MonkeyPatch) -> None:
    """First call seeds at 1000. Second call at balance=500 → ratio 0.5
    → multiplier floored at 0.5 → 10 * 0.5 = 5."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("BANKROLL_DYNAMIC_SIZING_ENABLED", "true")

    ssj._build_trade_signal(
        row=_user_row(balance=1000.0),
        cand=_cand(size=10.0),
        market=_market(),
        idempotency_key="seed",
    )
    signal = ssj._build_trade_signal(
        row=_user_row(balance=500.0),
        cand=_cand(size=10.0),
        market=_market(),
        idempotency_key="drawdown",
    )
    assert signal.proposed_size_usdc == Decimal("5.00")


def test_enabled_zero_balance_falls_back_to_base(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero balance triggers helper's safety fallback (multiplier=1.0)
    → proposed_size == base."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("BANKROLL_DYNAMIC_SIZING_ENABLED", "true")

    signal = ssj._build_trade_signal(
        row=_user_row(balance=0.0),
        cand=_cand(size=10.0),
        market=_market(),
        idempotency_key="zero",
    )
    assert signal.proposed_size_usdc == Decimal("10")
