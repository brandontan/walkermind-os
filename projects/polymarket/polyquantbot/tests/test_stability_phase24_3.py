"""Phase 24.3 — Stability Infrastructure Tests.

Validates the new capabilities added in the Phase 24.3 stability pass:

  VS-01  PerformanceTracker.update_trade — found and updated
  VS-02  PerformanceTracker.update_trade — missing trade_id returns False
  VS-03  PerformanceTracker.add_trade — trade_id stored in index
  VS-04  PerformanceTracker — index shifts correctly after window trim
  VS-05  PerformanceTracker — duplicate close event ignored (pnl overwritten)
  VS-06  _run_closed_validation_hook — updates tracker pnl and re-validates
  VS-07  _run_closed_validation_hook — skips on zero pnl
  VS-08  _run_closed_validation_hook — skips when trade_id not in window
  VS-09  WARNING alert cooldown — max 1 alert in 10 min
  VS-10  CRITICAL alert always sent regardless of cooldown
  VS-11  validation_update fields — trade_count, rolling_window_size, last_pnl verified via tracker state
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
    trade_id: str | None = None,
) -> dict[str, Any]:
    t: dict[str, Any] = {
        "pnl": pnl,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "size": size,
        "timestamp": time.time(),
        "signal_type": signal_type,
    }
    if trade_id is not None:
        t["trade_id"] = trade_id
    return t


def _build_closed_hook(
    tracker: PerformanceTracker,
    me: MetricsEngine,
    ve: ValidationEngine,
    vs: ValidationStateStore,
    prev_vs: list[ValidationState],
    warning_last_alerted: list[float],
    validation_hook_errors: list[int],
    *,
    warning_cooldown_s: float = 600.0,
):
    """Replicate the _run_closed_validation_hook closure from trading_loop.py."""
    import structlog
    _log = structlog.get_logger()

    async def _emit(val_result, computed, tg_cb):
        vs.update(val_result.state, computed)
        _tc = tracker.get_trade_count()
        _last_pnl = computed.get("last_pnl", computed.get("expectancy", 0.0))
        _log_fn = _log.critical if val_result.state == ValidationState.CRITICAL else _log.info
        _log_fn(
            "validation_update",
            state=val_result.state.value,
            metrics=computed,
            reason=val_result.reasons,
            trade_count=_tc,
            rolling_window_size=tracker.max_window,
            last_pnl=round(_last_pnl, 6),
        )
        if val_result.state != prev_vs[0] or val_result.state == ValidationState.CRITICAL:
            _now_alert = time.time()
            _send_alert = True
            if val_result.state == ValidationState.CRITICAL:
                _alert = f"🚨 CRITICAL: {', '.join(val_result.reasons)}"
            elif val_result.state == ValidationState.WARNING:
                if _now_alert - warning_last_alerted[0] < warning_cooldown_s:
                    _send_alert = False
                _alert = f"⚠️ WARNING: {', '.join(val_result.reasons)}"
            else:
                _alert = None
            if val_result.state != prev_vs[0]:
                prev_vs[0] = val_result.state
            if _alert and _send_alert and tg_cb is not None:
                if val_result.state == ValidationState.WARNING:
                    warning_last_alerted[0] = _now_alert
                try:
                    await tg_cb(_alert)
                except Exception as exc:
                    _log.warning("validation_telegram_failed", error=str(exc))

    async def _run_closed_validation_hook(trade_id, pnl, tg_cb):
        if not trade_id or pnl == 0.0:
            return
        _updated = tracker.update_trade(trade_id, pnl)
        if not _updated:
            _log.warning("closed_validation_trade_not_found", trade_id=trade_id, pnl=pnl)
            return
        try:
            recent = tracker.get_recent_trades()
            computed = me.compute(recent)
            val_result = ve.evaluate(computed)
            await _emit(val_result, computed, tg_cb)
        except Exception as exc:
            validation_hook_errors[0] += 1
            _log.critical("closed_validation_hook_error", error=str(exc))

    return _run_closed_validation_hook


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_vs01_update_trade_found_and_updated() -> None:
    """VS-01: update_trade overwrites pnl for a known trade_id."""
    tracker = PerformanceTracker()
    trade = _make_trade(pnl=0.0, trade_id="t1")
    tracker.add_trade(trade)
    assert tracker.trades[0]["pnl"] == 0.0

    result = tracker.update_trade("t1", 0.42)
    assert result is True
    assert tracker.trades[0]["pnl"] == 0.42


def test_vs02_update_trade_missing_returns_false() -> None:
    """VS-02: update_trade returns False when trade_id is not in window."""
    tracker = PerformanceTracker()
    result = tracker.update_trade("nonexistent", 1.0)
    assert result is False


def test_vs03_add_trade_stores_trade_id_index() -> None:
    """VS-03: add_trade stores trade_id → index mapping."""
    tracker = PerformanceTracker()
    tracker.add_trade(_make_trade(trade_id="abc"))
    assert "abc" in tracker._trade_id_index
    assert tracker._trade_id_index["abc"] == 0


def test_vs04_index_shifts_after_window_trim() -> None:
    """VS-04: After window trim, trade_id indices remain valid."""
    tracker = PerformanceTracker(max_window=3)
    for i in range(3):
        tracker.add_trade(_make_trade(pnl=0.0, trade_id=f"t{i}"))

    # t0 is index 0, t1 = 1, t2 = 2
    assert tracker._trade_id_index["t0"] == 0

    # Adding a 4th trade trims t0
    tracker.add_trade(_make_trade(pnl=0.0, trade_id="t3"))
    assert "t0" not in tracker._trade_id_index  # trimmed
    assert tracker._trade_id_index["t1"] == 0   # shifted down by 1
    assert tracker._trade_id_index["t2"] == 1
    assert tracker._trade_id_index["t3"] == 2


def test_vs05_duplicate_close_event_overwrites_pnl() -> None:
    """VS-05: Calling update_trade twice with same trade_id is idempotent."""
    tracker = PerformanceTracker()
    tracker.add_trade(_make_trade(pnl=0.0, trade_id="dup"))
    tracker.update_trade("dup", 10.0)
    tracker.update_trade("dup", 10.0)  # duplicate close event
    assert tracker.trades[0]["pnl"] == 10.0
    assert tracker.get_trade_count() == 1  # no duplicate entries


async def test_vs06_closed_hook_updates_pnl_and_revalidates() -> None:
    """VS-06: _run_closed_validation_hook updates tracker pnl and runs validation."""
    tracker = PerformanceTracker()
    me = MetricsEngine()
    ve = ValidationEngine()
    vs = ValidationStateStore()
    prev_vs = [ValidationState.HEALTHY]
    wla: list[float] = [0.0]
    errs: list[int] = [0]

    hook = _build_closed_hook(tracker, me, ve, vs, prev_vs, wla, errs)

    # Add an open-trade entry (pnl=0)
    tracker.add_trade(_make_trade(pnl=0.0, trade_id="trade-x"))
    assert tracker.trades[0]["pnl"] == 0.0

    # Close it with real pnl
    await hook("trade-x", 5.0, None)

    assert tracker.trades[0]["pnl"] == 5.0
    snap = vs.get_state()
    assert snap["state"] in {"HEALTHY", "WARNING", "CRITICAL"}


async def test_vs07_closed_hook_skips_zero_pnl() -> None:
    """VS-07: _run_closed_validation_hook skips update when pnl == 0.0."""
    tracker = PerformanceTracker()
    me = MetricsEngine()
    ve = ValidationEngine()
    vs = ValidationStateStore()
    prev_vs = [ValidationState.HEALTHY]
    wla: list[float] = [0.0]
    errs: list[int] = [0]

    hook = _build_closed_hook(tracker, me, ve, vs, prev_vs, wla, errs)
    tracker.add_trade(_make_trade(pnl=0.0, trade_id="open-trade"))

    await hook("open-trade", 0.0, None)  # zero pnl → skip

    # pnl stays 0.0 — no update performed
    assert tracker.trades[0]["pnl"] == 0.0


async def test_vs08_closed_hook_logs_warning_when_not_found() -> None:
    """VS-08: _run_closed_validation_hook handles missing trade_id gracefully."""
    tracker = PerformanceTracker()
    me = MetricsEngine()
    ve = ValidationEngine()
    vs = ValidationStateStore()
    prev_vs = [ValidationState.HEALTHY]
    wla: list[float] = [0.0]
    errs: list[int] = [0]

    hook = _build_closed_hook(tracker, me, ve, vs, prev_vs, wla, errs)

    # Should not raise even when trade_id not found
    await hook("ghost-trade", 99.0, None)

    assert tracker.get_trade_count() == 0  # nothing added


async def test_vs09_warning_alert_cooldown() -> None:
    """VS-09: WARNING alert suppressed within 10-min cooldown window."""
    tracker = PerformanceTracker()
    me = MetricsEngine()
    mock_ve = MagicMock(spec=ValidationEngine)
    mock_ve.evaluate.return_value = ValidationResult(
        state=ValidationState.WARNING,
        reasons=["win_rate low"],
    )
    vs = ValidationStateStore()
    prev_vs = [ValidationState.HEALTHY]
    wla: list[float] = [0.0]
    errs: list[int] = [0]

    hook = _build_closed_hook(
        tracker, me, mock_ve, vs, prev_vs, wla, errs, warning_cooldown_s=600.0
    )
    tracker.add_trade(_make_trade(pnl=0.0, trade_id="t1"))
    tracker.add_trade(_make_trade(pnl=0.0, trade_id="t2"))

    tg_cb = AsyncMock()

    # First close — WARNING transition fires alert
    await hook("t1", 1.0, tg_cb)
    assert tg_cb.await_count == 1

    # Second close — still WARNING, within cooldown → no alert
    await hook("t2", 2.0, tg_cb)
    assert tg_cb.await_count == 1  # still 1, not 2


async def test_vs10_critical_always_sent() -> None:
    """VS-10: CRITICAL alert is always sent regardless of cooldown state."""
    tracker = PerformanceTracker()
    me = MetricsEngine()
    mock_ve = MagicMock(spec=ValidationEngine)
    mock_ve.evaluate.return_value = ValidationResult(
        state=ValidationState.CRITICAL,
        reasons=["mdd exceeded", "win_rate low"],
    )
    vs = ValidationStateStore()
    prev_vs = [ValidationState.CRITICAL]  # already in CRITICAL
    wla: list[float] = [time.time()]       # cooldown recently triggered
    errs: list[int] = [0]

    hook = _build_closed_hook(tracker, me, mock_ve, vs, prev_vs, wla, errs)
    tracker.add_trade(_make_trade(pnl=0.0, trade_id="c1"))
    tracker.add_trade(_make_trade(pnl=0.0, trade_id="c2"))

    tg_cb = AsyncMock()
    await hook("c1", -5.0, tg_cb)
    await hook("c2", -5.0, tg_cb)

    # Both CRITICAL alerts must fire
    assert tg_cb.await_count == 2


async def test_vs11_validation_update_log_includes_observability_fields() -> None:
    """VS-11: After closed-trade hook, tracker reflects correct trade_count and updated pnl."""
    tracker = PerformanceTracker(max_window=50)
    me = MetricsEngine()
    mock_ve = MagicMock(spec=ValidationEngine)
    mock_ve.evaluate.return_value = ValidationResult(
        state=ValidationState.HEALTHY,
        reasons=[],
    )
    vs = ValidationStateStore()
    prev_vs = [ValidationState.HEALTHY]
    wla: list[float] = [0.0]
    errs: list[int] = [0]

    hook = _build_closed_hook(tracker, me, mock_ve, vs, prev_vs, wla, errs)
    tracker.add_trade(_make_trade(pnl=0.0, trade_id="obs1"))

    await hook("obs1", 3.0, None)

    # Confirm tracker fields that would appear in validation_update log
    assert tracker.get_trade_count() == 1
    assert tracker.max_window == 50
    assert tracker.trades[0]["pnl"] == 3.0
    snap = vs.get_state()
    assert "win_rate" in snap["last_metrics"]
