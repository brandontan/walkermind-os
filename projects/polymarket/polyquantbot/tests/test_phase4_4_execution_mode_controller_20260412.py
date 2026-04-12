from __future__ import annotations

from dataclasses import fields, replace

from projects.polymarket.polyquantbot.platform.execution.execution_gateway import (
    GATEWAY_EXECUTION_STATUS_ACCEPTED,
    ExecutionGatewayResult,
)
from projects.polymarket.polyquantbot.platform.execution.execution_mode_controller import (
    MODE_BLOCK_DRY_RUN_DISABLED,
    MODE_BLOCK_GATEWAY_NOT_ACCEPTED,
    MODE_BLOCK_INVALID_GATEWAY_INPUT_CONTRACT,
    MODE_BLOCK_INVALID_POLICY_INPUT,
    MODE_BLOCK_INVALID_POLICY_INPUT_CONTRACT,
    MODE_BLOCK_LIVE_MODE_BLOCKED,
    MODE_BLOCK_REQUESTED_MODE_INVALID,
    MODE_BLOCK_SIMULATION_DISABLED,
    MODE_DRY_RUN,
    MODE_FUTURE_LIVE,
    MODE_LIVE,
    MODE_SIMULATION,
    ExecutionModeController,
    ExecutionModeDecision,
    ExecutionModeGatewayInput,
    ExecutionModePolicyInput,
)

VALID_GATEWAY_RESULT = ExecutionGatewayResult(
    accepted=True,
    blocked_reason=None,
    execution_status=GATEWAY_EXECUTION_STATUS_ACCEPTED,
    request_built=True,
    response_status="SIMULATED_ACCEPTED",
    client_order_id="SIM-VALID",
    simulated=True,
    non_executing=True,
)

VALID_GATEWAY_INPUT = ExecutionModeGatewayInput(
    gateway_result=VALID_GATEWAY_RESULT,
    source_trace_refs={"gateway_trace_id": "GW-4-4"},
)


def test_phase4_4_gateway_accepted_simulation_enabled_allows_simulation() -> None:
    controller = ExecutionModeController()

    result = controller.evaluate_mode_with_trace(
        gateway_input=VALID_GATEWAY_INPUT,
        policy_input=ExecutionModePolicyInput(requested_mode=MODE_SIMULATION),
    )

    assert result.decision is not None
    assert result.decision.selected_mode == MODE_SIMULATION
    assert result.decision.allowed is True
    assert result.decision.blocked_reason is None
    assert result.decision.live_capable is False
    assert result.decision.simulated is True
    assert result.decision.non_executing is True


def test_phase4_4_gateway_accepted_dry_run_enabled_allows_dry_run() -> None:
    controller = ExecutionModeController()

    result = controller.evaluate_mode_with_trace(
        gateway_input=VALID_GATEWAY_INPUT,
        policy_input=ExecutionModePolicyInput(
            requested_mode=MODE_DRY_RUN,
            dry_run_enabled=True,
        ),
    )

    assert result.decision is not None
    assert result.decision.selected_mode == MODE_DRY_RUN
    assert result.decision.allowed is True
    assert result.decision.blocked_reason is None
    assert result.decision.live_capable is False
    assert result.decision.simulated is True
    assert result.decision.non_executing is True


def test_phase4_4_live_requested_is_deterministically_blocked() -> None:
    controller = ExecutionModeController()

    result = controller.evaluate_mode_with_trace(
        gateway_input=VALID_GATEWAY_INPUT,
        policy_input=ExecutionModePolicyInput(
            requested_mode=MODE_LIVE,
            live_enabled=True,
        ),
    )

    assert result.decision is not None
    assert result.decision.selected_mode == MODE_LIVE
    assert result.decision.allowed is False
    assert result.decision.blocked_reason == MODE_BLOCK_LIVE_MODE_BLOCKED
    assert result.decision.live_capable is False
    assert result.decision.simulated is True
    assert result.decision.non_executing is True


def test_phase4_4_invalid_top_level_gateway_input_blocked_deterministically() -> None:
    controller = ExecutionModeController()

    result = controller.evaluate_mode_with_trace(
        gateway_input=None,  # type: ignore[arg-type]
        policy_input=ExecutionModePolicyInput(requested_mode=MODE_SIMULATION),
    )

    assert result.decision is not None
    assert result.decision.allowed is False
    assert result.decision.blocked_reason == MODE_BLOCK_INVALID_GATEWAY_INPUT_CONTRACT


def test_phase4_4_invalid_policy_input_blocked_deterministically() -> None:
    controller = ExecutionModeController()

    result = controller.evaluate_mode_with_trace(
        gateway_input=VALID_GATEWAY_INPUT,
        policy_input=ExecutionModePolicyInput(  # type: ignore[arg-type]
            requested_mode=MODE_SIMULATION,
            simulation_enabled="yes",  # type: ignore[arg-type]
        ),
    )

    assert result.decision is not None
    assert result.decision.allowed is False
    assert result.decision.blocked_reason == MODE_BLOCK_INVALID_POLICY_INPUT


def test_phase4_4_gateway_not_accepted_blocked_deterministically() -> None:
    controller = ExecutionModeController()

    result = controller.evaluate_mode_with_trace(
        gateway_input=ExecutionModeGatewayInput(
            gateway_result=replace(VALID_GATEWAY_RESULT, accepted=False)
        ),
        policy_input=ExecutionModePolicyInput(requested_mode=MODE_SIMULATION),
    )

    assert result.decision is not None
    assert result.decision.allowed is False
    assert result.decision.blocked_reason == MODE_BLOCK_GATEWAY_NOT_ACCEPTED




def test_phase4_4_future_live_requested_is_explicitly_recognized_and_blocked() -> None:
    controller = ExecutionModeController()

    result = controller.evaluate_mode_with_trace(
        gateway_input=VALID_GATEWAY_INPUT,
        policy_input=ExecutionModePolicyInput(requested_mode=MODE_FUTURE_LIVE),
    )

    assert result.decision is not None
    assert result.decision.selected_mode == MODE_FUTURE_LIVE
    assert result.decision.allowed is False
    assert result.decision.blocked_reason == MODE_BLOCK_LIVE_MODE_BLOCKED

def test_phase4_4_unknown_requested_mode_blocked_deterministically() -> None:
    controller = ExecutionModeController()

    result = controller.evaluate_mode_with_trace(
        gateway_input=VALID_GATEWAY_INPUT,
        policy_input=ExecutionModePolicyInput(requested_mode="UNSUPPORTED_MODE"),
    )

    assert result.decision is not None
    assert result.decision.selected_mode == "UNSUPPORTED_MODE"
    assert result.decision.allowed is False
    assert result.decision.blocked_reason == MODE_BLOCK_REQUESTED_MODE_INVALID


def test_phase4_4_simulation_disabled_blocked_deterministically() -> None:
    controller = ExecutionModeController()

    result = controller.evaluate_mode_with_trace(
        gateway_input=VALID_GATEWAY_INPUT,
        policy_input=ExecutionModePolicyInput(
            requested_mode=MODE_SIMULATION,
            simulation_enabled=False,
        ),
    )

    assert result.decision is not None
    assert result.decision.allowed is False
    assert result.decision.blocked_reason == MODE_BLOCK_SIMULATION_DISABLED


def test_phase4_4_dry_run_disabled_blocked_deterministically() -> None:
    controller = ExecutionModeController()

    result = controller.evaluate_mode_with_trace(
        gateway_input=VALID_GATEWAY_INPUT,
        policy_input=ExecutionModePolicyInput(requested_mode=MODE_DRY_RUN),
    )

    assert result.decision is not None
    assert result.decision.allowed is False
    assert result.decision.blocked_reason == MODE_BLOCK_DRY_RUN_DISABLED


def test_phase4_4_deterministic_equality_for_same_valid_input() -> None:
    controller = ExecutionModeController()
    policy = ExecutionModePolicyInput(requested_mode=MODE_SIMULATION)

    first = controller.evaluate_mode_with_trace(
        gateway_input=VALID_GATEWAY_INPUT,
        policy_input=policy,
    )
    second = controller.evaluate_mode_with_trace(
        gateway_input=VALID_GATEWAY_INPUT,
        policy_input=policy,
    )

    assert first == second


def test_phase4_4_no_network_api_wallet_signing_capital_fields_introduced() -> None:
    field_names = {item.name for item in fields(ExecutionModeDecision)}

    assert "api_key" not in field_names
    assert "private_key" not in field_names
    assert "wallet_address" not in field_names
    assert "signature" not in field_names
    assert "network_client" not in field_names
    assert "capital_transfer" not in field_names


def test_phase4_4_none_dict_wrong_object_inputs_do_not_crash() -> None:
    controller = ExecutionModeController()

    none_gateway = controller.evaluate_mode_with_trace(
        gateway_input=None,  # type: ignore[arg-type]
        policy_input=ExecutionModePolicyInput(requested_mode=MODE_SIMULATION),
    )
    assert none_gateway.decision is not None
    assert none_gateway.decision.blocked_reason == MODE_BLOCK_INVALID_GATEWAY_INPUT_CONTRACT

    dict_gateway = controller.evaluate_mode_with_trace(
        gateway_input={"gateway_result": VALID_GATEWAY_RESULT},  # type: ignore[arg-type]
        policy_input=ExecutionModePolicyInput(requested_mode=MODE_SIMULATION),
    )
    assert dict_gateway.decision is not None
    assert dict_gateway.decision.blocked_reason == MODE_BLOCK_INVALID_GATEWAY_INPUT_CONTRACT

    wrong_policy = controller.evaluate_mode_with_trace(
        gateway_input=VALID_GATEWAY_INPUT,
        policy_input={"requested_mode": MODE_SIMULATION},  # type: ignore[arg-type]
    )
    assert wrong_policy.decision is not None
    assert wrong_policy.decision.blocked_reason == MODE_BLOCK_INVALID_POLICY_INPUT_CONTRACT
