from __future__ import annotations

from dataclasses import replace

from projects.polymarket.polyquantbot.platform.execution.monitoring_circuit_breaker import (
    ANOMALY_EXPOSURE_THRESHOLD_BREACH,
    ANOMALY_INVALID_CONTRACT_INPUT,
    ANOMALY_KILL_SWITCH_TRIGGERED,
    ANOMALY_MONITORING_DISABLED,
    MONITORING_ANOMALY_PRECEDENCE,
    MONITORING_ANOMALY_TAXONOMY,
    MONITORING_DECISION_ALLOW,
    MONITORING_DECISION_BLOCK,
    MONITORING_DECISION_HALT,
    MONITORING_MAX_EXPOSURE_RATIO,
    MonitoringCircuitBreaker,
    MonitoringContractInput,
)


def _valid_contract_input() -> MonitoringContractInput:
    return MonitoringContractInput(
        policy_ref="phase6_4_1_policy",
        eval_ref="phase6_4_1_eval",
        timestamp_ms=1713350400000,
        exposure_ratio=MONITORING_MAX_EXPOSURE_RATIO,
        position_notional_usd=100.0,
        total_capital_usd=1_000.0,
        data_freshness_ms=100,
        quality_score=0.95,
        signal_dedup_ok=True,
        kill_switch_armed=True,
        kill_switch_triggered=False,
        monitoring_enabled=True,
        quality_guard_enabled=True,
        exposure_guard_enabled=True,
        max_exposure_ratio=MONITORING_MAX_EXPOSURE_RATIO,
        max_data_freshness_ms=500,
        min_quality_score=0.80,
        trace_refs={"phase": "6.4.1"},
    )


def test_phase6_4_1_foundation_contract_exposure_ratio_boundary_is_deterministic() -> None:
    breaker = MonitoringCircuitBreaker()

    compliant = breaker.evaluate(_valid_contract_input())
    breach = breaker.evaluate(replace(_valid_contract_input(), exposure_ratio=0.11))

    assert compliant.decision == MONITORING_DECISION_ALLOW
    assert compliant.primary_anomaly is None
    assert breach.decision == MONITORING_DECISION_BLOCK
    assert breach.primary_anomaly == ANOMALY_EXPOSURE_THRESHOLD_BREACH


def test_phase6_4_1_foundation_contract_anomaly_taxonomy_is_fixed_and_complete() -> None:
    assert MONITORING_ANOMALY_TAXONOMY == (
        ANOMALY_INVALID_CONTRACT_INPUT,
        ANOMALY_EXPOSURE_THRESHOLD_BREACH,
        "EXPOSURE_INPUT_INCONSISTENT",
        "DATA_STALENESS_BREACH",
        "QUALITY_SCORE_BREACH",
        "SIGNAL_DEDUP_FAILURE",
        ANOMALY_KILL_SWITCH_TRIGGERED,
        ANOMALY_MONITORING_DISABLED,
    )


def test_phase6_4_1_foundation_contract_precedence_is_deterministic() -> None:
    breaker = MonitoringCircuitBreaker()

    result = breaker.evaluate(
        replace(
            _valid_contract_input(),
            monitoring_enabled=False,
            kill_switch_triggered=True,
            quality_score=float("nan"),
        )
    )

    assert MONITORING_ANOMALY_PRECEDENCE[0] == ANOMALY_INVALID_CONTRACT_INPUT
    assert result.decision == MONITORING_DECISION_HALT
    assert result.primary_anomaly == ANOMALY_INVALID_CONTRACT_INPUT
    assert result.anomalies[:3] == (
        ANOMALY_INVALID_CONTRACT_INPUT,
        ANOMALY_MONITORING_DISABLED,
        ANOMALY_KILL_SWITCH_TRIGGERED,
    )


def test_phase6_4_1_foundation_contract_max_exposure_constant_is_enforced() -> None:
    breaker = MonitoringCircuitBreaker()

    result = breaker.evaluate(replace(_valid_contract_input(), max_exposure_ratio=0.11))

    assert result.decision == MONITORING_DECISION_HALT
    assert result.primary_anomaly == ANOMALY_INVALID_CONTRACT_INPUT
