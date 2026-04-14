from __future__ import annotations

from dataclasses import replace

from projects.polymarket.polyquantbot.platform.execution.exchange_integration import (
    EXCHANGE_EXECUTION_BLOCK_MONITORING_ANOMALY,
    EXCHANGE_EXECUTION_HALT_MONITORING_ANOMALY,
    ExchangeExecutionPolicyInput,
    ExchangeExecutionTransportInput,
    ExchangeIntegration,
)
from projects.polymarket.polyquantbot.platform.execution.execution_decision import ExecutionDecision
from projects.polymarket.polyquantbot.platform.execution.execution_gateway import (
    ExecutionGateway,
    ExecutionGatewayDecisionInput,
)
from projects.polymarket.polyquantbot.platform.execution.execution_mode_controller import MODE_LIVE
from projects.polymarket.polyquantbot.platform.execution.execution_transport import (
    ExecutionTransport,
    ExecutionTransportAuthorizationInput,
    ExecutionTransportPolicyInput,
    ExecutionTransportResult,
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


VALID_MONITORING_INPUT = MonitoringContractInput(
    policy_ref="phase6_4_5_policy",
    eval_ref="phase6_4_5_eval",
    timestamp_ms=1713205000000,
    exposure_ratio=0.10,
    position_notional_usd=100.0,
    total_capital_usd=1_000.0,
    data_freshness_ms=120,
    quality_score=0.93,
    signal_dedup_ok=True,
    kill_switch_armed=True,
    kill_switch_triggered=False,
    monitoring_enabled=True,
    quality_guard_enabled=True,
    exposure_guard_enabled=True,
    max_exposure_ratio=0.10,
    max_data_freshness_ms=500,
    min_quality_score=0.80,
    trace_refs={"target_path": "exchange_integration.execute_with_trace"},
)

VALID_TRANSPORT_RESULT = ExecutionTransportResult(
    submitted=True,
    success=True,
    blocked_reason=None,
    execution_authorized=True,
    request_payload={"client_order_id": "CID-6-4-5-001", "side": "BUY", "size": 10},
    exchange_response={"transport": "ok"},
    transport_mode="REAL",
    simulated=False,
    non_executing=False,
)

VALID_TRANSPORT_INPUT = ExchangeExecutionTransportInput(
    transport_result=VALID_TRANSPORT_RESULT,
    monitoring_input=VALID_MONITORING_INPUT,
    monitoring_circuit_breaker=MonitoringCircuitBreaker(),
    monitoring_required=True,
    upstream_trace_refs={"phase": "6.4.5"},
)

VALID_POLICY_INPUT = ExchangeExecutionPolicyInput(
    network_enabled=True,
    allow_real_network=True,
    endpoint_url="https://api.exchange.local/orders",
    http_method="POST",
    signing_required=True,
    signing_key_present=True,
    signing_scheme="ed25519",
    wallet_reference="wallet-ref-001",
    request_timeout_ms=500,
    allow_testnet=False,
    environment="prod",
    allowed_environments=["prod", "staging"],
    policy_trace_refs={"policy": "phase6.4.5"},
)


def test_phase6_4_5_exchange_monitoring_allow_pass_through() -> None:
    integration = ExchangeIntegration(real_network_enabled=False)

    build = integration.execute_with_trace(
        transport_input=VALID_TRANSPORT_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )

    assert build.result is not None
    assert build.result.executed is True
    assert build.result.success is True
    assert build.result.blocked_reason is None
    assert build.trace.execution_attempted is True
    assert build.trace.upstream_trace_refs["monitoring"]["decision"] == "ALLOW"


def test_phase6_4_5_exchange_monitoring_block_prevents_execution() -> None:
    integration = ExchangeIntegration(real_network_enabled=False)
    breaker = MonitoringCircuitBreaker()

    build = integration.execute_with_trace(
        transport_input=replace(
            VALID_TRANSPORT_INPUT,
            monitoring_input=replace(VALID_MONITORING_INPUT, exposure_ratio=0.11),
            monitoring_circuit_breaker=breaker,
        ),
        policy_input=VALID_POLICY_INPUT,
    )

    assert build.result is not None
    assert build.result.executed is False
    assert build.result.blocked_reason == EXCHANGE_EXECUTION_BLOCK_MONITORING_ANOMALY
    assert build.trace.execution_attempted is False
    assert build.trace.upstream_trace_refs["monitoring"]["primary_anomaly"] == ANOMALY_EXPOSURE_THRESHOLD_BREACH
    assert len(breaker.get_events()) == 1


def test_phase6_4_5_exchange_monitoring_halt_stops_execution() -> None:
    integration = ExchangeIntegration(real_network_enabled=False)
    breaker = MonitoringCircuitBreaker()

    build = integration.execute_with_trace(
        transport_input=replace(
            VALID_TRANSPORT_INPUT,
            monitoring_input=replace(VALID_MONITORING_INPUT, kill_switch_triggered=True),
            monitoring_circuit_breaker=breaker,
        ),
        policy_input=VALID_POLICY_INPUT,
    )

    assert build.result is not None
    assert build.result.executed is False
    assert build.result.blocked_reason == EXCHANGE_EXECUTION_HALT_MONITORING_ANOMALY
    assert build.trace.execution_attempted is False
    assert build.trace.upstream_trace_refs["monitoring"]["primary_anomaly"] == ANOMALY_KILL_SWITCH_TRIGGERED
    assert len(breaker.get_events()) == 1


def test_phase6_4_5_existing_three_monitored_paths_remain_intact() -> None:
    authorizer = LiveExecutionAuthorizer()
    gateway = ExecutionGateway()
    transport = ExecutionTransport()

    auth_build = authorizer.authorize_with_trace(
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
            target_market_id="market-6-4-5",
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
    assert auth_build.decision is not None
    assert auth_build.decision.execution_authorized is True

    gateway_build = gateway.simulate_execution_with_trace(
        decision_input=ExecutionGatewayDecisionInput(
            decision=ExecutionDecision(
                allowed=True,
                blocked_reason=None,
                market_id="MKT-6-4-5",
                outcome="YES",
                side="YES",
                size=5.0,
                routing_mode="platform-gateway-shadow",
                execution_mode="paper-prep-only",
                ready_for_execution=True,
                non_activating=True,
            ),
            monitoring_input=VALID_MONITORING_INPUT,
            monitoring_circuit_breaker=MonitoringCircuitBreaker(),
            monitoring_required=True,
            source_trace_refs={"phase": "6.4.4"},
        )
    )
    assert gateway_build.result is not None
    assert gateway_build.result.accepted is True

    transport_build = transport.submit_with_trace(
        authorization_input=ExecutionTransportAuthorizationInput(
            authorization=auth_build.decision,
            gateway_result=gateway_build.result,
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
    assert transport_build.result is not None
    assert transport_build.result.submitted is True
    assert transport_build.result.success is True
