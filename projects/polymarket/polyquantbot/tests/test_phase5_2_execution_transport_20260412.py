from __future__ import annotations

from dataclasses import replace

from projects.polymarket.polyquantbot.platform.execution.execution_gateway import ExecutionGatewayResult
from projects.polymarket.polyquantbot.platform.execution.execution_mode_controller import (
    MODE_LIVE,
    MODE_SIMULATION,
)
from projects.polymarket.polyquantbot.platform.execution.execution_transport import (
    EXECUTION_TRANSPORT_BLOCK_AUDIT_LOG_MISSING,
    EXECUTION_TRANSPORT_BLOCK_AUTHORIZATION_REQUIRED,
    EXECUTION_TRANSPORT_BLOCK_DRY_RUN_FORCED,
    EXECUTION_TRANSPORT_BLOCK_IDEMPOTENCY_REQUIRED,
    EXECUTION_TRANSPORT_BLOCK_INVALID_AUTHORIZATION_INPUT_CONTRACT,
    EXECUTION_TRANSPORT_BLOCK_INVALID_EXECUTION_MODE,
    EXECUTION_TRANSPORT_BLOCK_INVALID_POLICY_INPUT_CONTRACT,
    EXECUTION_TRANSPORT_BLOCK_MULTIPLE_ORDERS_NOT_ALLOWED,
    EXECUTION_TRANSPORT_BLOCK_OPERATOR_CONFIRMATION_MISSING,
    EXECUTION_TRANSPORT_BLOCK_REAL_SUBMISSION_NOT_ALLOWED,
    EXECUTION_TRANSPORT_BLOCK_TRANSPORT_DISABLED,
    EXECUTION_TRANSPORT_MODE_REAL,
    EXECUTION_TRANSPORT_MODE_SIMULATED,
    ExecutionTransport,
    ExecutionTransportAuthorizationInput,
    ExecutionTransportPolicyInput,
)
from projects.polymarket.polyquantbot.platform.execution.live_execution_authorizer import (
    LiveExecutionAuthorizationDecision,
)

VALID_AUTHORIZATION_DECISION = LiveExecutionAuthorizationDecision(
    execution_authorized=True,
    allowed=True,
    blocked_reason=None,
    selected_mode=MODE_LIVE,
    authorization_scope="single_market_first_path",
    kill_switch_armed=True,
    audit_required=True,
    audit_attached=True,
    simulated=False,
    non_executing=False,
)

VALID_GATEWAY_RESULT = ExecutionGatewayResult(
    accepted=True,
    blocked_reason=None,
    execution_status="SIMULATED_EXECUTION_ACCEPTED",
    request_built=True,
    response_status="SIMULATED_ACCEPTED",
    client_order_id="CID-5-2-001",
    simulated=True,
    non_executing=True,
)

VALID_AUTHORIZATION_INPUT = ExecutionTransportAuthorizationInput(
    authorization=VALID_AUTHORIZATION_DECISION,
    gateway_result=VALID_GATEWAY_RESULT,
    source_trace_refs={"phase": "5.2"},
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
    policy_trace_refs={"policy": "5.2"},
)


def test_phase5_2_real_submission_allowed_under_strict_live_policy() -> None:
    transport = ExecutionTransport()

    result = transport.submit_with_trace(
        authorization_input=VALID_AUTHORIZATION_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.result is not None
    assert result.result.submitted is True
    assert result.result.success is True
    assert result.result.blocked_reason is None
    assert result.result.execution_authorized is True
    assert result.result.transport_mode == EXECUTION_TRANSPORT_MODE_REAL
    assert result.result.simulated is False
    assert result.result.non_executing is False


def test_phase5_2_dry_run_force_true_routes_to_simulated_only() -> None:
    transport = ExecutionTransport()

    result = transport.submit_with_trace(
        authorization_input=VALID_AUTHORIZATION_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, dry_run_force=True),
    )

    assert result.result is not None
    assert result.result.submitted is True
    assert result.result.success is True
    assert result.result.blocked_reason == EXECUTION_TRANSPORT_BLOCK_DRY_RUN_FORCED
    assert result.result.transport_mode == EXECUTION_TRANSPORT_MODE_SIMULATED
    assert result.result.simulated is True
    assert result.result.non_executing is True


def test_phase5_2_transport_disabled_is_blocked() -> None:
    transport = ExecutionTransport()

    result = transport.submit_with_trace(
        authorization_input=VALID_AUTHORIZATION_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, transport_enabled=False),
    )

    assert result.result is not None
    assert result.result.blocked_reason == EXECUTION_TRANSPORT_BLOCK_TRANSPORT_DISABLED


def test_phase5_2_authorization_missing_is_blocked() -> None:
    transport = ExecutionTransport()

    result = transport.submit_with_trace(
        authorization_input=replace(
            VALID_AUTHORIZATION_INPUT,
            authorization=replace(VALID_AUTHORIZATION_DECISION, execution_authorized=False),
        ),
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.result is not None
    assert result.result.blocked_reason == EXECUTION_TRANSPORT_BLOCK_AUTHORIZATION_REQUIRED


def test_phase5_2_invalid_execution_mode_is_blocked() -> None:
    transport = ExecutionTransport()

    result = transport.submit_with_trace(
        authorization_input=VALID_AUTHORIZATION_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, execution_mode=MODE_SIMULATION),
    )

    assert result.result is not None
    assert result.result.blocked_reason == EXECUTION_TRANSPORT_BLOCK_INVALID_EXECUTION_MODE


def test_phase5_2_allow_real_submission_false_is_blocked() -> None:
    transport = ExecutionTransport()

    result = transport.submit_with_trace(
        authorization_input=VALID_AUTHORIZATION_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, allow_real_submission=False),
    )

    assert result.result is not None
    assert result.result.blocked_reason == EXECUTION_TRANSPORT_BLOCK_REAL_SUBMISSION_NOT_ALLOWED


def test_phase5_2_multiple_orders_attempt_is_blocked() -> None:
    transport = ExecutionTransport()

    result = transport.submit_with_trace(
        authorization_input=VALID_AUTHORIZATION_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, max_orders=2),
    )

    assert result.result is not None
    assert result.result.blocked_reason == EXECUTION_TRANSPORT_BLOCK_MULTIPLE_ORDERS_NOT_ALLOWED


def test_phase5_2_idempotency_missing_is_blocked() -> None:
    transport = ExecutionTransport()

    result = transport.submit_with_trace(
        authorization_input=VALID_AUTHORIZATION_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, idempotency_key_present=False),
    )

    assert result.result is not None
    assert result.result.blocked_reason == EXECUTION_TRANSPORT_BLOCK_IDEMPOTENCY_REQUIRED


def test_phase5_2_audit_log_missing_is_blocked() -> None:
    transport = ExecutionTransport()

    result = transport.submit_with_trace(
        authorization_input=VALID_AUTHORIZATION_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, audit_log_attached=False),
    )

    assert result.result is not None
    assert result.result.blocked_reason == EXECUTION_TRANSPORT_BLOCK_AUDIT_LOG_MISSING


def test_phase5_2_operator_confirmation_missing_is_blocked() -> None:
    transport = ExecutionTransport()

    result = transport.submit_with_trace(
        authorization_input=VALID_AUTHORIZATION_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, operator_confirm_present=False),
    )

    assert result.result is not None
    assert result.result.blocked_reason == EXECUTION_TRANSPORT_BLOCK_OPERATOR_CONFIRMATION_MISSING


def test_phase5_2_deterministic_equality_same_inputs_same_result() -> None:
    transport = ExecutionTransport()

    first = transport.submit_with_trace(
        authorization_input=VALID_AUTHORIZATION_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )
    second = transport.submit_with_trace(
        authorization_input=VALID_AUTHORIZATION_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )

    assert first == second


def test_phase5_2_simulated_vs_real_behavior_fields() -> None:
    transport = ExecutionTransport()

    real_result = transport.submit_with_trace(
        authorization_input=VALID_AUTHORIZATION_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )
    simulated_result = transport.submit_with_trace(
        authorization_input=VALID_AUTHORIZATION_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, dry_run_force=True),
    )

    assert real_result.result is not None
    assert simulated_result.result is not None
    assert real_result.result.transport_mode == EXECUTION_TRANSPORT_MODE_REAL
    assert simulated_result.result.transport_mode == EXECUTION_TRANSPORT_MODE_SIMULATED
    assert real_result.result.non_executing is False
    assert simulated_result.result.non_executing is True


def test_phase5_2_invalid_inputs_do_not_crash() -> None:
    transport = ExecutionTransport()

    invalid_auth = transport.submit_with_trace(
        authorization_input=None,  # type: ignore[arg-type]
        policy_input=VALID_POLICY_INPUT,
    )
    invalid_policy = transport.submit_with_trace(
        authorization_input=VALID_AUTHORIZATION_INPUT,
        policy_input=None,  # type: ignore[arg-type]
    )

    assert invalid_auth.result is not None
    assert invalid_auth.result.blocked_reason == EXECUTION_TRANSPORT_BLOCK_INVALID_AUTHORIZATION_INPUT_CONTRACT
    assert invalid_policy.result is not None
    assert invalid_policy.result.blocked_reason == EXECUTION_TRANSPORT_BLOCK_INVALID_POLICY_INPUT_CONTRACT
