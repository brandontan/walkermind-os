from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .execution_mode_controller import (
    MODE_FUTURE_LIVE,
    MODE_LIVE,
    ExecutionModeDecision,
)

LIVE_READINESS_BLOCK_INVALID_MODE_INPUT_CONTRACT = "invalid_mode_input_contract"
LIVE_READINESS_BLOCK_INVALID_POLICY_INPUT_CONTRACT = "invalid_policy_input_contract"
LIVE_READINESS_BLOCK_INVALID_MODE_DECISION = "invalid_mode_decision"
LIVE_READINESS_BLOCK_INVALID_POLICY_INPUT = "invalid_policy_input"
LIVE_READINESS_BLOCK_LIVE_MODE_REQUIRED = "live_mode_required"
LIVE_READINESS_BLOCK_UPSTREAM_MODE_NOT_ALLOWED = "upstream_mode_not_allowed"
LIVE_READINESS_BLOCK_EXPLICIT_LIVE_REQUEST_REQUIRED = "explicit_live_request_required"
LIVE_READINESS_BLOCK_LIVE_FEATURE_FLAG_MISSING = "live_feature_flag_missing"
LIVE_READINESS_BLOCK_LIVE_FEATURE_FLAG_DISABLED = "live_feature_flag_disabled"
LIVE_READINESS_BLOCK_KILL_SWITCH_MISSING = "kill_switch_missing"
LIVE_READINESS_BLOCK_KILL_SWITCH_NOT_ARMED = "kill_switch_not_armed"
LIVE_READINESS_BLOCK_AUDIT_HOOK_MISSING = "audit_hook_missing"
LIVE_READINESS_BLOCK_TWO_STEP_CONFIRMATION_MISSING = "two_step_confirmation_missing"
LIVE_READINESS_BLOCK_ENVIRONMENT_NOT_ALLOWED = "environment_not_allowed"
LIVE_READINESS_BLOCK_NON_EXECUTING_REQUIRED = "non_executing_required"


@dataclass(frozen=True)
class LiveExecutionModeInput:
    mode_decision: ExecutionModeDecision
    source_trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LiveExecutionGuardrailPolicyInput:
    explicit_live_request: bool
    live_feature_flag_present: bool
    live_feature_flag_enabled: bool
    kill_switch_present: bool
    kill_switch_armed: bool
    audit_hook_required: bool
    audit_hook_present: bool
    two_step_confirmation_required: bool
    two_step_confirmation_present: bool
    environment_name: str
    allowed_live_environments: tuple[str, ...] | list[str]
    policy_trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LiveExecutionReadinessDecision:
    live_ready: bool
    allowed: bool
    blocked_reason: str | None
    selected_mode: str
    guardrail_passed: bool
    kill_switch_armed: bool
    simulated: bool
    non_executing: bool


@dataclass(frozen=True)
class LiveExecutionReadinessTrace:
    readiness_evaluated: bool
    blocked_reason: str | None
    upstream_trace_refs: dict[str, Any] = field(default_factory=dict)
    guardrail_notes: dict[str, Any] | None = None


@dataclass(frozen=True)
class LiveExecutionReadinessBuildResult:
    decision: LiveExecutionReadinessDecision | None
    trace: LiveExecutionReadinessTrace


class LiveExecutionGuardrails:
    """Phase 4.5 deterministic live-readiness guardrails (still non-executing)."""

    def evaluate_readiness(
        self,
        mode_input: LiveExecutionModeInput,
        policy_input: LiveExecutionGuardrailPolicyInput,
    ) -> LiveExecutionReadinessDecision | None:
        return self.evaluate_readiness_with_trace(
            mode_input=mode_input,
            policy_input=policy_input,
        ).decision

    def evaluate_readiness_with_trace(
        self,
        *,
        mode_input: LiveExecutionModeInput,
        policy_input: LiveExecutionGuardrailPolicyInput,
    ) -> LiveExecutionReadinessBuildResult:
        if not isinstance(mode_input, LiveExecutionModeInput):
            return _blocked_result(
                selected_mode="",
                blocked_reason=LIVE_READINESS_BLOCK_INVALID_MODE_INPUT_CONTRACT,
                kill_switch_armed=False,
                readiness_evaluated=False,
                upstream_trace_refs={
                    "contract_errors": {
                        "mode_input": {
                            "expected_type": "LiveExecutionModeInput",
                            "actual_type": type(mode_input).__name__,
                        }
                    }
                },
                guardrail_notes={"contract_name": "mode_input"},
            )

        if not isinstance(policy_input, LiveExecutionGuardrailPolicyInput):
            return _blocked_result(
                selected_mode=_normalize_mode(mode_input.mode_decision.selected_mode),
                blocked_reason=LIVE_READINESS_BLOCK_INVALID_POLICY_INPUT_CONTRACT,
                kill_switch_armed=False,
                readiness_evaluated=False,
                upstream_trace_refs={
                    "mode_input": _trace_dict_or_empty(mode_input.source_trace_refs),
                    "contract_errors": {
                        "policy_input": {
                            "expected_type": "LiveExecutionGuardrailPolicyInput",
                            "actual_type": type(policy_input).__name__,
                        }
                    },
                },
                guardrail_notes={"contract_name": "policy_input"},
            )

        selected_mode = _normalize_mode(mode_input.mode_decision.selected_mode)
        upstream_trace_refs: dict[str, Any] = {
            "mode_input": _trace_dict_or_empty(mode_input.source_trace_refs),
            "policy_input": _trace_dict_or_empty(policy_input.policy_trace_refs),
        }

        mode_error = _validate_mode_decision(mode_input.mode_decision)
        if mode_error is not None:
            return _blocked_result(
                selected_mode=selected_mode,
                blocked_reason=LIVE_READINESS_BLOCK_INVALID_MODE_DECISION,
                kill_switch_armed=False,
                readiness_evaluated=True,
                upstream_trace_refs={
                    **upstream_trace_refs,
                    "contract_errors": {"mode_decision": mode_error},
                },
                guardrail_notes={"mode_decision_error": mode_error},
            )

        policy_error = _validate_policy_input(policy_input)
        if policy_error is not None:
            return _blocked_result(
                selected_mode=selected_mode,
                blocked_reason=LIVE_READINESS_BLOCK_INVALID_POLICY_INPUT,
                kill_switch_armed=bool(policy_input.kill_switch_armed),
                readiness_evaluated=True,
                upstream_trace_refs={
                    **upstream_trace_refs,
                    "contract_errors": {"policy_input": policy_error},
                },
                guardrail_notes={"policy_input_error": policy_error},
            )

        if selected_mode not in {MODE_LIVE, MODE_FUTURE_LIVE}:
            return _blocked_result(
                selected_mode=selected_mode,
                blocked_reason=LIVE_READINESS_BLOCK_LIVE_MODE_REQUIRED,
                kill_switch_armed=policy_input.kill_switch_armed,
                readiness_evaluated=True,
                upstream_trace_refs=upstream_trace_refs,
                guardrail_notes={"selected_mode": selected_mode},
            )

        if mode_input.mode_decision.allowed is not True:
            return _blocked_result(
                selected_mode=selected_mode,
                blocked_reason=LIVE_READINESS_BLOCK_UPSTREAM_MODE_NOT_ALLOWED,
                kill_switch_armed=policy_input.kill_switch_armed,
                readiness_evaluated=True,
                upstream_trace_refs=upstream_trace_refs,
                guardrail_notes={"upstream_blocked_reason": mode_input.mode_decision.blocked_reason},
            )

        if policy_input.explicit_live_request is not True:
            return _blocked_result(
                selected_mode=selected_mode,
                blocked_reason=LIVE_READINESS_BLOCK_EXPLICIT_LIVE_REQUEST_REQUIRED,
                kill_switch_armed=policy_input.kill_switch_armed,
                readiness_evaluated=True,
                upstream_trace_refs=upstream_trace_refs,
                guardrail_notes={"explicit_live_request": policy_input.explicit_live_request},
            )

        if policy_input.live_feature_flag_present is not True:
            return _blocked_result(
                selected_mode=selected_mode,
                blocked_reason=LIVE_READINESS_BLOCK_LIVE_FEATURE_FLAG_MISSING,
                kill_switch_armed=policy_input.kill_switch_armed,
                readiness_evaluated=True,
                upstream_trace_refs=upstream_trace_refs,
                guardrail_notes={"live_feature_flag_present": policy_input.live_feature_flag_present},
            )

        if policy_input.live_feature_flag_enabled is not True:
            return _blocked_result(
                selected_mode=selected_mode,
                blocked_reason=LIVE_READINESS_BLOCK_LIVE_FEATURE_FLAG_DISABLED,
                kill_switch_armed=policy_input.kill_switch_armed,
                readiness_evaluated=True,
                upstream_trace_refs=upstream_trace_refs,
                guardrail_notes={"live_feature_flag_enabled": policy_input.live_feature_flag_enabled},
            )

        if policy_input.kill_switch_present is not True:
            return _blocked_result(
                selected_mode=selected_mode,
                blocked_reason=LIVE_READINESS_BLOCK_KILL_SWITCH_MISSING,
                kill_switch_armed=policy_input.kill_switch_armed,
                readiness_evaluated=True,
                upstream_trace_refs=upstream_trace_refs,
                guardrail_notes={"kill_switch_present": policy_input.kill_switch_present},
            )

        if policy_input.kill_switch_armed is not True:
            return _blocked_result(
                selected_mode=selected_mode,
                blocked_reason=LIVE_READINESS_BLOCK_KILL_SWITCH_NOT_ARMED,
                kill_switch_armed=policy_input.kill_switch_armed,
                readiness_evaluated=True,
                upstream_trace_refs=upstream_trace_refs,
                guardrail_notes={"kill_switch_armed": policy_input.kill_switch_armed},
            )

        if policy_input.audit_hook_required and policy_input.audit_hook_present is not True:
            return _blocked_result(
                selected_mode=selected_mode,
                blocked_reason=LIVE_READINESS_BLOCK_AUDIT_HOOK_MISSING,
                kill_switch_armed=policy_input.kill_switch_armed,
                readiness_evaluated=True,
                upstream_trace_refs=upstream_trace_refs,
                guardrail_notes={"audit_hook_required": True},
            )

        if (
            policy_input.two_step_confirmation_required
            and policy_input.two_step_confirmation_present is not True
        ):
            return _blocked_result(
                selected_mode=selected_mode,
                blocked_reason=LIVE_READINESS_BLOCK_TWO_STEP_CONFIRMATION_MISSING,
                kill_switch_armed=policy_input.kill_switch_armed,
                readiness_evaluated=True,
                upstream_trace_refs=upstream_trace_refs,
                guardrail_notes={"two_step_confirmation_required": True},
            )

        allowed_environments = _normalize_allow_list(policy_input.allowed_live_environments)
        if policy_input.environment_name.strip() not in allowed_environments:
            return _blocked_result(
                selected_mode=selected_mode,
                blocked_reason=LIVE_READINESS_BLOCK_ENVIRONMENT_NOT_ALLOWED,
                kill_switch_armed=policy_input.kill_switch_armed,
                readiness_evaluated=True,
                upstream_trace_refs=upstream_trace_refs,
                guardrail_notes={
                    "environment_name": policy_input.environment_name,
                    "allowed_live_environments": sorted(allowed_environments),
                },
            )

        if mode_input.mode_decision.non_executing is not True:
            return _blocked_result(
                selected_mode=selected_mode,
                blocked_reason=LIVE_READINESS_BLOCK_NON_EXECUTING_REQUIRED,
                kill_switch_armed=policy_input.kill_switch_armed,
                readiness_evaluated=True,
                upstream_trace_refs=upstream_trace_refs,
                guardrail_notes={"upstream_non_executing": mode_input.mode_decision.non_executing},
            )

        return _allowed_result(
            selected_mode=selected_mode,
            kill_switch_armed=policy_input.kill_switch_armed,
            upstream_trace_refs=upstream_trace_refs,
        )


def _validate_mode_decision(mode_decision: ExecutionModeDecision) -> str | None:
    if not isinstance(mode_decision, ExecutionModeDecision):
        return "mode_decision_contract_required"
    if not isinstance(mode_decision.selected_mode, str) or not mode_decision.selected_mode.strip():
        return "selected_mode_required"
    if not isinstance(mode_decision.allowed, bool):
        return "allowed_must_be_bool"
    if mode_decision.blocked_reason is not None and not isinstance(mode_decision.blocked_reason, str):
        return "blocked_reason_must_be_str_or_none"
    if not isinstance(mode_decision.live_capable, bool):
        return "live_capable_must_be_bool"
    if not isinstance(mode_decision.simulated, bool):
        return "simulated_must_be_bool"
    if not isinstance(mode_decision.non_executing, bool):
        return "non_executing_must_be_bool"
    return None


def _validate_policy_input(policy_input: LiveExecutionGuardrailPolicyInput) -> str | None:
    bool_fields: dict[str, bool] = {
        "explicit_live_request": policy_input.explicit_live_request,
        "live_feature_flag_present": policy_input.live_feature_flag_present,
        "live_feature_flag_enabled": policy_input.live_feature_flag_enabled,
        "kill_switch_present": policy_input.kill_switch_present,
        "kill_switch_armed": policy_input.kill_switch_armed,
        "audit_hook_required": policy_input.audit_hook_required,
        "audit_hook_present": policy_input.audit_hook_present,
        "two_step_confirmation_required": policy_input.two_step_confirmation_required,
        "two_step_confirmation_present": policy_input.two_step_confirmation_present,
    }
    for name, value in bool_fields.items():
        if not isinstance(value, bool):
            return f"{name}_must_be_bool"

    if not isinstance(policy_input.environment_name, str) or not policy_input.environment_name.strip():
        return "environment_name_required"
    if not _is_valid_allow_list(policy_input.allowed_live_environments):
        return "allowed_live_environments_invalid"
    if not isinstance(policy_input.policy_trace_refs, dict):
        return "policy_trace_refs_must_be_dict"
    return None


def _is_valid_allow_list(values: tuple[str, ...] | list[str]) -> bool:
    if not isinstance(values, (tuple, list)):
        return False
    if not values:
        return False
    return all(isinstance(value, str) and value.strip() for value in values)


def _normalize_allow_list(values: tuple[str, ...] | list[str]) -> set[str]:
    return {value.strip() for value in values}


def _normalize_mode(raw_mode: str | None) -> str:
    if isinstance(raw_mode, str):
        return raw_mode.strip()
    return ""


def _trace_dict_or_empty(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _blocked_result(
    *,
    selected_mode: str,
    blocked_reason: str,
    kill_switch_armed: bool,
    readiness_evaluated: bool,
    upstream_trace_refs: dict[str, Any],
    guardrail_notes: dict[str, Any] | None,
) -> LiveExecutionReadinessBuildResult:
    decision = LiveExecutionReadinessDecision(
        live_ready=False,
        allowed=False,
        blocked_reason=blocked_reason,
        selected_mode=selected_mode,
        guardrail_passed=False,
        kill_switch_armed=bool(kill_switch_armed),
        simulated=True,
        non_executing=True,
    )
    trace = LiveExecutionReadinessTrace(
        readiness_evaluated=readiness_evaluated,
        blocked_reason=blocked_reason,
        upstream_trace_refs=upstream_trace_refs,
        guardrail_notes=guardrail_notes,
    )
    return LiveExecutionReadinessBuildResult(decision=decision, trace=trace)


def _allowed_result(
    *,
    selected_mode: str,
    kill_switch_armed: bool,
    upstream_trace_refs: dict[str, Any],
) -> LiveExecutionReadinessBuildResult:
    decision = LiveExecutionReadinessDecision(
        live_ready=True,
        allowed=True,
        blocked_reason=None,
        selected_mode=selected_mode,
        guardrail_passed=True,
        kill_switch_armed=bool(kill_switch_armed),
        simulated=True,
        non_executing=True,
    )
    trace = LiveExecutionReadinessTrace(
        readiness_evaluated=True,
        blocked_reason=None,
        upstream_trace_refs=upstream_trace_refs,
        guardrail_notes={
            "live_preparation_only": True,
            "execution_unlocked": False,
            "runtime_side_effects": False,
        },
    )
    return LiveExecutionReadinessBuildResult(decision=decision, trace=trace)
