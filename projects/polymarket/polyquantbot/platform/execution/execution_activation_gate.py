from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .execution_decision import ExecutionDecision

ACTIVATION_BLOCK_INVALID_DECISION_INPUT_CONTRACT = "invalid_decision_input_contract"
ACTIVATION_BLOCK_INVALID_POLICY_INPUT_CONTRACT = "invalid_policy_input_contract"
ACTIVATION_BLOCK_INVALID_DECISION_INPUT = "invalid_decision_input"
ACTIVATION_BLOCK_INVALID_POLICY_INPUT = "invalid_policy_input"
ACTIVATION_BLOCK_UPSTREAM_DECISION_BLOCKED = "upstream_decision_blocked"
ACTIVATION_BLOCK_ACTIVATION_DISABLED = "activation_disabled"
ACTIVATION_BLOCK_ACTIVATION_MODE_NOT_ALLOWED = "activation_mode_not_allowed"
ACTIVATION_BLOCK_SOURCE_NON_ACTIVATING_REQUIRED = "source_non_activating_required"
ACTIVATION_BLOCK_ALREADY_READY_FOR_EXECUTION = "already_ready_for_execution"
ACTIVATION_BLOCK_SIMULATION_ONLY_REQUIRED = "simulation_only_required"


@dataclass(frozen=True)
class ExecutionActivationDecisionInput:
    decision: ExecutionDecision
    activation_mode: str
    source_trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionActivationPolicyInput:
    activation_enabled: bool
    allowed_activation_modes: tuple[str, ...] | list[str]
    require_non_activating_source: bool = True
    allow_simulation_only: bool = True
    policy_trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionActivationDecision:
    activated: bool
    blocked_reason: str | None
    ready_for_execution: bool
    activation_mode: str
    activation_allowed: bool
    non_activating: bool


@dataclass(frozen=True)
class ExecutionActivationTrace:
    decision_created: bool
    blocked_reason: str | None
    upstream_trace_refs: dict[str, Any] = field(default_factory=dict)
    activation_notes: dict[str, Any] | None = None


@dataclass(frozen=True)
class ExecutionActivationBuildResult:
    decision: ExecutionActivationDecision | None
    trace: ExecutionActivationTrace


class ExecutionActivationGate:
    """Phase 3.8 deterministic, explicit, default-off execution activation gate."""

    def evaluate(
        self,
        decision_input: ExecutionActivationDecisionInput,
        policy_input: ExecutionActivationPolicyInput,
    ) -> ExecutionActivationDecision | None:
        return self.evaluate_with_trace(
            decision_input=decision_input,
            policy_input=policy_input,
        ).decision

    def evaluate_with_trace(
        self,
        *,
        decision_input: ExecutionActivationDecisionInput,
        policy_input: ExecutionActivationPolicyInput,
    ) -> ExecutionActivationBuildResult:
        if not isinstance(decision_input, ExecutionActivationDecisionInput):
            return _blocked_invalid_contract_result(
                blocked_reason=ACTIVATION_BLOCK_INVALID_DECISION_INPUT_CONTRACT,
                contract_name="decision_input",
                contract_input=decision_input,
            )

        if not isinstance(policy_input, ExecutionActivationPolicyInput):
            return _blocked_invalid_contract_result(
                blocked_reason=ACTIVATION_BLOCK_INVALID_POLICY_INPUT_CONTRACT,
                contract_name="policy_input",
                contract_input=policy_input,
            )

        upstream_trace_refs: dict[str, Any] = {
            "decision_input": dict(decision_input.source_trace_refs),
            "policy_input": dict(policy_input.policy_trace_refs),
        }

        decision_error = _validate_decision_input(decision_input)
        if decision_error is not None:
            return _blocked_result(
                blocked_reason=ACTIVATION_BLOCK_INVALID_DECISION_INPUT,
                activation_mode=decision_input.activation_mode,
                upstream_trace_refs={
                    **upstream_trace_refs,
                    "contract_errors": {"decision_input": decision_error},
                },
                activation_notes={"decision_input_error": decision_error},
            )

        policy_error = _validate_policy_input(policy_input)
        if policy_error is not None:
            return _blocked_result(
                blocked_reason=ACTIVATION_BLOCK_INVALID_POLICY_INPUT,
                activation_mode=decision_input.activation_mode,
                upstream_trace_refs={
                    **upstream_trace_refs,
                    "contract_errors": {"policy_input": policy_error},
                },
                activation_notes={"policy_input_error": policy_error},
            )

        source_decision = decision_input.decision
        if not source_decision.allowed:
            return _blocked_result(
                blocked_reason=ACTIVATION_BLOCK_UPSTREAM_DECISION_BLOCKED,
                activation_mode=decision_input.activation_mode,
                upstream_trace_refs=upstream_trace_refs,
                activation_notes={"upstream_blocked_reason": source_decision.blocked_reason},
            )

        if not policy_input.activation_enabled:
            return _blocked_result(
                blocked_reason=ACTIVATION_BLOCK_ACTIVATION_DISABLED,
                activation_mode=decision_input.activation_mode,
                upstream_trace_refs=upstream_trace_refs,
                activation_notes={"activation_enabled": False},
            )

        allowed_modes = _normalize_allow_list(policy_input.allowed_activation_modes)
        if decision_input.activation_mode not in allowed_modes:
            return _blocked_result(
                blocked_reason=ACTIVATION_BLOCK_ACTIVATION_MODE_NOT_ALLOWED,
                activation_mode=decision_input.activation_mode,
                upstream_trace_refs=upstream_trace_refs,
                activation_notes={
                    "activation_mode": decision_input.activation_mode,
                    "allowed_activation_modes": sorted(allowed_modes),
                },
            )

        if policy_input.require_non_activating_source and not source_decision.non_activating:
            return _blocked_result(
                blocked_reason=ACTIVATION_BLOCK_SOURCE_NON_ACTIVATING_REQUIRED,
                activation_mode=decision_input.activation_mode,
                upstream_trace_refs=upstream_trace_refs,
                activation_notes={"require_non_activating_source": True},
            )

        if source_decision.ready_for_execution:
            return _blocked_result(
                blocked_reason=ACTIVATION_BLOCK_ALREADY_READY_FOR_EXECUTION,
                activation_mode=decision_input.activation_mode,
                upstream_trace_refs=upstream_trace_refs,
                activation_notes={"source_ready_for_execution": True},
            )

        if policy_input.allow_simulation_only and not _is_simulation_mode(source_decision.execution_mode):
            return _blocked_result(
                blocked_reason=ACTIVATION_BLOCK_SIMULATION_ONLY_REQUIRED,
                activation_mode=decision_input.activation_mode,
                upstream_trace_refs=upstream_trace_refs,
                activation_notes={
                    "allow_simulation_only": True,
                    "execution_mode": source_decision.execution_mode,
                },
            )

        decision = ExecutionActivationDecision(
            activated=True,
            blocked_reason=None,
            ready_for_execution=True,
            activation_mode=decision_input.activation_mode,
            activation_allowed=True,
            non_activating=True,
        )
        return ExecutionActivationBuildResult(
            decision=decision,
            trace=ExecutionActivationTrace(
                decision_created=True,
                blocked_reason=None,
                upstream_trace_refs=upstream_trace_refs,
                activation_notes={
                    "activation_gate": "explicit_policy_unlock",
                    "local_policy_evaluation_only": True,
                    "external_state_mutation": False,
                },
            ),
        )


def _validate_decision_input(decision_input: ExecutionActivationDecisionInput) -> str | None:
    if not isinstance(decision_input.decision, ExecutionDecision):
        return "decision_contract_required"

    decision = decision_input.decision
    if not decision.market_id.strip():
        return "market_id_required"
    if not decision.outcome.strip():
        return "outcome_required"
    if not decision.side.strip():
        return "side_required"
    if not decision.routing_mode.strip():
        return "routing_mode_required"
    if not decision.execution_mode.strip():
        return "execution_mode_required"
    if not isinstance(decision.non_activating, bool):
        return "decision_non_activating_must_be_bool"
    if not isinstance(decision.ready_for_execution, bool):
        return "decision_ready_for_execution_must_be_bool"
    if not isinstance(decision.allowed, bool):
        return "decision_allowed_must_be_bool"
    if not isinstance(decision_input.activation_mode, str) or not decision_input.activation_mode.strip():
        return "activation_mode_required"
    return None


def _validate_policy_input(policy_input: ExecutionActivationPolicyInput) -> str | None:
    if not isinstance(policy_input.activation_enabled, bool):
        return "activation_enabled_must_be_bool"
    if not isinstance(policy_input.require_non_activating_source, bool):
        return "require_non_activating_source_must_be_bool"
    if not isinstance(policy_input.allow_simulation_only, bool):
        return "allow_simulation_only_must_be_bool"
    if not _is_valid_allow_list(policy_input.allowed_activation_modes):
        return "allowed_activation_modes_invalid"
    return None


def _is_valid_allow_list(values: tuple[str, ...] | list[str]) -> bool:
    if not isinstance(values, (tuple, list)):
        return False
    if not values:
        return False
    return all(isinstance(value, str) and value.strip() for value in values)


def _normalize_allow_list(values: tuple[str, ...] | list[str]) -> set[str]:
    return {value.strip() for value in values}


def _is_simulation_mode(execution_mode: str) -> bool:
    normalized = execution_mode.strip().lower()
    return normalized.startswith("paper") or "simulation" in normalized


def _blocked_invalid_contract_result(
    *,
    blocked_reason: str,
    contract_name: str,
    contract_input: Any,
) -> ExecutionActivationBuildResult:
    return _blocked_result(
        blocked_reason=blocked_reason,
        activation_mode="",
        upstream_trace_refs={
            "contract_errors": {
                contract_name: {
                    "expected_type": contract_name,
                    "actual_type": type(contract_input).__name__,
                }
            }
        },
        activation_notes={"contract_name": contract_name},
    )


def _blocked_result(
    *,
    blocked_reason: str,
    activation_mode: str,
    upstream_trace_refs: dict[str, Any],
    activation_notes: dict[str, Any] | None,
) -> ExecutionActivationBuildResult:
    decision = ExecutionActivationDecision(
        activated=False,
        blocked_reason=blocked_reason,
        ready_for_execution=False,
        activation_mode=activation_mode,
        activation_allowed=False,
        non_activating=True,
    )
    return ExecutionActivationBuildResult(
        decision=decision,
        trace=ExecutionActivationTrace(
            decision_created=True,
            blocked_reason=blocked_reason,
            upstream_trace_refs=upstream_trace_refs,
            activation_notes=activation_notes,
        ),
    )
