from __future__ import annotations

from dataclasses import replace

from projects.polymarket.polyquantbot.platform.execution.execution_decision import ExecutionDecision
from projects.polymarket.polyquantbot.platform.execution.execution_gateway import (
    GATEWAY_BLOCK_MONITORING_ANOMALY,
    GATEWAY_EXECUTION_STATUS_ACCEPTED,
    GATEWAY_HALT_MONITORING_ANOMALY,
    ExecutionGateway,
    ExecutionGatewayDecisionInput,
)
from projects.polymarket.polyquantbot.platform.execution.execution_mode_controller import MODE_LIVE
from projects.polymarket.polyquantbot.platform.execution.execution_transport import (
    ExecutionTransport,
    ExecutionTransportAuthorizationInput,
    ExecutionTransportPolicyInput,
)
from projects.polymarket.polyquantbot.platform.execution.live_execution_authorizer import (
    LiveExecutionAuthorizationPolicyInput,
    LiveExecutionAuthorizer,
    LiveExecutionReadinessInput,
)
from projects.polymarket.polyquantbot.platform.execution.live_execution_guardrails import LiveExecutionReadinessDecision
from projects.polymarket.polyquantbot.platform.execution.monitoring_circuit_breaker import (
    ANOMALY_EXPOSURE_THRESHOLD_BREACH,
    ANOMALY_KILL_SWITCH_TRIGGERED,
    MonitoringCircuitBreaker,
    MonitoringContractInput,
)


VALID_DECISION = ExecutionDecision(
    allowed=True,
    blocked_reason=None,
    market_id="MKT-6-4-4",
    outcome="YES",
    side="YES",
    size=9.5,
    routing_mode="platform-gateway-shadow",
    execution_mode="paper-prep-only",
    ready_for_execution=True,
    non_activating=True,
)

VALID_MONITORING_INPUT = MonitoringContractInput(
    policy_ref="phase6_4_4_policy",
    eval_ref="phase6_4_4_eval",
    timestamp_ms=1713200000000,
    exposure_ratio=0.10,
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
    max_exposure_ratio=0.10,
    max_data_freshness_ms=500,
    min_quality_score=0.80,
    trace_refs={"target_path": "execution_gateway.simulate_execution_with_trace"},
)

VALID_GATEWAY_INPUT = ExecutionGatewayDecisionInput(
    decision=VALID_DECISION,
    monitoring_input=VALID_MONITORING_INPUT,
    monitoring_circuit_breaker=MonitoringCircuitBreaker(),
    monitoring_required=True,
    source_trace_refs={"phase": "6.4.4"},
)


def test_phase6_4_4_gateway_monitoring_allow_pass_through() -> None:
    gateway = ExecutionGateway()

    result = gateway.simulate_execution_with_trace(decision_input=VALID_GATEWAY_INPUT)

    assert result.result is not None
    assert result.result.accepted is True
    assert result.result.blocked_reason is None
    assert result.result.execution_status == GATEWAY_EXECUTION_STATUS_ACCEPTED
    assert result.trace.gateway_completed is True
    assert result.trace.upstream_trace_refs["monitoring"]["decision"] == "ALLOW"


def test_phase6_4_4_gateway_monitoring_block_prevents_execution() -> None:
    gateway = ExecutionGateway()
    breaker = MonitoringCircuitBreaker()

    result = gateway.simulate_execution_with_trace(
        decision_input=replace(
            VALID_GATEWAY_INPUT,
            monitoring_input=replace(VALID_MONITORING_INPUT, exposure_ratio=0.11),
            monitoring_circuit_breaker=breaker,
        )
    )

    assert result.result is not None
    assert result.result.accepted is False
    assert result.result.blocked_reason == GATEWAY_BLOCK_MONITORING_ANOMALY
    assert result.trace.gateway_completed is False
    assert result.trace.gateway_notes is not None
    assert result.trace.gateway_notes["primary_anomaly"] == ANOMALY_EXPOSURE_THRESHOLD_BREACH
    assert len(breaker.get_events()) == 1


def test_phase6_4_4_gateway_monitoring_halt_stops_execution() -> None:
    gateway = ExecutionGateway()
    breaker = MonitoringCircuitBreaker()

    result = gateway.simulate_execution_with_trace(
        decision_input=replace(
            VALID_GATEWAY_INPUT,
            monitoring_input=replace(VALID_MONITORING_INPUT, kill_switch_triggered=True),
            monitoring_circuit_breaker=breaker,
        )
    )

    assert result.result is not None
    assert result.result.accepted is False
    assert result.result.blocked_reason == GATEWAY_HALT_MONITORING_ANOMALY
    assert result.trace.gateway_completed is False
    assert result.trace.gateway_notes is not None
    assert result.trace.gateway_notes["primary_anomaly"] == ANOMALY_KILL_SWITCH_TRIGGERED
    assert len(breaker.get_events()) == 1


def test_phase6_4_4_existing_two_monitored_paths_remain_intact() -> None:
    authorizer = LiveExecutionAuthorizer()
    gateway = ExecutionGateway()

    readiness_result = authorizer.authorize_with_trace(
        readiness_input=LiveExecutionReadinessInput(
            readiness_decision=LiveExecutionReadinessDecision(
                live_ready=True,
                allowed=True,
                blocked_reason=None,
                selected_mode=MODE_LIVE,
                guardrail_passed=True,
                kill_switch_armed=True,
                simulated=True,
                non_executing=True,
            ),
            monitoring_input=VALID_MONITORING_INPUT,
            monitoring_circuit_breaker=MonitoringCircuitBreaker(),
            source_trace_refs={"phase": "6.4.3"},
        ),
        policy_input=LiveExecutionAuthorizationPolicyInput(
            explicit_execution_enable=True,
            authorization_scope="single_market_first_path",
            allowed_scopes=("single_market_first_path",),
            single_market_only=True,
            target_market_id="market-6-4-4",
            wallet_binding_required=True,
            wallet_binding_present=True,
            audit_required=True,
            audit_attached=True,
            operator_approval_required=True,
            operator_approval_present=True,
            kill_switch_must_remain_armed=True,
            monitoring_required=True,
            policy_trace_refs={"phase": "6.4.3"},
        ),
    )

    assert readiness_result.decision is not None
    assert readiness_result.decision.execution_authorized is True

    transport = ExecutionTransport()
    gateway_build_result = gateway.simulate_execution_with_trace(decision_input=VALID_GATEWAY_INPUT)
    assert gateway_build_result.result is not None

    transport_result = transport.submit_with_trace(
        authorization_input=ExecutionTransportAuthorizationInput(
            authorization=readiness_result.decision,
            gateway_result=gateway_build_result.result,
            monitoring_input=VALID_MONITORING_INPUT,
            monitoring_circuit_breaker=MonitoringCircuitBreaker(),
            source_trace_refs={"phase": "6.4.2"},
        ),
        policy_input=ExecutionTransportPolicyInput(
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
            policy_trace_refs={"phase": "6.4.2"},
        ),
    )

    assert transport_result.result is not None
    assert transport_result.result.submitted is True
    assert transport_result.result.success is True
    assert transport_result.result.blocked_reason is None
