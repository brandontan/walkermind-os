from __future__ import annotations

from dataclasses import replace

from projects.polymarket.polyquantbot.platform.safety.kill_switch import (
    KILL_SWITCH_BLOCK_INVALID_INPUT_CONTRACT,
    KILL_SWITCH_BLOCK_NOT_ARMED,
    KILL_SWITCH_BLOCK_OPERATOR_HALT,
    KILL_SWITCH_BLOCK_POLICY_DISABLED,
    KillSwitchController,
    KillSwitchEvaluationInput,
    KillSwitchPolicyInput,
)


VALID_POLICY = KillSwitchPolicyInput(
    kill_switch_enabled=True,
    allow_operator_arm=True,
    allow_operator_disarm=True,
    operator_request_arm=True,
    operator_request_disarm=False,
    operator_halt_reason=None,
    policy_trace_refs={"phase": "6.3"},
)

VALID_EVALUATION = KillSwitchEvaluationInput(
    execution_requested=True,
    settlement_requested=True,
    transport_requested=True,
    system_halt_requested=False,
    halt_scope="all",
    upstream_trace_refs={"path": "transport-exchange-signing-capital-settlement"},
)


def test_phase6_3_operator_arm_forces_halt_decision() -> None:
    controller = KillSwitchController()

    state = controller.arm(VALID_POLICY)
    assert state.armed is True
    assert state.halt_active is True
    assert state.halt_reason == KILL_SWITCH_BLOCK_OPERATOR_HALT

    build = controller.evaluate_with_trace(
        evaluation_input=VALID_EVALUATION,
        policy_input=VALID_POLICY,
    )

    assert build.decision is not None
    assert build.decision.allowed_to_proceed is False
    assert build.decision.execution_blocked is True
    assert build.decision.settlement_blocked is True
    assert build.decision.transport_blocked is True
    assert build.decision.blocked_reason == KILL_SWITCH_BLOCK_OPERATOR_HALT
    assert build.trace.evaluation_attempted is True


def test_phase6_3_disarm_reopens_progression_when_policy_allows() -> None:
    controller = KillSwitchController()

    controller.arm(VALID_POLICY)
    disarmed = controller.disarm(
        replace(
            VALID_POLICY,
            operator_request_disarm=True,
            operator_request_arm=False,
        )
    )
    assert disarmed.halt_active is False

    build = controller.evaluate_with_trace(
        evaluation_input=VALID_EVALUATION,
        policy_input=VALID_POLICY,
    )

    assert build.decision is not None
    assert build.decision.blocked_reason == KILL_SWITCH_BLOCK_NOT_ARMED


def test_phase6_3_system_halt_is_deterministic_and_blocks_transport_path() -> None:
    controller = KillSwitchController()

    build = controller.evaluate_with_trace(
        evaluation_input=replace(
            VALID_EVALUATION,
            system_halt_requested=True,
            system_halt_reason="exchange_timeout_guard",
        ),
        policy_input=VALID_POLICY,
    )

    assert build.decision is not None
    assert build.decision.allowed_to_proceed is False
    assert build.decision.transport_blocked is True
    assert build.decision.state.system_triggered is True
    assert build.decision.blocked_reason == "exchange_timeout_guard"


def test_phase6_3_policy_disabled_blocks_progression_and_resets_state() -> None:
    controller = KillSwitchController()

    controller.arm(VALID_POLICY)
    build = controller.evaluate_with_trace(
        evaluation_input=VALID_EVALUATION,
        policy_input=replace(VALID_POLICY, kill_switch_enabled=False),
    )

    assert build.decision is not None
    assert build.decision.blocked_reason == KILL_SWITCH_BLOCK_POLICY_DISABLED
    assert build.decision.state.armed is False
    assert build.decision.state.halt_active is False


def test_phase6_3_invalid_input_contract_is_blocked_without_crash() -> None:
    controller = KillSwitchController()

    invalid_eval = controller.evaluate_with_trace(
        evaluation_input=None,  # type: ignore[arg-type]
        policy_input=VALID_POLICY,
    )
    invalid_policy = controller.evaluate_with_trace(
        evaluation_input=VALID_EVALUATION,
        policy_input=None,  # type: ignore[arg-type]
    )

    assert invalid_eval.decision is not None
    assert invalid_eval.decision.blocked_reason == KILL_SWITCH_BLOCK_INVALID_INPUT_CONTRACT
    assert invalid_policy.decision is not None
    assert invalid_policy.decision.blocked_reason == KILL_SWITCH_BLOCK_INVALID_INPUT_CONTRACT


def test_phase6_3_deterministic_same_inputs_same_outputs() -> None:
    controller = KillSwitchController()

    controller.arm(VALID_POLICY)
    first = controller.evaluate_with_trace(
        evaluation_input=VALID_EVALUATION,
        policy_input=VALID_POLICY,
    )

    controller = KillSwitchController()
    controller.arm(VALID_POLICY)
    second = controller.evaluate_with_trace(
        evaluation_input=VALID_EVALUATION,
        policy_input=VALID_POLICY,
    )

    assert first == second
