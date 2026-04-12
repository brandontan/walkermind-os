from __future__ import annotations

from dataclasses import fields, replace

from projects.polymarket.polyquantbot.platform.execution.execution_mode_controller import (
    MODE_FUTURE_LIVE,
    MODE_LIVE,
    MODE_SIMULATION,
    ExecutionModeDecision,
)
from projects.polymarket.polyquantbot.platform.execution.live_execution_guardrails import (
    LIVE_READINESS_BLOCK_AUDIT_HOOK_MISSING,
    LIVE_READINESS_BLOCK_ENVIRONMENT_NOT_ALLOWED,
    LIVE_READINESS_BLOCK_EXPLICIT_LIVE_REQUEST_REQUIRED,
    LIVE_READINESS_BLOCK_INVALID_MODE_DECISION,
    LIVE_READINESS_BLOCK_INVALID_MODE_INPUT_CONTRACT,
    LIVE_READINESS_BLOCK_INVALID_POLICY_INPUT,
    LIVE_READINESS_BLOCK_INVALID_POLICY_INPUT_CONTRACT,
    LIVE_READINESS_BLOCK_KILL_SWITCH_MISSING,
    LIVE_READINESS_BLOCK_KILL_SWITCH_NOT_ARMED,
    LIVE_READINESS_BLOCK_LIVE_FEATURE_FLAG_DISABLED,
    LIVE_READINESS_BLOCK_LIVE_FEATURE_FLAG_MISSING,
    LIVE_READINESS_BLOCK_LIVE_MODE_REQUIRED,
    LIVE_READINESS_BLOCK_NON_EXECUTING_REQUIRED,
    LIVE_READINESS_BLOCK_TWO_STEP_CONFIRMATION_MISSING,
    LIVE_READINESS_BLOCK_UPSTREAM_MODE_NOT_ALLOWED,
    LiveExecutionGuardrailPolicyInput,
    LiveExecutionGuardrails,
    LiveExecutionModeInput,
    LiveExecutionReadinessDecision,
)

VALID_MODE_DECISION = ExecutionModeDecision(
    selected_mode=MODE_LIVE,
    allowed=True,
    blocked_reason=None,
    gateway_accepted=True,
    live_capable=False,
    simulated=True,
    non_executing=True,
)

VALID_MODE_INPUT = LiveExecutionModeInput(
    mode_decision=VALID_MODE_DECISION,
    source_trace_refs={"mode_trace": "MODE-4-5"},
)

VALID_POLICY_INPUT = LiveExecutionGuardrailPolicyInput(
    explicit_live_request=True,
    live_feature_flag_present=True,
    live_feature_flag_enabled=True,
    kill_switch_present=True,
    kill_switch_armed=True,
    audit_hook_required=True,
    audit_hook_present=True,
    two_step_confirmation_required=True,
    two_step_confirmation_present=True,
    environment_name="staging-live-prep",
    allowed_live_environments=("staging-live-prep", "preprod-live-prep"),
    policy_trace_refs={"policy_trace": "POLICY-4-5"},
)


def test_phase4_5_live_mode_full_guardrails_satisfied_is_deterministic_readiness() -> None:
    controller = LiveExecutionGuardrails()

    result = controller.evaluate_readiness_with_trace(
        mode_input=VALID_MODE_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.decision is not None
    assert result.decision.live_ready is True
    assert result.decision.allowed is True
    assert result.decision.blocked_reason is None
    assert result.decision.selected_mode == MODE_LIVE
    assert result.decision.guardrail_passed is True
    assert result.decision.kill_switch_armed is True
    assert result.decision.simulated is True
    assert result.decision.non_executing is True


def test_phase4_5_future_live_mode_full_guardrails_satisfied_is_deterministic_readiness() -> None:
    controller = LiveExecutionGuardrails()

    result = controller.evaluate_readiness_with_trace(
        mode_input=replace(
            VALID_MODE_INPUT,
            mode_decision=replace(VALID_MODE_DECISION, selected_mode=MODE_FUTURE_LIVE),
        ),
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.decision is not None
    assert result.decision.live_ready is True
    assert result.decision.allowed is True
    assert result.decision.selected_mode == MODE_FUTURE_LIVE
    assert result.decision.simulated is True
    assert result.decision.non_executing is True


def test_phase4_5_invalid_top_level_mode_input_blocked_deterministically() -> None:
    controller = LiveExecutionGuardrails()

    result = controller.evaluate_readiness_with_trace(
        mode_input=None,  # type: ignore[arg-type]
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.decision is not None
    assert result.decision.allowed is False
    assert result.decision.blocked_reason == LIVE_READINESS_BLOCK_INVALID_MODE_INPUT_CONTRACT


def test_phase4_5_invalid_top_level_policy_input_blocked_deterministically() -> None:
    controller = LiveExecutionGuardrails()

    result = controller.evaluate_readiness_with_trace(
        mode_input=VALID_MODE_INPUT,
        policy_input=None,  # type: ignore[arg-type]
    )

    assert result.decision is not None
    assert result.decision.allowed is False
    assert result.decision.blocked_reason == LIVE_READINESS_BLOCK_INVALID_POLICY_INPUT_CONTRACT


def test_phase4_5_invalid_mode_decision_blocked_deterministically() -> None:
    controller = LiveExecutionGuardrails()

    result = controller.evaluate_readiness_with_trace(
        mode_input=replace(
            VALID_MODE_INPUT,
            mode_decision=replace(VALID_MODE_DECISION, selected_mode=""),
        ),
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.decision is not None
    assert result.decision.blocked_reason == LIVE_READINESS_BLOCK_INVALID_MODE_DECISION


def test_phase4_5_invalid_policy_fields_blocked_deterministically() -> None:
    controller = LiveExecutionGuardrails()

    result = controller.evaluate_readiness_with_trace(
        mode_input=VALID_MODE_INPUT,
        policy_input=LiveExecutionGuardrailPolicyInput(  # type: ignore[arg-type]
            explicit_live_request=True,
            live_feature_flag_present=True,
            live_feature_flag_enabled=True,
            kill_switch_present=True,
            kill_switch_armed=True,
            audit_hook_required=True,
            audit_hook_present=True,
            two_step_confirmation_required=True,
            two_step_confirmation_present=True,
            environment_name="staging-live-prep",
            allowed_live_environments=("staging-live-prep",),
            policy_trace_refs="not-a-dict",  # type: ignore[arg-type]
        ),
    )

    assert result.decision is not None
    assert result.decision.blocked_reason == LIVE_READINESS_BLOCK_INVALID_POLICY_INPUT


def test_phase4_5_upstream_mode_not_allowed_blocked_deterministically() -> None:
    controller = LiveExecutionGuardrails()

    result = controller.evaluate_readiness_with_trace(
        mode_input=replace(
            VALID_MODE_INPUT,
            mode_decision=replace(
                VALID_MODE_DECISION,
                allowed=False,
                blocked_reason="upstream_mode_blocked",
            ),
        ),
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.decision is not None
    assert result.decision.blocked_reason == LIVE_READINESS_BLOCK_UPSTREAM_MODE_NOT_ALLOWED


def test_phase4_5_non_live_mode_blocked_deterministically() -> None:
    controller = LiveExecutionGuardrails()

    result = controller.evaluate_readiness_with_trace(
        mode_input=replace(
            VALID_MODE_INPUT,
            mode_decision=replace(VALID_MODE_DECISION, selected_mode=MODE_SIMULATION),
        ),
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.decision is not None
    assert result.decision.blocked_reason == LIVE_READINESS_BLOCK_LIVE_MODE_REQUIRED


def test_phase4_5_explicit_live_request_missing_blocked_deterministically() -> None:
    controller = LiveExecutionGuardrails()

    result = controller.evaluate_readiness_with_trace(
        mode_input=VALID_MODE_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, explicit_live_request=False),
    )

    assert result.decision is not None
    assert result.decision.blocked_reason == LIVE_READINESS_BLOCK_EXPLICIT_LIVE_REQUEST_REQUIRED


def test_phase4_5_live_feature_flag_missing_blocked_deterministically() -> None:
    controller = LiveExecutionGuardrails()

    result = controller.evaluate_readiness_with_trace(
        mode_input=VALID_MODE_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, live_feature_flag_present=False),
    )

    assert result.decision is not None
    assert result.decision.blocked_reason == LIVE_READINESS_BLOCK_LIVE_FEATURE_FLAG_MISSING


def test_phase4_5_live_feature_flag_disabled_blocked_deterministically() -> None:
    controller = LiveExecutionGuardrails()

    result = controller.evaluate_readiness_with_trace(
        mode_input=VALID_MODE_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, live_feature_flag_enabled=False),
    )

    assert result.decision is not None
    assert result.decision.blocked_reason == LIVE_READINESS_BLOCK_LIVE_FEATURE_FLAG_DISABLED


def test_phase4_5_kill_switch_missing_blocked_deterministically() -> None:
    controller = LiveExecutionGuardrails()

    result = controller.evaluate_readiness_with_trace(
        mode_input=VALID_MODE_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, kill_switch_present=False),
    )

    assert result.decision is not None
    assert result.decision.blocked_reason == LIVE_READINESS_BLOCK_KILL_SWITCH_MISSING


def test_phase4_5_kill_switch_not_armed_blocked_deterministically() -> None:
    controller = LiveExecutionGuardrails()

    result = controller.evaluate_readiness_with_trace(
        mode_input=VALID_MODE_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, kill_switch_armed=False),
    )

    assert result.decision is not None
    assert result.decision.blocked_reason == LIVE_READINESS_BLOCK_KILL_SWITCH_NOT_ARMED


def test_phase4_5_audit_hook_missing_when_required_blocked_deterministically() -> None:
    controller = LiveExecutionGuardrails()

    result = controller.evaluate_readiness_with_trace(
        mode_input=VALID_MODE_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, audit_hook_present=False),
    )

    assert result.decision is not None
    assert result.decision.blocked_reason == LIVE_READINESS_BLOCK_AUDIT_HOOK_MISSING


def test_phase4_5_two_step_confirmation_missing_when_required_blocked_deterministically() -> None:
    controller = LiveExecutionGuardrails()

    result = controller.evaluate_readiness_with_trace(
        mode_input=VALID_MODE_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, two_step_confirmation_present=False),
    )

    assert result.decision is not None
    assert result.decision.blocked_reason == LIVE_READINESS_BLOCK_TWO_STEP_CONFIRMATION_MISSING


def test_phase4_5_environment_not_allow_listed_blocked_deterministically() -> None:
    controller = LiveExecutionGuardrails()

    result = controller.evaluate_readiness_with_trace(
        mode_input=VALID_MODE_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, environment_name="dev-sandbox"),
    )

    assert result.decision is not None
    assert result.decision.blocked_reason == LIVE_READINESS_BLOCK_ENVIRONMENT_NOT_ALLOWED


def test_phase4_5_deterministic_equality_for_same_valid_input() -> None:
    controller = LiveExecutionGuardrails()

    first = controller.evaluate_readiness_with_trace(
        mode_input=VALID_MODE_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )
    second = controller.evaluate_readiness_with_trace(
        mode_input=VALID_MODE_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )

    assert first == second


def test_phase4_5_simulated_and_non_executing_preserved_even_on_pass() -> None:
    controller = LiveExecutionGuardrails()

    decision = controller.evaluate_readiness(
        mode_input=VALID_MODE_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )

    assert decision is not None
    assert decision.simulated is True
    assert decision.non_executing is True


def test_phase4_5_upstream_non_executing_false_is_blocked_deterministically() -> None:
    controller = LiveExecutionGuardrails()

    result = controller.evaluate_readiness_with_trace(
        mode_input=replace(
            VALID_MODE_INPUT,
            mode_decision=replace(VALID_MODE_DECISION, non_executing=False),
        ),
        policy_input=VALID_POLICY_INPUT,
    )

    assert result.decision is not None
    assert result.decision.blocked_reason == LIVE_READINESS_BLOCK_NON_EXECUTING_REQUIRED


def test_phase4_5_no_network_api_wallet_signing_capital_fields_introduced() -> None:
    field_names = {item.name for item in fields(LiveExecutionReadinessDecision)}

    assert "api_key" not in field_names
    assert "private_key" not in field_names
    assert "wallet_address" not in field_names
    assert "signature" not in field_names
    assert "network_client" not in field_names
    assert "capital_transfer" not in field_names


def test_phase4_5_none_dict_wrong_object_inputs_do_not_crash() -> None:
    controller = LiveExecutionGuardrails()

    none_mode = controller.evaluate_readiness_with_trace(
        mode_input=None,  # type: ignore[arg-type]
        policy_input=VALID_POLICY_INPUT,
    )
    assert none_mode.decision is not None
    assert none_mode.decision.blocked_reason == LIVE_READINESS_BLOCK_INVALID_MODE_INPUT_CONTRACT

    dict_mode = controller.evaluate_readiness_with_trace(
        mode_input={"mode_decision": VALID_MODE_DECISION},  # type: ignore[arg-type]
        policy_input=VALID_POLICY_INPUT,
    )
    assert dict_mode.decision is not None
    assert dict_mode.decision.blocked_reason == LIVE_READINESS_BLOCK_INVALID_MODE_INPUT_CONTRACT

    wrong_policy = controller.evaluate_readiness_with_trace(
        mode_input=VALID_MODE_INPUT,
        policy_input={"explicit_live_request": True},  # type: ignore[arg-type]
    )
    assert wrong_policy.decision is not None
    assert wrong_policy.decision.blocked_reason == LIVE_READINESS_BLOCK_INVALID_POLICY_INPUT_CONTRACT
