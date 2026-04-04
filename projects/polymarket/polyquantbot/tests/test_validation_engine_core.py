"""Phase 24 — Validation Engine Core Tests.

Validates:
    monitoring/performance_tracker.py
    monitoring/metrics_engine.py
    monitoring/validation_engine.py
    risk/risk_audit.py
    strategy/signal_quality.py
    core/validation_state.py

Scenarios covered:

  VE-01  PerformanceTracker — add_trade succeeds with valid trade
  VE-02  PerformanceTracker — add_trade raises ValueError on missing key
  VE-03  PerformanceTracker — add_trade raises TypeError on non-dict
  VE-04  PerformanceTracker — rolling window trims oldest trades
  VE-05  PerformanceTracker — get_recent_trades returns copy
  VE-06  PerformanceTracker — get_trade_count matches window size

  VE-07  MetricsEngine — compute returns neutral dict for empty trades
  VE-08  MetricsEngine — compute_win_rate correct
  VE-09  MetricsEngine — compute_profit_factor correct
  VE-10  MetricsEngine — compute_profit_factor zero when no losers
  VE-11  MetricsEngine — compute_expectancy correct
  VE-12  MetricsEngine — compute_drawdown correct
  VE-13  MetricsEngine — compute_drawdown zero for single-point curve
  VE-14  MetricsEngine — no NaN / inf in output

  VE-15  ValidationEngine — HEALTHY when all thresholds met
  VE-16  ValidationEngine — WARNING when exactly 1 threshold violated
  VE-17  ValidationEngine — CRITICAL when 2 thresholds violated
  VE-18  ValidationEngine — CRITICAL when MDD exceeds hard limit alone
  VE-19  ValidationEngine — result.to_dict returns correct structure

  VE-20  RiskAudit — passes compliant trade
  VE-21  RiskAudit — raises RiskAuditError when EV ≤ 0
  VE-22  RiskAudit — raises RiskAuditError when size > 10% bankroll
  VE-23  RiskAudit — raises ValueError on missing required key
  VE-24  RiskAudit — raises TypeError on non-dict input
  VE-25  RiskAudit — raises ValueError on bankroll ≤ 0

  VE-26  SignalQualityAnalyzer — separates REAL and SYNTHETIC trades
  VE-27  SignalQualityAnalyzer — zero trades returns neutral metrics
  VE-28  SignalQualityAnalyzer — drift_warning set when synthetic >> real
  VE-29  SignalQualityAnalyzer — drift_warning False when rates close

  VE-30  ValidationStateStore — initial state is HEALTHY
  VE-31  ValidationStateStore — update persists state and metrics
  VE-32  ValidationStateStore — get_state returns copy (not reference)
  VE-33  ValidationStateStore — last_update_time advances on update
"""
from __future__ import annotations

import math
import time

import pytest

from projects.polymarket.polyquantbot.monitoring.performance_tracker import (
    PerformanceTracker,
)
from projects.polymarket.polyquantbot.monitoring.metrics_engine import MetricsEngine
from projects.polymarket.polyquantbot.monitoring.validation_engine import (
    ValidationEngine,
    ValidationState,
)
from projects.polymarket.polyquantbot.risk.risk_audit import RiskAudit, RiskAuditError
from projects.polymarket.polyquantbot.strategy.signal_quality import SignalQualityAnalyzer
from projects.polymarket.polyquantbot.core.validation_state import ValidationStateStore


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _trade(
    pnl: float = 10.0,
    entry_price: float = 0.50,
    exit_price: float = 0.55,
    size: float = 100.0,
    timestamp: float = 0.0,
    signal_type: str = "REAL",
) -> dict:
    return {
        "pnl": pnl,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "size": size,
        "timestamp": timestamp,
        "signal_type": signal_type,
    }


# ─── PerformanceTracker ───────────────────────────────────────────────────────


def test_ve01_add_trade_valid():
    pt = PerformanceTracker()
    pt.add_trade(_trade())
    assert pt.get_trade_count() == 1


def test_ve02_add_trade_missing_key_raises():
    pt = PerformanceTracker()
    bad = {"pnl": 10.0}  # missing many required keys
    with pytest.raises(ValueError, match="missing required keys"):
        pt.add_trade(bad)


def test_ve03_add_trade_non_dict_raises():
    pt = PerformanceTracker()
    with pytest.raises(TypeError):
        pt.add_trade("not a dict")  # type: ignore[arg-type]


def test_ve04_rolling_window_trims_oldest():
    pt = PerformanceTracker(max_window=3)
    for i in range(5):
        pt.add_trade(_trade(pnl=float(i), timestamp=float(i)))
    assert pt.get_trade_count() == 3
    # Oldest should have been discarded; most recent pnl = 4.0
    recent = pt.get_recent_trades()
    assert recent[-1]["pnl"] == 4.0
    assert recent[0]["pnl"] == 2.0


def test_ve05_get_recent_trades_returns_copy():
    pt = PerformanceTracker()
    pt.add_trade(_trade())
    copy1 = pt.get_recent_trades()
    copy2 = pt.get_recent_trades()
    assert copy1 is not copy2
    assert copy1 == copy2


def test_ve06_get_trade_count():
    pt = PerformanceTracker()
    assert pt.get_trade_count() == 0
    pt.add_trade(_trade())
    pt.add_trade(_trade())
    assert pt.get_trade_count() == 2


# ─── MetricsEngine ────────────────────────────────────────────────────────────


def test_ve07_empty_trades_neutral_metrics():
    engine = MetricsEngine()
    result = engine.compute([])
    assert result == {"win_rate": 0.0, "profit_factor": 0.0, "expectancy": 0.0, "max_drawdown": 0.0}


def test_ve08_win_rate_correct():
    trades = [_trade(pnl=10.0), _trade(pnl=-5.0), _trade(pnl=3.0)]
    assert MetricsEngine.compute_win_rate(trades) == pytest.approx(2 / 3, rel=1e-6)


def test_ve09_profit_factor_correct():
    trades = [_trade(pnl=20.0), _trade(pnl=-10.0)]
    # PF = 20 / 10 = 2.0
    assert MetricsEngine.compute_profit_factor(trades) == pytest.approx(2.0, rel=1e-6)


def test_ve10_profit_factor_zero_when_no_losers():
    trades = [_trade(pnl=10.0), _trade(pnl=5.0)]
    assert MetricsEngine.compute_profit_factor(trades) == 0.0


def test_ve11_expectancy_correct():
    # 2 wins of 10, 1 loss of 10 → WR=2/3, avg_win=10, avg_loss=10
    # E = (2/3 * 10) - (1/3 * 10) = 6.67 - 3.33 = 3.33
    trades = [_trade(pnl=10.0), _trade(pnl=10.0), _trade(pnl=-10.0)]
    e = MetricsEngine.compute_expectancy(trades)
    assert e == pytest.approx(10 / 3, rel=1e-4)


def test_ve12_drawdown_correct():
    # equity curve: 0 → 100 → 50  peak=100, trough=50 → MDD=50%
    curve = [0.0, 100.0, 50.0]
    mdd = MetricsEngine.compute_drawdown(curve)
    assert mdd == pytest.approx(0.5, rel=1e-6)


def test_ve13_drawdown_single_point():
    assert MetricsEngine.compute_drawdown([0.0]) == 0.0
    assert MetricsEngine.compute_drawdown([]) == 0.0


def test_ve14_no_nan_or_inf():
    # All-loss scenario should not produce NaN/inf
    trades = [_trade(pnl=-5.0), _trade(pnl=-3.0)]
    result = MetricsEngine().compute(trades)
    for v in result.values():
        assert math.isfinite(v), f"Expected finite value, got {v}"


# ─── ValidationEngine ─────────────────────────────────────────────────────────


def _healthy_metrics() -> dict:
    return {"win_rate": 0.75, "profit_factor": 2.0, "max_drawdown": 0.04}


def test_ve15_healthy_state():
    engine = ValidationEngine()
    result = engine.evaluate(_healthy_metrics())
    assert result.state == ValidationState.HEALTHY
    assert result.reasons == []


def test_ve16_warning_one_violation():
    engine = ValidationEngine()
    # Only win_rate violated
    metrics = {"win_rate": 0.60, "profit_factor": 2.0, "max_drawdown": 0.04}
    result = engine.evaluate(metrics)
    assert result.state == ValidationState.WARNING
    assert len(result.reasons) == 1


def test_ve17_critical_two_violations():
    engine = ValidationEngine()
    # win_rate and profit_factor violated
    metrics = {"win_rate": 0.50, "profit_factor": 1.0, "max_drawdown": 0.04}
    result = engine.evaluate(metrics)
    assert result.state == ValidationState.CRITICAL
    assert len(result.reasons) >= 2


def test_ve18_critical_mdd_hard_limit():
    engine = ValidationEngine()
    # MDD alone exceeds hard limit → always CRITICAL
    metrics = {"win_rate": 0.75, "profit_factor": 2.0, "max_drawdown": 0.09}
    result = engine.evaluate(metrics)
    assert result.state == ValidationState.CRITICAL
    assert any("max_drawdown" in r for r in result.reasons)


def test_ve19_result_to_dict():
    engine = ValidationEngine()
    result = engine.evaluate(_healthy_metrics())
    d = result.to_dict()
    assert d["state"] == "HEALTHY"
    assert isinstance(d["reasons"], list)


# ─── RiskAudit ───────────────────────────────────────────────────────────────


def test_ve20_risk_audit_compliant_trade():
    audit = RiskAudit(bankroll=10_000.0)
    trade = {"ev": 0.05, "size": 500.0}  # 5% of bankroll ✓
    assert audit.audit_trade(trade) is True


def test_ve21_risk_audit_ev_violation():
    audit = RiskAudit(bankroll=10_000.0)
    trade = {"ev": -0.01, "size": 100.0}
    with pytest.raises(RiskAuditError, match="EV"):
        audit.audit_trade(trade)


def test_ve22_risk_audit_size_violation():
    audit = RiskAudit(bankroll=10_000.0)
    trade = {"ev": 0.05, "size": 1_500.0}  # 15% of bankroll ✗
    with pytest.raises(RiskAuditError, match="size"):
        audit.audit_trade(trade)


def test_ve23_risk_audit_missing_key():
    audit = RiskAudit(bankroll=10_000.0)
    with pytest.raises(ValueError, match="required key"):
        audit.audit_trade({"ev": 0.05})  # missing "size"


def test_ve24_risk_audit_non_dict():
    audit = RiskAudit(bankroll=10_000.0)
    with pytest.raises(TypeError):
        audit.audit_trade([0.05, 100.0])  # type: ignore[arg-type]


def test_ve25_risk_audit_invalid_bankroll():
    with pytest.raises(ValueError, match="bankroll must be > 0"):
        RiskAudit(bankroll=0.0)


# ─── SignalQualityAnalyzer ────────────────────────────────────────────────────


def test_ve26_signal_quality_separation():
    trades = [
        _trade(pnl=10.0, signal_type="REAL"),
        _trade(pnl=-5.0, signal_type="REAL"),
        _trade(pnl=15.0, signal_type="SYNTHETIC"),
        _trade(pnl=12.0, signal_type="SYNTHETIC"),
    ]
    analyzer = SignalQualityAnalyzer()
    result = analyzer.evaluate(trades)
    assert result["real_wr"] == pytest.approx(0.5, rel=1e-6)
    assert result["synthetic_wr"] == pytest.approx(1.0, rel=1e-6)
    assert result["real_pnl"] == pytest.approx(5.0, rel=1e-6)
    assert result["synthetic_pnl"] == pytest.approx(27.0, rel=1e-6)


def test_ve27_signal_quality_empty():
    analyzer = SignalQualityAnalyzer()
    result = analyzer.evaluate([])
    assert result["real_wr"] == 0.0
    assert result["synthetic_wr"] == 0.0
    assert result["real_pnl"] == 0.0
    assert result["synthetic_pnl"] == 0.0
    assert result["drift_warning"] is False


def test_ve28_drift_warning_triggered():
    # synthetic_wr = 1.0, real_wr = 0.0 → delta 1.0 > 0.20
    trades = [
        _trade(pnl=-1.0, signal_type="REAL"),
        _trade(pnl=1.0, signal_type="SYNTHETIC"),
    ]
    analyzer = SignalQualityAnalyzer()
    result = analyzer.evaluate(trades)
    assert result["drift_warning"] is True


def test_ve29_no_drift_when_rates_close():
    trades = [
        _trade(pnl=1.0, signal_type="REAL"),
        _trade(pnl=1.0, signal_type="SYNTHETIC"),
    ]
    analyzer = SignalQualityAnalyzer()
    result = analyzer.evaluate(trades)
    assert result["drift_warning"] is False


# ─── ValidationStateStore ─────────────────────────────────────────────────────


def test_ve30_initial_state_healthy():
    store = ValidationStateStore()
    state = store.get_state()
    assert state["state"] == "HEALTHY"


def test_ve31_update_persists_state_and_metrics():
    store = ValidationStateStore()
    metrics = {"win_rate": 0.75, "profit_factor": 2.0, "max_drawdown": 0.04}
    store.update(ValidationState.WARNING, metrics)
    state = store.get_state()
    assert state["state"] == "WARNING"
    assert state["last_metrics"]["win_rate"] == 0.75


def test_ve32_get_state_returns_copy():
    store = ValidationStateStore()
    metrics = {"win_rate": 0.75}
    store.update(ValidationState.HEALTHY, metrics)
    snap1 = store.get_state()
    snap2 = store.get_state()
    assert snap1 is not snap2
    snap1["last_metrics"]["win_rate"] = 999.0
    # Original store should not be mutated
    assert store.get_state()["last_metrics"]["win_rate"] == 0.75


def test_ve33_last_update_time_advances():
    store = ValidationStateStore()
    t1 = store.last_update_time
    time.sleep(0.01)
    store.update(ValidationState.HEALTHY, {})
    assert store.last_update_time > t1
