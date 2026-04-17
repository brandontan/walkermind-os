from __future__ import annotations

from dataclasses import replace

from projects.polymarket.polyquantbot.platform.execution.monitoring_circuit_breaker import (
    ANOMALY_EXPOSURE_THRESHOLD_BREACH,
    MONITORING_ANOMALY_PRECEDENCE,
    MONITORING_ANOMALY_TAXONOMY,
    MONITORING_MAX_EXPOSURE_RATIO,
    MonitoringCircuitBreaker,
    MonitoringContractInput,
)


BASE_INPUT = MonitoringContractInput(
    policy_ref="phase6_4_1_policy",
    eval_ref="phase6_4_1_eval",
    timestamp_ms=1713208200000,
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


def test_phase6_4_1_exports_foundation_contract_constants() -> None:
    assert MONITORING_MAX_EXPOSURE_RATIO == 0.10
    assert ANOMALY_EXPOSURE_THRESHOLD_BREACH in MONITORING_ANOMALY_TAXONOMY
    assert MONITORING_ANOMALY_PRECEDENCE[0] == "INVALID_CONTRACT_INPUT"


def test_phase6_4_1_max_exposure_boundary_allows_exact_10_percent() -> None:
    breaker = MonitoringCircuitBreaker()

    result = breaker.evaluate(contract_input=BASE_INPUT)

    assert result.decision == "ALLOW"
    assert result.primary_anomaly is None


def test_phase6_4_1_exposure_breach_blocks_above_boundary() -> None:
    breaker = MonitoringCircuitBreaker()

    result = breaker.evaluate(
        contract_input=replace(BASE_INPUT, exposure_ratio=MONITORING_MAX_EXPOSURE_RATIO + 0.01)
    )

    assert result.decision == "BLOCK"
    assert result.primary_anomaly == ANOMALY_EXPOSURE_THRESHOLD_BREACH


def test_phase6_4_1_validation_rejects_non_constant_max_exposure_ratio() -> None:
    breaker = MonitoringCircuitBreaker()

    result = breaker.evaluate(
        contract_input=replace(BASE_INPUT, max_exposure_ratio=0.09)
    )

    assert result.decision == "HALT"
    assert result.primary_anomaly == "INVALID_CONTRACT_INPUT"
