from __future__ import annotations

from dataclasses import replace

from projects.polymarket.polyquantbot.platform.execution.execution_gateway import ExecutionGatewayResult
from projects.polymarket.polyquantbot.platform.execution.execution_mode_controller import MODE_LIVE
from projects.polymarket.polyquantbot.platform.execution.execution_transport import (
    ExecutionTransport,
    ExecutionTransportAuthorizationInput,
    ExecutionTransportPolicyInput,
)
from projects.polymarket.polyquantbot.platform.execution.live_execution_authorizer import (
    LIVE_AUTH_BLOCK_MONITORING_ANOMALY,
    LIVE_AUTH_BLOCK_MONITORING_EVALUATION_REQUIRED,
    LIVE_AUTH_HALT_MONITORING_ANOMALY,
    LiveExecutionAuthorizationPolicyInput,
    LiveExecutionAuthorizer,
    LiveExecutionReadinessInput,
)
from projects.polymarket.polyquantbot.platform.execution.live_execution_guardrails import (
    LiveExecutionReadinessDecision,
)
from projects.polymarket.polyquantbot.platform.execution.monitoring_circuit_breaker import (
    ANOMALY_EXPOSURE_THRESHOLD_BREACH,
    ANOMALY_INVALID_CONTRACT_INPUT,
    ANOMALY_KILL_SWITCH_TRIGGERED,
    MonitoringCircuitBreaker,
    MonitoringContractInput,
)

VALID_READINESS_DECISION = LiveExecutionReadinessDecision(
    live_ready=True,
    allowed=True,
    blocked_reason=None,
    selected_mode=MODE_LIVE,
    guardrail_passed=True,
    kill_switch_armed=True,
    simulated=True,
    non_executing=True,
)

VALID_MONITORING_INPUT = MonitoringContractInput(
    policy_ref="phase6_4_3_policy",
    eval_ref="phase6_4_3_eval",
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
    trace_refs={"target_path": "live_execution_authorizer.authorize_with_trace"},
)

VALID_READINESS_INPUT = LiveExecutionReadinessInput(
    readiness_decision=VALID_READINESS_DECISION,
    monitoring_input=VALID_MONITORING_INPUT,
    monitoring_circuit_breaker=MonitoringCircuitBreaker(),
    source_trace_refs={"readiness_trace": "READINESS-6-4-3"},
)

VALID_POLICY_INPUT = LiveExecutionAuthorizationPolicyInput(
    explicit_execution_enable=True,
    authorization_scope="single_market_first_path",
    allowed_scopes=("single_market_first_path",),
    single_market_only=True,
    target_market_id="market-123",
    wallet_binding_required=True,
    wallet_binding_present=True,
    audit_required=True,
    audit_attached=True,
    operator_approval_required=True,
    operator_approval_present=True,
    kill_switch_must_remain_armed=True,
    monitoring_required=True,
    policy_trace_refs={"policy_trace": "POLICY-6-4-3"},
)


def test_phase6_4_3_invalid_monitoring_input_blocks_authorizer_path() -> None:
    authorizer = LiveExecutionAuthorizer()

    result = authorizer.authorize_with_trace(
        readiness_input=replace(VALID_READINESS_INPUT, monitoring_input=None),
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.decision is not None
    assert result.decision.allowed is False
    assert result.decision.blocked_reason == LIVE_AUTH_BLOCK_MONITORING_EVALUATION_REQUIRED


def test_phase6_4_3_invalid_monitoring_breaker_contract_blocks_authorizer_path() -> None:
    authorizer = LiveExecutionAuthorizer()

    result = authorizer.authorize_with_trace(
        readiness_input=replace(  # type: ignore[arg-type]
            VALID_READINESS_INPUT,
            monitoring_circuit_breaker="not-a-breaker",
        ),
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.decision is not None
    assert result.decision.allowed is False
    assert result.decision.blocked_reason == LIVE_AUTH_BLOCK_MONITORING_EVALUATION_REQUIRED
    assert result.trace.authorization_notes is not None
    assert result.trace.authorization_notes["contract_name"] == "monitoring_circuit_breaker"


def test_phase6_4_3_authorizer_monitoring_anomaly_blocks_execution_authorization() -> None:
    authorizer = LiveExecutionAuthorizer()
    breaker = MonitoringCircuitBreaker()

    result = authorizer.authorize_with_trace(
        readiness_input=replace(
            VALID_READINESS_INPUT,
            monitoring_input=replace(VALID_MONITORING_INPUT, exposure_ratio=0.11),
            monitoring_circuit_breaker=breaker,
        ),
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.decision is not None
    assert result.decision.execution_authorized is False
    assert result.decision.blocked_reason == LIVE_AUTH_BLOCK_MONITORING_ANOMALY
    assert result.trace.authorization_notes is not None
    assert result.trace.authorization_notes["primary_anomaly"] == ANOMALY_EXPOSURE_THRESHOLD_BREACH
    assert len(breaker.get_events()) == 1


def test_phase6_4_3_authorizer_kill_switch_anomaly_halts_authorization() -> None:
    authorizer = LiveExecutionAuthorizer()
    breaker = MonitoringCircuitBreaker()

    result = authorizer.authorize_with_trace(
        readiness_input=replace(
            VALID_READINESS_INPUT,
            monitoring_input=replace(VALID_MONITORING_INPUT, kill_switch_triggered=True),
            monitoring_circuit_breaker=breaker,
        ),
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.decision is not None
    assert result.decision.execution_authorized is False
    assert result.decision.blocked_reason == LIVE_AUTH_HALT_MONITORING_ANOMALY
    assert result.trace.authorization_notes is not None
    assert result.trace.authorization_notes["primary_anomaly"] == ANOMALY_KILL_SWITCH_TRIGGERED


def test_phase6_4_3_authorizer_invalid_contract_input_halts() -> None:
    authorizer = LiveExecutionAuthorizer()
    breaker = MonitoringCircuitBreaker()

    result = authorizer.authorize_with_trace(
        readiness_input=replace(
            VALID_READINESS_INPUT,
            monitoring_input=replace(VALID_MONITORING_INPUT, quality_score=float("nan")),
            monitoring_circuit_breaker=breaker,
        ),
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.decision is not None
    assert result.decision.execution_authorized is False
    assert result.decision.blocked_reason == LIVE_AUTH_HALT_MONITORING_ANOMALY
    assert result.trace.authorization_notes is not None
    assert result.trace.authorization_notes["primary_anomaly"] == ANOMALY_INVALID_CONTRACT_INPUT


def test_phase6_4_3_transport_path_regression_remains_intact() -> None:
    authorizer = LiveExecutionAuthorizer()
    decision_result = authorizer.authorize_with_trace(
        readiness_input=VALID_READINESS_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )

    assert decision_result.decision is not None
    assert decision_result.decision.execution_authorized is True

    gateway_result = ExecutionGatewayResult(
        accepted=True,
        blocked_reason=None,
        execution_status="SIMULATED_EXECUTION_ACCEPTED",
        request_built=True,
        response_status="SIMULATED_ACCEPTED",
        client_order_id="CID-6-4-3-001",
        simulated=True,
        non_executing=True,
    )
    transport = ExecutionTransport()

    submit_result = transport.submit_with_trace(
        authorization_input=ExecutionTransportAuthorizationInput(
            authorization=decision_result.decision,
            gateway_result=gateway_result,
            monitoring_input=VALID_MONITORING_INPUT,
            monitoring_circuit_breaker=MonitoringCircuitBreaker(),
            source_trace_refs={"phase": "6.4.3"},
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
            policy_trace_refs={"policy": "6.4.3"},
        ),
    )

    assert submit_result.result is not None
    assert submit_result.result.submitted is True
    assert submit_result.result.success is True
    assert submit_result.result.blocked_reason is None


def test_phase6_4_3_allow_path_propagates_monitoring_trace_refs() -> None:
    authorizer = LiveExecutionAuthorizer()
    result = authorizer.authorize_with_trace(
        readiness_input=replace(
            VALID_READINESS_INPUT,
            monitoring_circuit_breaker=MonitoringCircuitBreaker(),
        ),
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.decision is not None
    assert result.decision.execution_authorized is True
    assert result.trace.upstream_trace_refs["monitoring"]["decision"] == "ALLOW"
    assert result.trace.upstream_trace_refs["monitoring"]["primary_anomaly"] is None
