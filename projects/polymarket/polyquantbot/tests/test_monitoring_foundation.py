"""Phase 6.4.1 — Monitoring & Circuit Breaker Foundation Tests.

Validates the deterministic evaluation contract implemented in
monitoring/foundation.py against every scenario defined in the
Phase 6.4.1 spec (reports/forge/24_98_phase6_4_1_monitoring_circuit_breaker_foundation.md).

Scenarios:
  MCB-01  ALLOW on fully compliant clean input
  MCB-02  HALT on INVALID_CONTRACT_INPUT — empty policy_ref
  MCB-03  HALT on INVALID_CONTRACT_INPUT — empty eval_ref
  MCB-04  HALT on INVALID_CONTRACT_INPUT — timestamp_ms == 0
  MCB-04b HALT on INVALID_CONTRACT_INPUT — timestamp_ms < 0
  MCB-05  HALT on INVALID_CONTRACT_INPUT — max_exposure_ratio != 0.10
  MCB-06  HALT on INVALID_CONTRACT_INPUT — NaN exposure_ratio
  MCB-06b HALT on INVALID_CONTRACT_INPUT — Inf exposure_ratio
  MCB-07  HALT on INVALID_CONTRACT_INPUT — negative exposure_ratio
  MCB-08  BLOCK on MONITORING_DISABLED
  MCB-09  HALT on KILL_SWITCH_TRIGGERED (armed and triggered)
  MCB-10  BLOCK on EXPOSURE_THRESHOLD_BREACH (exposure_ratio > 0.10)
  MCB-11  ALLOW on exposure_ratio exactly at 0.10 boundary (inclusive)
  MCB-12  BLOCK on EXPOSURE_INPUT_INCONSISTENT — total_capital_usd == 0
  MCB-13  BLOCK on EXPOSURE_INPUT_INCONSISTENT — negative position_notional_usd
  MCB-14  BLOCK on DATA_STALENESS_BREACH
  MCB-15  BLOCK on QUALITY_SCORE_BREACH
  MCB-16  BLOCK on SIGNAL_DEDUP_FAILURE
  MCB-17  INVALID_CONTRACT_INPUT is sole anomaly when contract is invalid
  MCB-18  MONITORING_DISABLED primary over KILL_SWITCH_TRIGGERED (position 2 > 3)
  MCB-19  all_anomalies sorted by enum name
  MCB-20  kill_switch_armed=True, triggered=False -> no kill anomaly
  MCB-21  guards disabled -> no exposure/quality anomalies
  MCB-22  multiple quality breaches all captured in all_anomalies
  MCB-23  determinism — equal inputs produce equal outputs
  MCB-24  HALT on INVALID_CONTRACT_INPUT — negative data_freshness_ms
"""
from __future__ import annotations

import pytest

from projects.polymarket.polyquantbot.monitoring.foundation import (
    MonitoringAnomalyCategory,
    MonitoringContractInput,
    MonitoringDecision,
    MonitoringEvaluationResult,
    evaluate_monitoring_contract,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helper — build a fully compliant input with optional field overrides
# ─────────────────────────────────────────────────────────────────────────────

def _clean(**overrides) -> MonitoringContractInput:
    """Return a fully compliant MonitoringContractInput with optional overrides."""
    defaults: dict = dict(
        policy_ref="policy-v1",
        eval_ref="eval-001",
        timestamp_ms=1_700_000_000_000,
        exposure_ratio=0.05,
        position_notional_usd=500.0,
        total_capital_usd=10_000.0,
        data_freshness_ms=200,
        quality_score=0.90,
        signal_dedup_ok=True,
        kill_switch_armed=False,
        kill_switch_triggered=False,
        monitoring_enabled=True,
        quality_guard_enabled=True,
        exposure_guard_enabled=True,
        max_exposure_ratio=0.10,
        max_data_freshness_ms=5_000,
        min_quality_score=0.60,
    )
    defaults.update(overrides)
    return MonitoringContractInput(**defaults)


# ─────────────────────────────────────────────────────────────────────────────
# MCB-01  ALLOW on fully compliant clean input
# ─────────────────────────────────────────────────────────────────────────────

def test_mcb01_allow_clean_input():
    result = evaluate_monitoring_contract(_clean())
    assert result.decision == MonitoringDecision.ALLOW
    assert result.primary_anomaly is None
    assert result.all_anomalies == ()


# ─────────────────────────────────────────────────────────────────────────────
# MCB-02  HALT — empty policy_ref
# ─────────────────────────────────────────────────────────────────────────────

def test_mcb02_halt_empty_policy_ref():
    result = evaluate_monitoring_contract(_clean(policy_ref=""))
    assert result.decision == MonitoringDecision.HALT
    assert result.primary_anomaly == MonitoringAnomalyCategory.INVALID_CONTRACT_INPUT


# ─────────────────────────────────────────────────────────────────────────────
# MCB-03  HALT — empty eval_ref
# ─────────────────────────────────────────────────────────────────────────────

def test_mcb03_halt_empty_eval_ref():
    result = evaluate_monitoring_contract(_clean(eval_ref=""))
    assert result.decision == MonitoringDecision.HALT
    assert result.primary_anomaly == MonitoringAnomalyCategory.INVALID_CONTRACT_INPUT


# ─────────────────────────────────────────────────────────────────────────────
# MCB-04  HALT — timestamp_ms == 0
# ─────────────────────────────────────────────────────────────────────────────

def test_mcb04_halt_zero_timestamp():
    result = evaluate_monitoring_contract(_clean(timestamp_ms=0))
    assert result.decision == MonitoringDecision.HALT
    assert result.primary_anomaly == MonitoringAnomalyCategory.INVALID_CONTRACT_INPUT


def test_mcb04b_halt_negative_timestamp():
    result = evaluate_monitoring_contract(_clean(timestamp_ms=-1))
    assert result.decision == MonitoringDecision.HALT
    assert result.primary_anomaly == MonitoringAnomalyCategory.INVALID_CONTRACT_INPUT


# ─────────────────────────────────────────────────────────────────────────────
# MCB-05  HALT — max_exposure_ratio != 0.10 (risk-constant lock)
# ─────────────────────────────────────────────────────────────────────────────

def test_mcb05_halt_wrong_max_exposure_ratio():
    result = evaluate_monitoring_contract(_clean(max_exposure_ratio=0.15))
    assert result.decision == MonitoringDecision.HALT
    assert result.primary_anomaly == MonitoringAnomalyCategory.INVALID_CONTRACT_INPUT


# ─────────────────────────────────────────────────────────────────────────────
# MCB-06  HALT — non-finite exposure_ratio (NaN)
# ─────────────────────────────────────────────────────────────────────────────

def test_mcb06_halt_nan_exposure_ratio():
    result = evaluate_monitoring_contract(_clean(exposure_ratio=float("nan")))
    assert result.decision == MonitoringDecision.HALT
    assert result.primary_anomaly == MonitoringAnomalyCategory.INVALID_CONTRACT_INPUT


def test_mcb06b_halt_inf_exposure_ratio():
    result = evaluate_monitoring_contract(_clean(exposure_ratio=float("inf")))
    assert result.decision == MonitoringDecision.HALT
    assert result.primary_anomaly == MonitoringAnomalyCategory.INVALID_CONTRACT_INPUT


# ─────────────────────────────────────────────────────────────────────────────
# MCB-07  HALT — negative exposure_ratio
# ─────────────────────────────────────────────────────────────────────────────

def test_mcb07_halt_negative_exposure_ratio():
    result = evaluate_monitoring_contract(_clean(exposure_ratio=-0.01))
    assert result.decision == MonitoringDecision.HALT
    assert result.primary_anomaly == MonitoringAnomalyCategory.INVALID_CONTRACT_INPUT


# ─────────────────────────────────────────────────────────────────────────────
# MCB-08  BLOCK — monitoring_enabled=False
# ─────────────────────────────────────────────────────────────────────────────

def test_mcb08_block_monitoring_disabled():
    result = evaluate_monitoring_contract(_clean(monitoring_enabled=False))
    assert result.decision == MonitoringDecision.BLOCK
    assert result.primary_anomaly == MonitoringAnomalyCategory.MONITORING_DISABLED
    assert MonitoringAnomalyCategory.MONITORING_DISABLED in result.all_anomalies


# ─────────────────────────────────────────────────────────────────────────────
# MCB-09  HALT — kill_switch_armed=True AND kill_switch_triggered=True
# ─────────────────────────────────────────────────────────────────────────────

def test_mcb09_halt_kill_switch_triggered():
    result = evaluate_monitoring_contract(
        _clean(kill_switch_armed=True, kill_switch_triggered=True)
    )
    assert result.decision == MonitoringDecision.HALT
    assert result.primary_anomaly == MonitoringAnomalyCategory.KILL_SWITCH_TRIGGERED


# ─────────────────────────────────────────────────────────────────────────────
# MCB-10  BLOCK — exposure_ratio > 0.10
# ─────────────────────────────────────────────────────────────────────────────

def test_mcb10_block_exposure_threshold_breach():
    result = evaluate_monitoring_contract(_clean(exposure_ratio=0.11))
    assert result.decision == MonitoringDecision.BLOCK
    assert result.primary_anomaly == MonitoringAnomalyCategory.EXPOSURE_THRESHOLD_BREACH


# ─────────────────────────────────────────────────────────────────────────────
# MCB-11  ALLOW — exposure_ratio == 0.10 (exact boundary is allowed)
# ─────────────────────────────────────────────────────────────────────────────

def test_mcb11_allow_exposure_at_exact_boundary():
    result = evaluate_monitoring_contract(_clean(exposure_ratio=0.10))
    assert result.decision == MonitoringDecision.ALLOW
    assert result.primary_anomaly is None
    assert result.all_anomalies == ()


# ─────────────────────────────────────────────────────────────────────────────
# MCB-12  BLOCK — EXPOSURE_INPUT_INCONSISTENT: total_capital_usd == 0
# ─────────────────────────────────────────────────────────────────────────────

def test_mcb12_block_exposure_inconsistent_zero_capital():
    result = evaluate_monitoring_contract(
        _clean(total_capital_usd=0.0, exposure_guard_enabled=True)
    )
    assert result.decision == MonitoringDecision.BLOCK
    assert result.primary_anomaly == MonitoringAnomalyCategory.EXPOSURE_INPUT_INCONSISTENT


# ─────────────────────────────────────────────────────────────────────────────
# MCB-13  BLOCK — EXPOSURE_INPUT_INCONSISTENT: negative position_notional_usd
# ─────────────────────────────────────────────────────────────────────────────

def test_mcb13_block_exposure_inconsistent_negative_position():
    result = evaluate_monitoring_contract(
        _clean(position_notional_usd=-1.0, exposure_guard_enabled=True)
    )
    assert result.decision == MonitoringDecision.BLOCK
    assert result.primary_anomaly == MonitoringAnomalyCategory.EXPOSURE_INPUT_INCONSISTENT


# ─────────────────────────────────────────────────────────────────────────────
# MCB-14  BLOCK — data_freshness_ms > max_data_freshness_ms
# ─────────────────────────────────────────────────────────────────────────────

def test_mcb14_block_data_staleness_breach():
    result = evaluate_monitoring_contract(
        _clean(data_freshness_ms=6_000, max_data_freshness_ms=5_000)
    )
    assert result.decision == MonitoringDecision.BLOCK
    assert result.primary_anomaly == MonitoringAnomalyCategory.DATA_STALENESS_BREACH


# ─────────────────────────────────────────────────────────────────────────────
# MCB-15  BLOCK — quality_score < min_quality_score
# ─────────────────────────────────────────────────────────────────────────────

def test_mcb15_block_quality_score_breach():
    result = evaluate_monitoring_contract(
        _clean(quality_score=0.50, min_quality_score=0.60)
    )
    assert result.decision == MonitoringDecision.BLOCK
    assert result.primary_anomaly == MonitoringAnomalyCategory.QUALITY_SCORE_BREACH


# ─────────────────────────────────────────────────────────────────────────────
# MCB-16  BLOCK — signal_dedup_ok=False
# ─────────────────────────────────────────────────────────────────────────────

def test_mcb16_block_signal_dedup_failure():
    result = evaluate_monitoring_contract(_clean(signal_dedup_ok=False))
    assert result.decision == MonitoringDecision.BLOCK
    assert result.primary_anomaly == MonitoringAnomalyCategory.SIGNAL_DEDUP_FAILURE


# ─────────────────────────────────────────────────────────────────────────────
# MCB-17  INVALID_CONTRACT_INPUT is the sole anomaly when contract is invalid
#         (other guard conditions not evaluated — spec Section 6 determinism)
# ─────────────────────────────────────────────────────────────────────────────

def test_mcb17_invalid_contract_sole_anomaly():
    # empty policy_ref makes contract invalid; exposure breach would also fire
    # but MUST NOT appear because guard steps are skipped on invalid contract
    result = evaluate_monitoring_contract(
        _clean(policy_ref="", exposure_ratio=0.50)
    )
    assert result.decision == MonitoringDecision.HALT
    assert result.primary_anomaly == MonitoringAnomalyCategory.INVALID_CONTRACT_INPUT
    assert result.all_anomalies == (MonitoringAnomalyCategory.INVALID_CONTRACT_INPUT,)


# ─────────────────────────────────────────────────────────────────────────────
# MCB-18  MONITORING_DISABLED is primary over KILL_SWITCH_TRIGGERED
#         Spec Section 5 precedence: position 2 (MONITORING_DISABLED) beats
#         position 3 (KILL_SWITCH_TRIGGERED)
# ─────────────────────────────────────────────────────────────────────────────

def test_mcb18_monitoring_disabled_primary_over_kill_switch():
    result = evaluate_monitoring_contract(
        _clean(
            monitoring_enabled=False,
            kill_switch_armed=True,
            kill_switch_triggered=True,
        )
    )
    # MONITORING_DISABLED (pos 2) has higher precedence than KILL_SWITCH_TRIGGERED (pos 3)
    assert result.decision == MonitoringDecision.BLOCK
    assert result.primary_anomaly == MonitoringAnomalyCategory.MONITORING_DISABLED
    assert MonitoringAnomalyCategory.KILL_SWITCH_TRIGGERED in result.all_anomalies


# ─────────────────────────────────────────────────────────────────────────────
# MCB-19  all_anomalies sorted by enum name (stable output)
# ─────────────────────────────────────────────────────────────────────────────

def test_mcb19_all_anomalies_sorted_by_name():
    result = evaluate_monitoring_contract(
        _clean(
            data_freshness_ms=9_000,
            quality_score=0.10,
            signal_dedup_ok=False,
        )
    )
    names = [a.name for a in result.all_anomalies]
    assert names == sorted(names), "all_anomalies must be sorted by enum name"
    assert len(result.all_anomalies) == 3


# ─────────────────────────────────────────────────────────────────────────────
# MCB-20  kill_switch_armed=True, kill_switch_triggered=False -> no kill anomaly
# ─────────────────────────────────────────────────────────────────────────────

def test_mcb20_armed_not_triggered_no_kill_anomaly():
    result = evaluate_monitoring_contract(
        _clean(kill_switch_armed=True, kill_switch_triggered=False)
    )
    assert result.decision == MonitoringDecision.ALLOW
    assert MonitoringAnomalyCategory.KILL_SWITCH_TRIGGERED not in result.all_anomalies


# ─────────────────────────────────────────────────────────────────────────────
# MCB-21  exposure/quality guards disabled -> no anomalies from those paths
# ─────────────────────────────────────────────────────────────────────────────

def test_mcb21_guards_disabled_no_anomalies():
    result = evaluate_monitoring_contract(
        _clean(
            exposure_guard_enabled=False,
            quality_guard_enabled=False,
            exposure_ratio=0.99,    # would breach if guard enabled
            quality_score=0.0,      # would breach if guard enabled
            signal_dedup_ok=False,  # would breach if guard enabled
        )
    )
    assert result.decision == MonitoringDecision.ALLOW
    assert result.all_anomalies == ()


# ─────────────────────────────────────────────────────────────────────────────
# MCB-22  multiple quality breaches all appear in all_anomalies
# ─────────────────────────────────────────────────────────────────────────────

def test_mcb22_multiple_quality_breaches_all_captured():
    result = evaluate_monitoring_contract(
        _clean(
            data_freshness_ms=9_999,
            quality_score=0.01,
            signal_dedup_ok=False,
        )
    )
    assert MonitoringAnomalyCategory.DATA_STALENESS_BREACH in result.all_anomalies
    assert MonitoringAnomalyCategory.QUALITY_SCORE_BREACH in result.all_anomalies
    assert MonitoringAnomalyCategory.SIGNAL_DEDUP_FAILURE in result.all_anomalies
    assert len(result.all_anomalies) == 3


# ─────────────────────────────────────────────────────────────────────────────
# MCB-23  determinism — equal inputs always produce equal outputs
# ─────────────────────────────────────────────────────────────────────────────

def test_mcb23_determinism():
    inp = _clean(exposure_ratio=0.11)
    r1 = evaluate_monitoring_contract(inp)
    r2 = evaluate_monitoring_contract(inp)
    assert r1 == r2, "equal inputs must produce equal MonitoringEvaluationResult"


# ─────────────────────────────────────────────────────────────────────────────
# MCB-24  HALT — negative data_freshness_ms (invalid contract)
# ─────────────────────────────────────────────────────────────────────────────

def test_mcb24_halt_negative_data_freshness_ms():
    result = evaluate_monitoring_contract(_clean(data_freshness_ms=-1))
    assert result.decision == MonitoringDecision.HALT
    assert result.primary_anomaly == MonitoringAnomalyCategory.INVALID_CONTRACT_INPUT
