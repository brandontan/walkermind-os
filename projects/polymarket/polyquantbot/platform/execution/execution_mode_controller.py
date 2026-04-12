from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .execution_gateway import ExecutionGatewayResult

MODE_BLOCK_INVALID_GATEWAY_INPUT_CONTRACT = "invalid_gateway_input_contract"
MODE_BLOCK_INVALID_POLICY_INPUT_CONTRACT = "invalid_policy_input_contract"
MODE_BLOCK_INVALID_GATEWAY_RESULT = "invalid_gateway_result"
MODE_BLOCK_INVALID_POLICY_INPUT = "invalid_policy_input"
MODE_BLOCK_GATEWAY_NOT_ACCEPTED = "gateway_not_accepted"
MODE_BLOCK_REQUESTED_MODE_INVALID = "requested_mode_invalid"
MODE_BLOCK_SIMULATION_DISABLED = "simulation_disabled"
MODE_BLOCK_DRY_RUN_DISABLED = "dry_run_disabled"
MODE_BLOCK_LIVE_MODE_BLOCKED = "live_mode_blocked"
MODE_BLOCK_NON_EXECUTING_REQUIRED = "non_executing_required"

MODE_SIMULATION = "SIMULATION"
MODE_DRY_RUN = "DRY_RUN"
MODE_LIVE = "LIVE"
MODE_FUTURE_LIVE = "FUTURE_LIVE"


@dataclass(frozen=True)
class ExecutionModeGatewayInput:
    gateway_result: ExecutionGatewayResult
    source_trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionModePolicyInput:
    requested_mode: str
    simulation_enabled: bool = True
    dry_run_enabled: bool = False
    live_enabled: bool = False
    require_gateway_acceptance: bool = True
    policy_trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionModeDecision:
    selected_mode: str
    allowed: bool
    blocked_reason: str | None
    gateway_accepted: bool
    live_capable: bool
    simulated: bool
    non_executing: bool


@dataclass(frozen=True)
class ExecutionModeTrace:
    mode_evaluated: bool
    blocked_reason: str | None
    upstream_trace_refs: dict[str, Any] = field(default_factory=dict)
    mode_notes: dict[str, Any] | None = None


@dataclass(frozen=True)
class ExecutionModeBuildResult:
    decision: ExecutionModeDecision | None
    trace: ExecutionModeTrace


class ExecutionModeController:
    """Phase 4.4 deterministic execution mode controller (non-executing)."""

    def evaluate_mode(
        self,
        gateway_input: ExecutionModeGatewayInput,
        policy_input: ExecutionModePolicyInput,
    ) -> ExecutionModeDecision | None:
        return self.evaluate_mode_with_trace(
            gateway_input=gateway_input,
            policy_input=policy_input,
        ).decision

    def evaluate_mode_with_trace(
        self,
        *,
        gateway_input: ExecutionModeGatewayInput,
        policy_input: ExecutionModePolicyInput,
    ) -> ExecutionModeBuildResult:
        if not isinstance(gateway_input, ExecutionModeGatewayInput):
            return _blocked_mode_result(
                selected_mode=_normalize_mode(None),
                blocked_reason=MODE_BLOCK_INVALID_GATEWAY_INPUT_CONTRACT,
                gateway_accepted=False,
                upstream_trace_refs={
                    "contract_errors": {
                        "gateway_input": {
                            "expected_type": "ExecutionModeGatewayInput",
                            "actual_type": type(gateway_input).__name__,
                        }
                    }
                },
                mode_notes={"contract_name": "gateway_input"},
            )

        if not isinstance(policy_input, ExecutionModePolicyInput):
            return _blocked_mode_result(
                selected_mode=_normalize_mode(None),
                blocked_reason=MODE_BLOCK_INVALID_POLICY_INPUT_CONTRACT,
                gateway_accepted=False,
                upstream_trace_refs={
                    "gateway_input": dict(gateway_input.source_trace_refs),
                    "contract_errors": {
                        "policy_input": {
                            "expected_type": "ExecutionModePolicyInput",
                            "actual_type": type(policy_input).__name__,
                        }
                    },
                },
                mode_notes={"contract_name": "policy_input"},
            )

        gateway_error = _validate_gateway_result(gateway_input.gateway_result)
        normalized_mode = _normalize_mode(policy_input.requested_mode)
        if gateway_error is not None:
            return _blocked_mode_result(
                selected_mode=normalized_mode,
                blocked_reason=MODE_BLOCK_INVALID_GATEWAY_RESULT,
                gateway_accepted=False,
                upstream_trace_refs={
                    "gateway_input": dict(gateway_input.source_trace_refs),
                    "policy_input": dict(policy_input.policy_trace_refs),
                    "contract_errors": {"gateway_result": gateway_error},
                },
                mode_notes={"gateway_error": gateway_error},
            )

        policy_error = _validate_policy_input(policy_input)
        if policy_error is not None:
            return _blocked_mode_result(
                selected_mode=normalized_mode,
                blocked_reason=MODE_BLOCK_INVALID_POLICY_INPUT,
                gateway_accepted=bool(gateway_input.gateway_result.accepted),
                upstream_trace_refs={
                    "gateway_input": dict(gateway_input.source_trace_refs),
                    "policy_input": dict(policy_input.policy_trace_refs),
                    "contract_errors": {"policy_input": policy_error},
                },
                mode_notes={"policy_error": policy_error},
            )

        gateway_accepted = bool(gateway_input.gateway_result.accepted)
        if (
            policy_input.require_gateway_acceptance
            and gateway_accepted is not True
        ):
            return _blocked_mode_result(
                selected_mode=normalized_mode,
                blocked_reason=MODE_BLOCK_GATEWAY_NOT_ACCEPTED,
                gateway_accepted=gateway_accepted,
                upstream_trace_refs={
                    "gateway_input": dict(gateway_input.source_trace_refs),
                    "policy_input": dict(policy_input.policy_trace_refs),
                },
                mode_notes={"require_gateway_acceptance": True},
            )

        if gateway_input.gateway_result.non_executing is not True:
            return _blocked_mode_result(
                selected_mode=normalized_mode,
                blocked_reason=MODE_BLOCK_NON_EXECUTING_REQUIRED,
                gateway_accepted=gateway_accepted,
                upstream_trace_refs={
                    "gateway_input": dict(gateway_input.source_trace_refs),
                    "policy_input": dict(policy_input.policy_trace_refs),
                },
                mode_notes={"gateway_non_executing": gateway_input.gateway_result.non_executing},
            )

        if normalized_mode == MODE_SIMULATION:
            if policy_input.simulation_enabled is True:
                return _allowed_mode_result(
                    selected_mode=MODE_SIMULATION,
                    gateway_accepted=gateway_accepted,
                    upstream_trace_refs={
                        "gateway_input": dict(gateway_input.source_trace_refs),
                        "policy_input": dict(policy_input.policy_trace_refs),
                    },
                )
            return _blocked_mode_result(
                selected_mode=MODE_SIMULATION,
                blocked_reason=MODE_BLOCK_SIMULATION_DISABLED,
                gateway_accepted=gateway_accepted,
                upstream_trace_refs={
                    "gateway_input": dict(gateway_input.source_trace_refs),
                    "policy_input": dict(policy_input.policy_trace_refs),
                },
                mode_notes={"simulation_enabled": policy_input.simulation_enabled},
            )

        if normalized_mode == MODE_DRY_RUN:
            if policy_input.dry_run_enabled is True:
                return _allowed_mode_result(
                    selected_mode=MODE_DRY_RUN,
                    gateway_accepted=gateway_accepted,
                    upstream_trace_refs={
                        "gateway_input": dict(gateway_input.source_trace_refs),
                        "policy_input": dict(policy_input.policy_trace_refs),
                    },
                )
            return _blocked_mode_result(
                selected_mode=MODE_DRY_RUN,
                blocked_reason=MODE_BLOCK_DRY_RUN_DISABLED,
                gateway_accepted=gateway_accepted,
                upstream_trace_refs={
                    "gateway_input": dict(gateway_input.source_trace_refs),
                    "policy_input": dict(policy_input.policy_trace_refs),
                },
                mode_notes={"dry_run_enabled": policy_input.dry_run_enabled},
            )

        if normalized_mode in {MODE_LIVE, MODE_FUTURE_LIVE}:
            return _blocked_mode_result(
                selected_mode=normalized_mode,
                blocked_reason=MODE_BLOCK_LIVE_MODE_BLOCKED,
                gateway_accepted=gateway_accepted,
                upstream_trace_refs={
                    "gateway_input": dict(gateway_input.source_trace_refs),
                    "policy_input": dict(policy_input.policy_trace_refs),
                },
                mode_notes={
                    "live_enabled_requested": policy_input.live_enabled,
                    "phase_enforcement": "non_executing_only",
                },
            )

        return _blocked_mode_result(
            selected_mode=normalized_mode,
            blocked_reason=MODE_BLOCK_REQUESTED_MODE_INVALID,
            gateway_accepted=gateway_accepted,
            upstream_trace_refs={
                "gateway_input": dict(gateway_input.source_trace_refs),
                "policy_input": dict(policy_input.policy_trace_refs),
            },
            mode_notes={"requested_mode": policy_input.requested_mode},
        )


def _validate_gateway_result(gateway_result: ExecutionGatewayResult) -> str | None:
    if not isinstance(gateway_result, ExecutionGatewayResult):
        return "gateway_result_contract_required"
    if not isinstance(gateway_result.accepted, bool):
        return "accepted_must_be_bool"
    if not isinstance(gateway_result.non_executing, bool):
        return "non_executing_must_be_bool"
    return None


def _validate_policy_input(policy_input: ExecutionModePolicyInput) -> str | None:
    if not isinstance(policy_input.requested_mode, str) or not policy_input.requested_mode.strip():
        return "requested_mode_required"
    if not isinstance(policy_input.simulation_enabled, bool):
        return "simulation_enabled_must_be_bool"
    if not isinstance(policy_input.dry_run_enabled, bool):
        return "dry_run_enabled_must_be_bool"
    if not isinstance(policy_input.live_enabled, bool):
        return "live_enabled_must_be_bool"
    if not isinstance(policy_input.require_gateway_acceptance, bool):
        return "require_gateway_acceptance_must_be_bool"
    return None


def _normalize_mode(requested_mode: str | None) -> str:
    if not isinstance(requested_mode, str):
        return "INVALID"
    normalized = requested_mode.strip().upper()
    return normalized if normalized else "INVALID"


def _allowed_mode_result(
    *,
    selected_mode: str,
    gateway_accepted: bool,
    upstream_trace_refs: dict[str, Any],
) -> ExecutionModeBuildResult:
    return ExecutionModeBuildResult(
        decision=ExecutionModeDecision(
            selected_mode=selected_mode,
            allowed=True,
            blocked_reason=None,
            gateway_accepted=gateway_accepted,
            live_capable=False,
            simulated=True,
            non_executing=True,
        ),
        trace=ExecutionModeTrace(
            mode_evaluated=True,
            blocked_reason=None,
            upstream_trace_refs=upstream_trace_refs,
            mode_notes={"safe_default": "explicit_allow"},
        ),
    )


def _blocked_mode_result(
    *,
    selected_mode: str,
    blocked_reason: str,
    gateway_accepted: bool,
    upstream_trace_refs: dict[str, Any],
    mode_notes: dict[str, Any] | None,
) -> ExecutionModeBuildResult:
    return ExecutionModeBuildResult(
        decision=ExecutionModeDecision(
            selected_mode=selected_mode,
            allowed=False,
            blocked_reason=blocked_reason,
            gateway_accepted=gateway_accepted,
            live_capable=False,
            simulated=True,
            non_executing=True,
        ),
        trace=ExecutionModeTrace(
            mode_evaluated=False,
            blocked_reason=blocked_reason,
            upstream_trace_refs=upstream_trace_refs,
            mode_notes=mode_notes,
        ),
    )
