from __future__ import annotations

from dataclasses import fields, replace

from projects.polymarket.polyquantbot.platform.execution.execution_mode_controller import (
    MODE_FUTURE_LIVE,
    MODE_LIVE,
    MODE_SIMULATION,
)
from projects.polymarket.polyquantbot.platform.execution.live_execution_authorizer import (
    LIVE_AUTH_BLOCK_AUDIT_ATTACHMENT_MISSING,
    LIVE_AUTH_BLOCK_AUTHORIZATION_SCOPE_NOT_ALLOWED,
    LIVE_AUTH_BLOCK_EXPLICIT_EXECUTION_ENABLE_REQUIRED,
    LIVE_AUTH_BLOCK_INVALID_POLICY_INPUT,
    LIVE_AUTH_BLOCK_INVALID_POLICY_INPUT_CONTRACT,
    LIVE_AUTH_BLOCK_INVALID_READINESS_DECISION,
    LIVE_AUTH_BLOCK_INVALID_READINESS_INPUT_CONTRACT,
    LIVE_AUTH_BLOCK_KILL_SWITCH_NOT_ARMED,
    LIVE_AUTH_BLOCK_LIVE_MODE_REQUIRED,
    LIVE_AUTH_BLOCK_LIVE_READINESS_REQUIRED,
    LIVE_AUTH_BLOCK_OPERATOR_APPROVAL_MISSING,
    LIVE_AUTH_BLOCK_TARGET_MARKET_REQUIRED,
    LIVE_AUTH_BLOCK_UPSTREAM_READINESS_NOT_ALLOWED,
    LIVE_AUTH_BLOCK_WALLET_BINDING_MISSING,
    LiveExecutionAuthorizationDecision,
    LiveExecutionAuthorizationPolicyInput,
    LiveExecutionAuthorizer,
    LiveExecutionReadinessInput,
)
from projects.polymarket.polyquantbot.platform.execution.live_execution_guardrails import (
    LiveExecutionReadinessDecision,
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

VALID_READINESS_INPUT = LiveExecutionReadinessInput(
    readiness_decision=VALID_READINESS_DECISION,
    source_trace_refs={"readiness_trace": "READINESS-5-1"},
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
    policy_trace_refs={"policy_trace": "POLICY-5-1"},
)


def test_phase5_1_live_mode_full_explicit_policy_satisfied_is_authorized_deterministically() -> None:
    authorizer = LiveExecutionAuthorizer()

    result = authorizer.authorize_with_trace(
        readiness_input=VALID_READINESS_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.decision is not None
    assert result.decision.execution_authorized is True
    assert result.decision.allowed is True
    assert result.decision.blocked_reason is None
    assert result.decision.selected_mode == MODE_LIVE
    assert result.decision.authorization_scope == "single_market_first_path"
    assert result.decision.kill_switch_armed is True
    assert result.decision.audit_required is True
    assert result.decision.audit_attached is True
    assert result.decision.simulated is False
    assert result.decision.non_executing is False


def test_phase5_1_future_live_mode_full_explicit_policy_satisfied_is_authorized_deterministically() -> None:
    authorizer = LiveExecutionAuthorizer()

    result = authorizer.authorize_with_trace(
        readiness_input=replace(
            VALID_READINESS_INPUT,
            readiness_decision=replace(VALID_READINESS_DECISION, selected_mode=MODE_FUTURE_LIVE),
        ),
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.decision is not None
    assert result.decision.execution_authorized is True
    assert result.decision.allowed is True
    assert result.decision.selected_mode == MODE_FUTURE_LIVE
    assert result.decision.simulated is False
    assert result.decision.non_executing is False


def test_phase5_1_invalid_top_level_readiness_input_blocked_deterministically() -> None:
    authorizer = LiveExecutionAuthorizer()

    result = authorizer.authorize_with_trace(
        readiness_input=None,  # type: ignore[arg-type]
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.decision is not None
    assert result.decision.allowed is False
    assert result.decision.blocked_reason == LIVE_AUTH_BLOCK_INVALID_READINESS_INPUT_CONTRACT


def test_phase5_1_invalid_top_level_policy_input_blocked_deterministically() -> None:
    authorizer = LiveExecutionAuthorizer()

    result = authorizer.authorize_with_trace(
        readiness_input=VALID_READINESS_INPUT,
        policy_input=None,  # type: ignore[arg-type]
    )

    assert result.decision is not None
    assert result.decision.allowed is False
    assert result.decision.blocked_reason == LIVE_AUTH_BLOCK_INVALID_POLICY_INPUT_CONTRACT


def test_phase5_1_invalid_readiness_decision_blocked_deterministically() -> None:
    authorizer = LiveExecutionAuthorizer()

    result = authorizer.authorize_with_trace(
        readiness_input=replace(
            VALID_READINESS_INPUT,
            readiness_decision=replace(VALID_READINESS_DECISION, selected_mode=""),
        ),
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.decision is not None
    assert result.decision.blocked_reason == LIVE_AUTH_BLOCK_INVALID_READINESS_DECISION


def test_phase5_1_invalid_policy_fields_blocked_deterministically() -> None:
    authorizer = LiveExecutionAuthorizer()

    result = authorizer.authorize_with_trace(
        readiness_input=VALID_READINESS_INPUT,
        policy_input=LiveExecutionAuthorizationPolicyInput(  # type: ignore[arg-type]
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
            policy_trace_refs="not-a-dict",  # type: ignore[arg-type]
        ),
    )

    assert result.decision is not None
    assert result.decision.blocked_reason == LIVE_AUTH_BLOCK_INVALID_POLICY_INPUT


def test_phase5_1_upstream_readiness_not_allowed_blocked_deterministically() -> None:
    authorizer = LiveExecutionAuthorizer()

    result = authorizer.authorize_with_trace(
        readiness_input=replace(
            VALID_READINESS_INPUT,
            readiness_decision=replace(
                VALID_READINESS_DECISION,
                allowed=False,
                blocked_reason="upstream_readiness_blocked",
            ),
        ),
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.decision is not None
    assert result.decision.blocked_reason == LIVE_AUTH_BLOCK_UPSTREAM_READINESS_NOT_ALLOWED


def test_phase5_1_live_ready_false_blocked_deterministically() -> None:
    authorizer = LiveExecutionAuthorizer()

    result = authorizer.authorize_with_trace(
        readiness_input=replace(
            VALID_READINESS_INPUT,
            readiness_decision=replace(VALID_READINESS_DECISION, live_ready=False),
        ),
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.decision is not None
    assert result.decision.blocked_reason == LIVE_AUTH_BLOCK_LIVE_READINESS_REQUIRED


def test_phase5_1_non_live_mode_blocked_deterministically() -> None:
    authorizer = LiveExecutionAuthorizer()

    result = authorizer.authorize_with_trace(
        readiness_input=replace(
            VALID_READINESS_INPUT,
            readiness_decision=replace(VALID_READINESS_DECISION, selected_mode=MODE_SIMULATION),
        ),
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.decision is not None
    assert result.decision.blocked_reason == LIVE_AUTH_BLOCK_LIVE_MODE_REQUIRED


def test_phase5_1_explicit_execution_enable_missing_blocked_deterministically() -> None:
    authorizer = LiveExecutionAuthorizer()

    result = authorizer.authorize_with_trace(
        readiness_input=VALID_READINESS_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, explicit_execution_enable=False),
    )

    assert result.decision is not None
    assert result.decision.blocked_reason == LIVE_AUTH_BLOCK_EXPLICIT_EXECUTION_ENABLE_REQUIRED


def test_phase5_1_authorization_scope_not_allow_listed_blocked_deterministically() -> None:
    authorizer = LiveExecutionAuthorizer()

    result = authorizer.authorize_with_trace(
        readiness_input=VALID_READINESS_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, authorization_scope="global_all_markets"),
    )

    assert result.decision is not None
    assert result.decision.blocked_reason == LIVE_AUTH_BLOCK_AUTHORIZATION_SCOPE_NOT_ALLOWED


def test_phase5_1_single_market_without_target_market_id_blocked_deterministically() -> None:
    authorizer = LiveExecutionAuthorizer()

    result = authorizer.authorize_with_trace(
        readiness_input=VALID_READINESS_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, target_market_id=None),
    )

    assert result.decision is not None
    assert result.decision.blocked_reason == LIVE_AUTH_BLOCK_TARGET_MARKET_REQUIRED


def test_phase5_1_wallet_binding_missing_when_required_blocked_deterministically() -> None:
    authorizer = LiveExecutionAuthorizer()

    result = authorizer.authorize_with_trace(
        readiness_input=VALID_READINESS_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, wallet_binding_present=False),
    )

    assert result.decision is not None
    assert result.decision.blocked_reason == LIVE_AUTH_BLOCK_WALLET_BINDING_MISSING


def test_phase5_1_audit_attachment_missing_when_required_blocked_deterministically() -> None:
    authorizer = LiveExecutionAuthorizer()

    result = authorizer.authorize_with_trace(
        readiness_input=VALID_READINESS_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, audit_attached=False),
    )

    assert result.decision is not None
    assert result.decision.blocked_reason == LIVE_AUTH_BLOCK_AUDIT_ATTACHMENT_MISSING


def test_phase5_1_operator_approval_missing_when_required_blocked_deterministically() -> None:
    authorizer = LiveExecutionAuthorizer()

    result = authorizer.authorize_with_trace(
        readiness_input=VALID_READINESS_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, operator_approval_present=False),
    )

    assert result.decision is not None
    assert result.decision.blocked_reason == LIVE_AUTH_BLOCK_OPERATOR_APPROVAL_MISSING


def test_phase5_1_kill_switch_not_armed_blocked_deterministically() -> None:
    authorizer = LiveExecutionAuthorizer()

    result = authorizer.authorize_with_trace(
        readiness_input=replace(
            VALID_READINESS_INPUT,
            readiness_decision=replace(VALID_READINESS_DECISION, kill_switch_armed=False),
        ),
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.decision is not None
    assert result.decision.blocked_reason == LIVE_AUTH_BLOCK_KILL_SWITCH_NOT_ARMED


def test_phase5_1_deterministic_equality_for_same_valid_input() -> None:
    authorizer = LiveExecutionAuthorizer()

    first = authorizer.authorize_with_trace(
        readiness_input=VALID_READINESS_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )
    second = authorizer.authorize_with_trace(
        readiness_input=VALID_READINESS_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )

    assert first == second


def test_phase5_1_allowed_path_returns_executing_flags_only_for_authorization_layer() -> None:
    authorizer = LiveExecutionAuthorizer()

    decision = authorizer.authorize(
        readiness_input=VALID_READINESS_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )

    assert decision is not None
    assert decision.simulated is False
    assert decision.non_executing is False


def test_phase5_1_no_network_api_signing_capital_fields_introduced() -> None:
    field_names = {item.name for item in fields(LiveExecutionAuthorizationDecision)}

    assert "api_key" not in field_names
    assert "private_key" not in field_names
    assert "wallet_secret" not in field_names
    assert "signature" not in field_names
    assert "network_client" not in field_names
    assert "capital_transfer" not in field_names


def test_phase5_1_none_dict_wrong_object_inputs_do_not_crash() -> None:
    authorizer = LiveExecutionAuthorizer()

    none_readiness = authorizer.authorize_with_trace(
        readiness_input=None,  # type: ignore[arg-type]
        policy_input=VALID_POLICY_INPUT,
    )
    assert none_readiness.decision is not None
    assert none_readiness.decision.blocked_reason == LIVE_AUTH_BLOCK_INVALID_READINESS_INPUT_CONTRACT

    dict_readiness = authorizer.authorize_with_trace(
        readiness_input={"readiness_decision": VALID_READINESS_DECISION},  # type: ignore[arg-type]
        policy_input=VALID_POLICY_INPUT,
    )
    assert dict_readiness.decision is not None
    assert dict_readiness.decision.blocked_reason == LIVE_AUTH_BLOCK_INVALID_READINESS_INPUT_CONTRACT

    wrong_policy = authorizer.authorize_with_trace(
        readiness_input=VALID_READINESS_INPUT,
        policy_input={"explicit_execution_enable": True},  # type: ignore[arg-type]
    )
    assert wrong_policy.decision is not None
    assert wrong_policy.decision.blocked_reason == LIVE_AUTH_BLOCK_INVALID_POLICY_INPUT_CONTRACT
