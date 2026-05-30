"""Regression: bankroll circuit breaker (WARP/R00T/bankroll-circuit-breaker).

Per-user latch in ``services.signal_scan.signal_scan_job._process_candidate``
step 0a. When a user's current balance drops below
``baseline * BANKROLL_CIRCUIT_BREAKER_THRESHOLD`` the breaker trips and
subsequent candidates short-circuit with
``scan_outcome="skipped_circuit_breaker"`` BEFORE dedup / open-position /
strategy gates. The latch only releases when balance climbs back above
``baseline * THRESHOLD * (1 + HYSTERESIS)``.

Reference baseline is the slow-moving ``_bankroll_ema_baseline``
maintained by Lane 5 (``bankroll-dynamic-sizing``) — same source of
truth, no duplicate state. Crash-recovery resume (step 0) runs FIRST so
already-approved-but-interrupted trades still complete; the breaker
only blocks NEW entries.

Knobs (config.py):
  - ``BANKROLL_CIRCUIT_BREAKER_ENABLED`` (default False — dark launch)
  - ``BANKROLL_CIRCUIT_BREAKER_THRESHOLD`` (default 0.20)
  - ``BANKROLL_CIRCUIT_BREAKER_HYSTERESIS`` (default 0.10)

Polybot directive: 1.4 + #6 (bankroll service / circuit breaker).
Failure mode prevented: Appendix C "circuit breaker loop" — the
hysteresis cushion stops the breaker from flapping at the trip boundary.

Guard lives in:
  ``services.signal_scan.signal_scan_job._process_candidate`` step 0a
Helper lives in:
  ``services.signal_scan.signal_scan_job._evaluate_bankroll_circuit_breaker``
"""
from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from projects.polymarket.crusaderbot import config as crusaderbot_config
from projects.polymarket.crusaderbot.domain.strategy import (
    StrategyRegistry,
    bootstrap_default_strategies,
)
from projects.polymarket.crusaderbot.domain.strategy.types import SignalCandidate
from projects.polymarket.crusaderbot.services.signal_scan import (
    signal_scan_job as ssj,
)
from projects.polymarket.crusaderbot.services.trade_engine import TradeResult


_USER_UUID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
_MARKET_ID = "circuit-breaker-market"


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
    StrategyRegistry._reset_for_tests()
    ssj._bankroll_reset_for_tests()
    crusaderbot_config.get_settings.cache_clear()
    yield
    StrategyRegistry._reset_for_tests()
    ssj._bankroll_reset_for_tests()
    crusaderbot_config.get_settings.cache_clear()


# ---------------------------------------------------------------------
# Source-level pins — fail closed if the guard is removed or scope shifts.
# ---------------------------------------------------------------------


def test_process_candidate_has_circuit_breaker_gate():
    """`_process_candidate` must contain the `skipped_circuit_breaker`
    outcome path; removing it would let drained users keep firing.
    """
    src = inspect.getsource(ssj._process_candidate)
    assert "skipped_circuit_breaker" in src, (
        "Regression: _process_candidate lost its bankroll circuit-breaker gate."
    )


def test_process_candidate_reads_enable_knob():
    """The gate must check `BANKROLL_CIRCUIT_BREAKER_ENABLED` so it stays
    dark-launched OFF by default and can be toggled without redeploy.
    """
    src = inspect.getsource(ssj._process_candidate)
    assert "BANKROLL_CIRCUIT_BREAKER_ENABLED" in src, (
        "Regression: circuit breaker must read the ENABLED knob."
    )


def test_gate_runs_after_crash_recovery():
    """Source ordering pin: the crash-recovery resume (step 0) must
    execute BEFORE the breaker gate (step 0a). Otherwise an
    already-approved-but-interrupted trade could be locked out by a
    breaker that tripped after the crash."""
    src = inspect.getsource(ssj._process_candidate)
    # The crash-recovery branch is gated on `pub_uuid is not None` +
    # references _load_stale_queued_row; the breaker block is the
    # `# 0a.` block. Pin: recovery comment line appears before breaker
    # comment line.
    recovery_idx = src.find("# 0. Crash-recovery resume")
    breaker_idx = src.find("# 0a. Bankroll circuit breaker")
    assert recovery_idx != -1 and breaker_idx != -1, (
        "Lost step-numbering comments — cannot verify ordering."
    )
    assert recovery_idx < breaker_idx, (
        "Crash-recovery (step 0) must run BEFORE the circuit breaker "
        "(step 0a) so in-flight trades complete after a restart."
    )


def test_helper_uses_lane5_baseline():
    """Helper must read the same ``_bankroll_ema_baseline`` dict that
    Lane 5 maintains — duplicating the baseline would let the breaker
    and sizing multiplier drift apart, hiding regressions."""
    src = inspect.getsource(ssj._evaluate_bankroll_circuit_breaker)
    assert "_bankroll_ema_baseline" in src, (
        "Regression: circuit breaker must reuse Lane 5's "
        "_bankroll_ema_baseline; do not introduce a second baseline source."
    )


# ---------------------------------------------------------------------
# Config knob — defaults + validators.
# ---------------------------------------------------------------------


def test_circuit_breaker_default_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default OFF so this lane ships dark and the operator chooses when
    to enable after watching the trip rate."""
    _set_required_env(monkeypatch)
    monkeypatch.delenv("BANKROLL_CIRCUIT_BREAKER_ENABLED", raising=False)
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert s.BANKROLL_CIRCUIT_BREAKER_ENABLED is False


def test_circuit_breaker_default_thresholds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defaults match directive #6: trip at 20% of baseline, resume with
    10% hysteresis cushion."""
    _set_required_env(monkeypatch)
    monkeypatch.delenv("BANKROLL_CIRCUIT_BREAKER_THRESHOLD", raising=False)
    monkeypatch.delenv("BANKROLL_CIRCUIT_BREAKER_HYSTERESIS", raising=False)
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert s.BANKROLL_CIRCUIT_BREAKER_THRESHOLD == 0.20
    assert s.BANKROLL_CIRCUIT_BREAKER_HYSTERESIS == 0.10


@pytest.mark.parametrize("bad", ["0", "-0.1", "1.5", "nan", "inf", "-inf"])
def test_threshold_rejects_invalid(
    monkeypatch: pytest.MonkeyPatch, bad: str,
) -> None:
    """Threshold outside (0, 1] would mean 'never trip' (0) or 'always
    tripped' (> 1) — both silent kill switches."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("BANKROLL_CIRCUIT_BREAKER_THRESHOLD", bad)
    with pytest.raises(Exception) as excinfo:
        crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert "BANKROLL_CIRCUIT_BREAKER_THRESHOLD" in str(excinfo.value)


@pytest.mark.parametrize("bad", ["-0.1", "1.5", "nan", "inf", "-inf"])
def test_hysteresis_rejects_invalid(
    monkeypatch: pytest.MonkeyPatch, bad: str,
) -> None:
    """Hysteresis outside [0, 1]: negative would invert the gate;
    > 1 would lock the breaker permanently once tripped."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("BANKROLL_CIRCUIT_BREAKER_HYSTERESIS", bad)
    with pytest.raises(Exception) as excinfo:
        crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert "BANKROLL_CIRCUIT_BREAKER_HYSTERESIS" in str(excinfo.value)


# ---------------------------------------------------------------------
# Helper math — latch transitions + fail-safes.
# ---------------------------------------------------------------------


def _seed_baseline(user_id: str, baseline: float) -> None:
    """Inject a baseline directly so the helper's branch on `baseline is
    not None` resolves true without going through the EMA bootstrap path.
    """
    ssj._bankroll_ema_baseline[str(user_id)] = baseline
    ssj._bankroll_ema_baseline_active[str(user_id)] = baseline


def _evaluate(uid: str, balance: float, threshold: float = 0.20, hysteresis: float = 0.10) -> bool:
    return ssj._evaluate_bankroll_circuit_breaker(
        uid, balance, threshold=threshold, hysteresis=hysteresis,
    )


def test_helper_does_not_trip_above_threshold():
    """Balance well above threshold = breaker latch stays False."""
    _seed_baseline("u-1", 1000.0)
    assert _evaluate("u-1", 950.0) is False
    assert ssj._bankroll_circuit_tripped.get("u-1", False) is False


def test_helper_trips_below_threshold():
    """Balance below baseline * 0.20 = breaker trips on this call."""
    _seed_baseline("u-2", 1000.0)
    # 199 < 1000 * 0.20 = 200 → trips
    assert _evaluate("u-2", 199.0) is True
    assert ssj._bankroll_circuit_tripped["u-2"] is True


def test_helper_latched_below_resume_bound():
    """Once tripped, the latch stays True until balance exceeds
    `baseline * threshold * (1 + hysteresis)`. Reading 210 (above the
    trip bound 200 but below the resume bound 220) must NOT release the
    breaker.
    """
    _seed_baseline("u-3", 1000.0)
    assert _evaluate("u-3", 199.0) is True   # trips
    # 200 * 1.10 = 220; 210 is below that → latched
    assert _evaluate("u-3", 210.0) is True
    assert ssj._bankroll_circuit_tripped["u-3"] is True


def test_helper_releases_above_resume_bound():
    """Latched breaker releases when balance climbs above the resume
    bound. baseline 1000 * threshold 0.20 * (1 + 0.10) = 220."""
    _seed_baseline("u-4", 1000.0)
    assert _evaluate("u-4", 199.0) is True   # trips
    # 221 > 220 → released
    assert _evaluate("u-4", 221.0) is False
    assert ssj._bankroll_circuit_tripped["u-4"] is False


def test_helper_no_baseline_fail_safe():
    """First observation (no baseline) cannot measure deviation against
    an unknown reference — fail safe = NOT tripped."""
    # No seed; baseline absent.
    assert _evaluate("u-5", 50.0) is False
    assert ssj._bankroll_circuit_tripped.get("u-5", False) is False


def test_helper_non_positive_balance_fail_safe():
    """Non-positive / non-finite balance = fail-safe NOT tripped (we
    can't tell if it's a stale read or a real zero — don't lock the
    user out on noise)."""
    _seed_baseline("u-6", 1000.0)
    assert _evaluate("u-6", 0.0) is False
    assert _evaluate("u-6", -1.0) is False
    assert _evaluate("u-6", float("nan")) is False
    assert ssj._bankroll_circuit_tripped.get("u-6", False) is False


def test_helper_zero_hysteresis_thrashes_at_boundary():
    """Pin: hysteresis=0 lets the breaker release immediately above the
    trip bound (no cushion). This is the failure mode the default 0.10
    cushion exists to prevent — documents the contract so an operator
    who flips hysteresis to 0 understands the consequence."""
    _seed_baseline("u-7", 1000.0)
    # Trip at 199 (< 200)
    assert _evaluate("u-7", 199.0, hysteresis=0.0) is True
    # 201 > 200 with no cushion → released immediately
    assert _evaluate("u-7", 201.0, hysteresis=0.0) is False


# ---------------------------------------------------------------------
# Behavioural integration — call _process_candidate end-to-end.
# ---------------------------------------------------------------------


def _user_row(balance: float = 100.0) -> dict:
    return {
        "user_id": _USER_UUID,
        "telegram_user_id": 99,
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


def _market_row() -> dict:
    return {
        "id": _MARKET_ID,
        "slug": "circuit-breaker-market",
        "question": "Will X happen?",
        "status": "active",
        "yes_price": 0.65,
        "no_price": 0.35,
        "yes_token_id": "tok_yes",
        "no_token_id": "tok_no",
        "liquidity_usdc": 20000.0,
    }


def _candidate() -> SignalCandidate:
    return SignalCandidate(
        market_id=_MARKET_ID,
        condition_id=_MARKET_ID,
        side="YES",
        confidence=0.7,
        suggested_size_usdc=10.0,
        strategy_name="late_entry_v3",
        signal_ts=datetime.now(timezone.utc),
        metadata={
            "market_id": _MARKET_ID,
            "entry_price": 0.65,
            "fav_price_min": 0.60,
            "fav_price_max": 0.70,
            "underdog_mode": False,
            "entry_price_ts": datetime.now(timezone.utc).timestamp(),
            "complete_set_edge": 0.05,
        },
    )


def _approved_trade_result() -> TradeResult:
    return TradeResult(
        approved=True,
        mode="paper",
        order_id=uuid4(),
        position_id=uuid4(),
        rejection_reason=None,
        failed_gate_step=None,
        chosen_mode="paper",
        final_size_usdc=Decimal("10"),
    )


def _run_process_candidate(*, row: dict, cand: SignalCandidate) -> bool:
    engine_called = {"called": False}

    async def _track_execute(signal):
        engine_called["called"] = True
        return _approved_trade_result()

    with patch.object(ssj, "_load_stale_queued_row", return_value=None), \
            patch.object(ssj, "_publication_already_queued", return_value=False), \
            patch.object(ssj, "_has_open_position_for_market", return_value=False), \
            patch.object(ssj, "_load_market", return_value=_market_row()), \
            patch.object(ssj, "get_live_market_price",
                         new=AsyncMock(return_value=0.66)), \
            patch.object(ssj._engine, "execute", side_effect=_track_execute), \
            patch.object(ssj, "_insert_execution_queue", return_value=True), \
            patch.object(ssj, "_mark_executed", new=AsyncMock()):
        asyncio.run(ssj._process_candidate(row, cand))
    return engine_called["called"]


def test_disabled_gate_passes_drained_user(monkeypatch: pytest.MonkeyPatch) -> None:
    """With BANKROLL_CIRCUIT_BREAKER_ENABLED=false (default) even a
    drained user reaches the engine — the gate is fully no-op."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("BANKROLL_CIRCUIT_BREAKER_ENABLED", "false")
    bootstrap_default_strategies()

    _seed_baseline(str(_USER_UUID), 1000.0)
    row = _user_row(balance=50.0)  # 50 < 200 — would trip if enabled

    assert _run_process_candidate(row=row, cand=_candidate()) is True


def test_enabled_gate_blocks_drained_user(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the breaker enabled and balance below trip bound, the
    candidate is rejected BEFORE reaching the engine."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("BANKROLL_CIRCUIT_BREAKER_ENABLED", "true")
    bootstrap_default_strategies()

    _seed_baseline(str(_USER_UUID), 1000.0)
    row = _user_row(balance=50.0)  # 50 < 200 → trips

    assert _run_process_candidate(row=row, cand=_candidate()) is False
    assert ssj._bankroll_circuit_tripped[str(_USER_UUID)] is True


def test_enabled_gate_passes_healthy_user(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the breaker enabled but balance above trip bound, the
    candidate reaches the engine — the gate is not over-eager."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("BANKROLL_CIRCUIT_BREAKER_ENABLED", "true")
    bootstrap_default_strategies()

    _seed_baseline(str(_USER_UUID), 1000.0)
    row = _user_row(balance=950.0)  # well above trip bound

    assert _run_process_candidate(row=row, cand=_candidate()) is True


def test_enabled_gate_passes_first_observation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail-safe: first scan for a user (no baseline) must NOT block —
    we can't measure deviation against an unknown reference. Operator
    is protected on day-0 against a buggy breaker."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("BANKROLL_CIRCUIT_BREAKER_ENABLED", "true")
    bootstrap_default_strategies()

    # No _seed_baseline — baseline absent.
    row = _user_row(balance=10.0)  # very low; would trip if baseline existed

    assert _run_process_candidate(row=row, cand=_candidate()) is True
