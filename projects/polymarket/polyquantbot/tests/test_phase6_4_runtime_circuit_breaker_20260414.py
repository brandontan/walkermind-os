from __future__ import annotations

from dataclasses import replace
import math

from projects.polymarket.polyquantbot.platform.execution.execution_gateway import ExecutionGatewayResult
from projects.polymarket.polyquantbot.platform.execution.execution_mode_controller import MODE_LIVE
from projects.polymarket.polyquantbot.platform.execution.execution_transport import (
    EXECUTION_TRANSPORT_BLOCK_MONITORING_ANOMALY,
    EXECUTION_TRANSPORT_HALT_MONITORING_ANOMALY,
    ExecutionTransport,
    ExecutionTransportAuthorizationInput,
    ExecutionTransportPolicyInput,
)
from projects.polymarket.polyquantbot.platform.execution.monitoring_circuit_breaker import (
    ANOMALY_EXPOSURE_THRESHOLD_BREACH,
    ANOMALY_INVALID_CONTRACT_INPUT,
    MONITORING_DECISION_HALT,
    MonitoringCircuitBreaker,
    MonitoringContractInput,
)
from projects.polymarket.polyquantbot.platform.execution.live_execution_authorizer import (
    LiveExecutionAuthorizationDecision,
)

VALID_AUTHORIZATION = LiveExecutionAuthorizationDecision(
    execution_authorized=True,
    allowed=True,
    blocked_reason=None,
    selected_mode=MODE_LIVE,
    authorization_scope="phase6_4_runtime_path",
    kill_switch_armed=True,
    audit_required=True,
    audit_attached=True,
    simulated=False,
    non_executing=False,
)

VALID_GATEWAY = ExecutionGatewayResult(
    accepted=True,
    blocked_reason=None,
    execution_status="SIMULATED_EXECUTION_ACCEPTED",
    request_built=True,
    response_status="SIMULATED_ACCEPTED",
    client_order_id="CID-6-4-001",
    simulated=True,
    non_executing=True,
)

VALID_MONITORING_INPUT = MonitoringContractInput(
    policy_ref="phase6_4_policy",
    eval_ref="phase6_4_eval",
    timestamp_ms=1713120000000,
    exposure_ratio=0.10,
    position_notional_usd=100.0,
    total_capital_usd=1_000.0,
    data_freshness_ms=150,
    quality_score=0.95,
    signal_dedup_ok=True,
    kill_switch_armed=True,
    kill_switch_triggered=False,
    monitoring_enabled=True,
    quality_guard_enabled=True,
    exposure_guard_enabled=True,
    max_exposure_ratio=0.10,
    max_data_freshness_ms=500,
    min_quality_score=0.80,
    trace_refs={"target_path": "execution_transport.submit_with_trace"},
)

VALID_AUTHORIZATION_INPUT = ExecutionTransportAuthorizationInput(
    authorization=VALID_AUTHORIZATION,
    gateway_result=VALID_GATEWAY,
    monitoring_input=VALID_MONITORING_INPUT,
    monitoring_circuit_breaker=MonitoringCircuitBreaker(),
    source_trace_refs={"phase": "6.4"},
)

VALID_POLICY_INPUT = ExecutionTransportPolicyInput(
    transport_enabled=True,
    execution_mode=MODE_LIVE,
    dry_run_force=False,
    allow_real_submission=True,
    single_submission_only=True,
    max_orders=1,
    require_idempotency=True,
    idempotency_key_present=True,
    audit_log_required=True,
    audit_log_attached=True,
    operator_confirm_required=True,
    operator_confirm_present=True,
    monitoring_required=True,
    policy_trace_refs={"policy": "6.4"},
)


def test_phase6_4_anomaly_precedence_invalid_input_overrides_monitoring_disabled() -> None:
    breaker = MonitoringCircuitBreaker()

    result = breaker.evaluate(
        replace(
            VALID_MONITORING_INPUT,
            monitoring_enabled=False,
            quality_score=math.nan,
        )
    )

    assert result.decision == MONITORING_DECISION_HALT
    assert result.primary_anomaly == ANOMALY_INVALID_CONTRACT_INPUT
    assert result.anomalies[0] == ANOMALY_INVALID_CONTRACT_INPUT


def test_phase6_4_exposure_breach_blocks_execution_transport_target_path() -> None:
    transport = ExecutionTransport()
    breaker = MonitoringCircuitBreaker()

    result = transport.submit_with_trace(
        authorization_input=replace(
            VALID_AUTHORIZATION_INPUT,
            monitoring_input=replace(VALID_MONITORING_INPUT, exposure_ratio=0.11),
            monitoring_circuit_breaker=breaker,
        ),
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.result is not None
    assert result.result.submitted is False
    assert result.result.blocked_reason == EXECUTION_TRANSPORT_BLOCK_MONITORING_ANOMALY
    assert result.trace.transport_attempted is False
    assert result.trace.transport_notes is not None
    assert result.trace.transport_notes["primary_anomaly"] == ANOMALY_EXPOSURE_THRESHOLD_BREACH
    assert len(breaker.get_events()) == 1


def test_phase6_4_kill_switch_anomaly_halts_execution_transport_target_path() -> None:
    transport = ExecutionTransport()
    breaker = MonitoringCircuitBreaker()

    result = transport.submit_with_trace(
        authorization_input=replace(
            VALID_AUTHORIZATION_INPUT,
            monitoring_input=replace(VALID_MONITORING_INPUT, kill_switch_triggered=True),
            monitoring_circuit_breaker=breaker,
        ),
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.result is not None
    assert result.result.submitted is False
    assert result.result.non_executing is True
    assert result.result.blocked_reason == EXECUTION_TRANSPORT_HALT_MONITORING_ANOMALY
    assert result.trace.transport_attempted is False
    assert len(breaker.get_events()) == 1
