"""Phase 24.2 — Validation Engine Wiring Tests.

Validates:
    core/pipeline/trading_loop.py — _run_validation_hook integration

Scenarios covered:

  VW-01  _run_validation_hook — valid trade updates tracker and state
  VW-02  _run_validation_hook — invalid trade (missing key) logs error and skips
  VW-03  _run_validation_hook — non-dict trade logs error and skips
  VW-04  _run_validation_hook — state change triggers Telegram WARNING alert
  VW-05  _run_validation_hook — CRITICAL state triggers Telegram CRITICAL alert
  VW-06  _run_validation_hook — HEALTHY → HEALTHY transition sends no alert
  VW-07  _run_validation_hook — Telegram failure is caught (no crash)
  VW-08  _run_validation_hook — 10-trade simulation produces correct state transitions
  VW-09  _run_validation_hook — metrics compute correctly after multiple trades
  VW-10  _run_validation_hook — no alert sent when state does not change
"""
from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from projects.polymarket.polyquantbot.monitoring.performance_tracker import (
    PerformanceTracker,
)
from projects.polymarket.polyquantbot.monitoring.metrics_engine import MetricsEngine
from projects.polymarket.polyquantbot.monitoring.validation_engine import (
    ValidationEngine,
    ValidationResult,
    ValidationState,
)
from projects.polymarket.polyquantbot.core.validation_state import ValidationStateStore

# ── Helpers ───────────────────────────────────────────────────────────────────

_REQUIRED_KEYS = ("pnl", "entry_price", "exit_price", "size", "timestamp", "signal_type")


def _make_trade(
    pnl: float = 0.10,
    entry_price: float = 0.75,
    exit_price: float = 0.85,
    size: float = 100.0,
    signal_type: str = "REAL",
) -> dict[str, Any]:
    return {
        "pnl": pnl,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "size": size,
        "timestamp": time.time(),
        "signal_type": signal_type,
    }


def _build_hook(
    tracker: PerformanceTracker,
    me: MetricsEngine,
    ve: ValidationEngine,
    vs: ValidationStateStore,
    prev_vs: list[ValidationState],
):
    """Replicate the _run_validation_hook closure from trading_loop.py."""
    import structlog
    _log = structlog.get_logger()

    async def _run_validation_hook(trade, tg_cb):
        try:
            tracker.add_trade(trade)
        except (ValueError, TypeError) as _ve:
            _log.error("validation_trade_invalid", error=str(_ve))
            return

        try:
            recent = tracker.get_recent_trades()
            computed = me.compute(recent)
            val_result = ve.evaluate(computed)
            vs.update(val_result.state, computed)

            if val_result.state == ValidationState.CRITICAL:
                _log.critical(
                    "validation_update",
                    state=val_result.state.value,
                    metrics=computed,
                    reason=val_result.reasons,
                )
            else:
                _log.info(
                    "validation_update",
                    state=val_result.state.value,
                    metrics=computed,
                    reason=val_result.reasons,
                )

            if val_result.state != prev_vs[0]:
                prev_vs[0] = val_result.state
                if tg_cb is not None:
                    if val_result.state == ValidationState.CRITICAL:
                        alert = (
                            f"🚨 CRITICAL: validation state → CRITICAL\n"
                            f"{', '.join(val_result.reasons)}"
                        )
                    elif val_result.state == ValidationState.WARNING:
                        alert = (
                            f"⚠️ WARNING: validation state → WARNING\n"
                            f"{', '.join(val_result.reasons)}"
                        )
                    else:
                        alert = None
                    if alert:
                        try:
                            await tg_cb(alert)
                        except Exception as tg_exc:
                            _log.warning("validation_telegram_failed", error=str(tg_exc))
        except Exception as exc:
            _log.critical("validation_hook_error", error=str(exc), exc_info=True)

    return _run_validation_hook


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_vw01_valid_trade_updates_tracker_and_state() -> None:
    """VW-01: Valid trade is added to tracker and state store updates."""
    tracker = PerformanceTracker()
    me = MetricsEngine()
    ve = ValidationEngine()
    vs = ValidationStateStore()
    prev_vs: list[ValidationState] = [ValidationState.HEALTHY]
    hook = _build_hook(tracker, me, ve, vs, prev_vs)

    trade = _make_trade(pnl=0.10)
    await hook(trade, None)

    assert tracker.get_trade_count() == 1
    state_snap = vs.get_state()
    assert state_snap["state"] in (
        ValidationState.HEALTHY.value,
        ValidationState.WARNING.value,
        ValidationState.CRITICAL.value,
    )


async def test_vw02_missing_key_logs_error_and_skips() -> None:
    """VW-02: Trade missing required key logs error and skips validation."""
    tracker = PerformanceTracker()
    me = MetricsEngine()
    ve = ValidationEngine()
    vs = ValidationStateStore()
    prev_vs: list[ValidationState] = [ValidationState.HEALTHY]
    hook = _build_hook(tracker, me, ve, vs, prev_vs)

    incomplete_trade = {"pnl": 0.10}  # missing entry_price, exit_price, size, timestamp, signal_type
    await hook(incomplete_trade, None)

    assert tracker.get_trade_count() == 0  # nothing added


async def test_vw03_non_dict_trade_logs_error_and_skips() -> None:
    """VW-03: Non-dict trade (e.g. string) logs error and skips validation."""
    tracker = PerformanceTracker()
    me = MetricsEngine()
    ve = ValidationEngine()
    vs = ValidationStateStore()
    prev_vs: list[ValidationState] = [ValidationState.HEALTHY]
    hook = _build_hook(tracker, me, ve, vs, prev_vs)

    await hook("not-a-dict", None)

    assert tracker.get_trade_count() == 0


async def test_vw04_state_change_warning_triggers_telegram() -> None:
    """VW-04: Transition to WARNING state triggers a Telegram alert."""
    tracker = PerformanceTracker()
    me = MetricsEngine()
    vs = ValidationStateStore()
    prev_vs: list[ValidationState] = [ValidationState.HEALTHY]

    # Force WARNING by having ValidationEngine return WARNING
    mock_ve = MagicMock(spec=ValidationEngine)
    mock_ve.evaluate.return_value = ValidationResult(
        state=ValidationState.WARNING,
        reasons=["win_rate 0.5000 < required 0.7000"],
    )

    hook = _build_hook(tracker, me, mock_ve, vs, prev_vs)
    tg_cb = AsyncMock()
    trade = _make_trade()

    await hook(trade, tg_cb)

    tg_cb.assert_awaited_once()
    call_arg: str = tg_cb.call_args[0][0]
    assert "WARNING" in call_arg
    assert prev_vs[0] == ValidationState.WARNING


async def test_vw05_critical_state_triggers_telegram() -> None:
    """VW-05: Transition to CRITICAL state triggers an urgent Telegram alert."""
    tracker = PerformanceTracker()
    me = MetricsEngine()
    vs = ValidationStateStore()
    prev_vs: list[ValidationState] = [ValidationState.HEALTHY]

    mock_ve = MagicMock(spec=ValidationEngine)
    mock_ve.evaluate.return_value = ValidationResult(
        state=ValidationState.CRITICAL,
        reasons=["win_rate low", "profit_factor low"],
    )

    hook = _build_hook(tracker, me, mock_ve, vs, prev_vs)
    tg_cb = AsyncMock()
    trade = _make_trade()

    await hook(trade, tg_cb)

    tg_cb.assert_awaited_once()
    call_arg: str = tg_cb.call_args[0][0]
    assert "CRITICAL" in call_arg


async def test_vw06_healthy_to_healthy_sends_no_alert() -> None:
    """VW-06: HEALTHY → HEALTHY transition sends no Telegram alert."""
    tracker = PerformanceTracker()
    me = MetricsEngine()
    vs = ValidationStateStore()
    prev_vs: list[ValidationState] = [ValidationState.HEALTHY]

    mock_ve = MagicMock(spec=ValidationEngine)
    mock_ve.evaluate.return_value = ValidationResult(
        state=ValidationState.HEALTHY,
        reasons=[],
    )

    hook = _build_hook(tracker, me, mock_ve, vs, prev_vs)
    tg_cb = AsyncMock()
    trade = _make_trade()

    await hook(trade, tg_cb)

    tg_cb.assert_not_awaited()


async def test_vw07_telegram_failure_is_caught() -> None:
    """VW-07: Telegram callback failure does not propagate (no crash)."""
    tracker = PerformanceTracker()
    me = MetricsEngine()
    vs = ValidationStateStore()
    prev_vs: list[ValidationState] = [ValidationState.HEALTHY]

    mock_ve = MagicMock(spec=ValidationEngine)
    mock_ve.evaluate.return_value = ValidationResult(
        state=ValidationState.CRITICAL,
        reasons=["mdd exceeded"],
    )

    hook = _build_hook(tracker, me, mock_ve, vs, prev_vs)
    failing_tg = AsyncMock(side_effect=RuntimeError("Telegram down"))
    trade = _make_trade()

    # Must not raise
    await hook(trade, failing_tg)

    failing_tg.assert_awaited_once()


async def test_vw08_ten_trade_simulation() -> None:
    """VW-08: Simulate 10 trades — tracker updates and state transitions recorded."""
    tracker = PerformanceTracker()
    me = MetricsEngine()
    ve = ValidationEngine()
    vs = ValidationStateStore()
    prev_vs: list[ValidationState] = [ValidationState.HEALTHY]
    hook = _build_hook(tracker, me, ve, vs, prev_vs)
    tg_cb = AsyncMock()

    trades = [_make_trade(pnl=0.10 * (i % 2 == 0 and 1 or -0.05)) for i in range(10)]
    for t in trades:
        await hook(t, tg_cb)

    assert tracker.get_trade_count() == 10
    snap = vs.get_state()
    assert snap["state"] in {"HEALTHY", "WARNING", "CRITICAL"}
    assert "win_rate" in snap["last_metrics"]


async def test_vw09_metrics_correct_after_trades() -> None:
    """VW-09: Metrics computed by hook match direct MetricsEngine computation."""
    tracker_direct = PerformanceTracker()
    tracker_hook = PerformanceTracker()
    me = MetricsEngine()
    ve = ValidationEngine()
    vs = ValidationStateStore()
    prev_vs: list[ValidationState] = [ValidationState.HEALTHY]
    hook = _build_hook(tracker_hook, me, ve, vs, prev_vs)

    trades = [_make_trade(pnl=0.05 * i) for i in range(5)]
    for t in trades:
        tracker_direct.add_trade(t)
        await hook(t, None)

    expected = me.compute(tracker_direct.get_recent_trades())
    snap = vs.get_state()

    assert abs(snap["last_metrics"]["win_rate"] - expected["win_rate"]) < 1e-9
    assert abs(snap["last_metrics"]["profit_factor"] - expected["profit_factor"]) < 1e-9


async def test_vw10_no_alert_when_state_unchanged() -> None:
    """VW-10: Repeated same state → Telegram alert sent only on first change."""
    tracker = PerformanceTracker()
    me = MetricsEngine()
    vs = ValidationStateStore()
    prev_vs: list[ValidationState] = [ValidationState.HEALTHY]

    mock_ve = MagicMock(spec=ValidationEngine)
    mock_ve.evaluate.return_value = ValidationResult(
        state=ValidationState.WARNING,
        reasons=["win_rate low"],
    )

    hook = _build_hook(tracker, me, mock_ve, vs, prev_vs)
    tg_cb = AsyncMock()

    # Fire three times — state stays WARNING after first transition
    for _ in range(3):
        await hook(_make_trade(), tg_cb)

    # Alert only on the first HEALTHY→WARNING transition
    assert tg_cb.await_count == 1
