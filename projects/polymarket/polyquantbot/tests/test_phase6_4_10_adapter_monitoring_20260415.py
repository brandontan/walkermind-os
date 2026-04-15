from __future__ import annotations

from dataclasses import replace

from projects.polymarket.polyquantbot.platform.execution.execution_adapter import (
    ADAPTER_BLOCK_MONITORING_ANOMALY,
    ADAPTER_HALT_MONITORING_ANOMALY,
    ExecutionAdapter,
    ExecutionAdapterDecisionInput,
)
from projects.polymarket.polyquantbot.platform.execution.execution_decision import ExecutionDecision
from projects.polymarket.polyquantbot.platform.execution.monitoring_circuit_breaker import (
    ANOMALY_EXPOSURE_THRESHOLD_BREACH,
    ANOMALY_KILL_SWITCH_TRIGGERED,
    MonitoringCircuitBreaker,
    MonitoringContractInput,
)

VALID_MONITORING_INPUT = MonitoringContractInput(
    policy_ref="phase6_4_10_policy",
    eval_ref="phase6_4_10_eval",
    timestamp_ms=1713208200000,
    exposure_ratio=0.10,
    position_notional_usd=100.0,
    total_capital_usd=1_000.0,
    data_freshness_ms=100,
    quality_score=0.94,
    signal_dedup_ok=True,
    kill_switch_armed=True,
    kill_switch_triggered=False,
    monitoring_enabled=True,
    quality_guard_enabled=True,
    exposure_guard_enabled=True,
    max_exposure_ratio=0.10,
    max_data_freshness_ms=500,
    min_quality_score=0.80,
    trace_refs={"target_path": "execution_adapter.build_order_with_trace"},
)

VALID_DECISION = ExecutionDecision(
    allowed=True,
    blocked_reason=None,
    market_id="MKT-6-4-10",
    outcome="YES",
    side="BUY",
    size=5.0,
    routing_mode="platform-gateway-shadow",
    execution_mode="paper-prep-only",
    ready_for_execution=True,
    non_activating=True,
)


def _decision_input() -> ExecutionAdapterDecisionInput:
    return ExecutionAdapterDecisionInput(
        decision=VALID_DECISION,
        monitoring_input=VALID_MONITORING_INPUT,
        monitoring_circuit_breaker=MonitoringCircuitBreaker(),
        monitoring_required=True,
        source_trace_refs={"phase": "6.4.10"},
    )


def test_phase6_4_10_adapter_monitoring_allow_builds_order() -> None:
    adapter = ExecutionAdapter()

    build = adapter.build_order_with_trace(decision_input=_decision_input())

    assert build.order is not None
    assert build.trace.order_created is True
    assert build.trace.blocked_reason is None
    assert build.trace.upstream_trace_refs["monitoring"]["decision"] == "ALLOW"


def test_phase6_4_10_adapter_monitoring_block_prevents_order_build() -> None:
    adapter = ExecutionAdapter()
    breaker = MonitoringCircuitBreaker()

    build = adapter.build_order_with_trace(
        decision_input=replace(
            _decision_input(),
            monitoring_input=replace(VALID_MONITORING_INPUT, exposure_ratio=0.11),
            monitoring_circuit_breaker=breaker,
        )
    )

    assert build.order is None
    assert build.trace.order_created is False
    assert build.trace.blocked_reason == ADAPTER_BLOCK_MONITORING_ANOMALY
    assert build.trace.upstream_trace_refs["monitoring"]["primary_anomaly"] == ANOMALY_EXPOSURE_THRESHOLD_BREACH
    assert len(breaker.get_events()) == 1


def test_phase6_4_10_adapter_monitoring_halt_prevents_order_build() -> None:
    adapter = ExecutionAdapter()
    breaker = MonitoringCircuitBreaker()

    build = adapter.build_order_with_trace(
        decision_input=replace(
            _decision_input(),
            monitoring_input=replace(VALID_MONITORING_INPUT, kill_switch_triggered=True),
            monitoring_circuit_breaker=breaker,
        )
    )

    assert build.order is None
    assert build.trace.order_created is False
    assert build.trace.blocked_reason == ADAPTER_HALT_MONITORING_ANOMALY
    assert build.trace.upstream_trace_refs["monitoring"]["primary_anomaly"] == ANOMALY_KILL_SWITCH_TRIGGERED
    assert len(breaker.get_events()) == 1
