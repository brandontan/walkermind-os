from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

KILL_SWITCH_SCOPE_ALL = "all"

KILL_SWITCH_BLOCK_INVALID_INPUT_CONTRACT = "invalid_kill_switch_input_contract"
KILL_SWITCH_BLOCK_POLICY_DISABLED = "kill_switch_policy_disabled"
KILL_SWITCH_BLOCK_NOT_ARMED = "kill_switch_not_armed"
KILL_SWITCH_BLOCK_OPERATOR_ARM_NOT_ALLOWED = "operator_arm_not_allowed"
KILL_SWITCH_BLOCK_OPERATOR_DISARM_NOT_ALLOWED = "operator_disarm_not_allowed"
KILL_SWITCH_BLOCK_OPERATOR_REQUEST_MISSING = "operator_arm_request_missing"
KILL_SWITCH_BLOCK_DISARM_REQUEST_MISSING = "operator_disarm_request_missing"
KILL_SWITCH_BLOCK_ACTIVE = "kill_switch_halt_active"
KILL_SWITCH_BLOCK_OPERATOR_HALT = "operator_halt_active"
KILL_SWITCH_BLOCK_SYSTEM_HALT = "system_halt_active"


@dataclass(frozen=True)
class KillSwitchState:
    armed: bool
    halt_active: bool
    halt_reason: str | None
    halt_scope: str
    operator_triggered: bool
    system_triggered: bool


@dataclass(frozen=True)
class KillSwitchDecision:
    execution_blocked: bool
    settlement_blocked: bool
    transport_blocked: bool
    allowed_to_proceed: bool
    blocked_reason: str | None
    state: KillSwitchState


@dataclass(frozen=True)
class KillSwitchTrace:
    evaluation_attempted: bool
    blocked_reason: str | None
    trace_refs: dict[str, Any] = field(default_factory=dict)
    halt_notes: dict[str, Any] | None = None


@dataclass(frozen=True)
class KillSwitchBuildResult:
    decision: KillSwitchDecision | None
    trace: KillSwitchTrace


@dataclass(frozen=True)
class KillSwitchPolicyInput:
    kill_switch_enabled: bool
    allow_operator_arm: bool
    allow_operator_disarm: bool
    operator_request_arm: bool
    operator_request_disarm: bool = False
    operator_halt_reason: str | None = None
    policy_trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KillSwitchEvaluationInput:
    execution_requested: bool
    settlement_requested: bool
    transport_requested: bool
    system_halt_requested: bool = False
    system_halt_reason: str | None = None
    halt_scope: str = KILL_SWITCH_SCOPE_ALL
    upstream_trace_refs: dict[str, Any] = field(default_factory=dict)


class KillSwitchController:
    """Phase 6.3 deterministic kill-switch and execution-halt controller."""

    def __init__(self) -> None:
        self._state = KillSwitchState(
            armed=False,
            halt_active=False,
            halt_reason=None,
            halt_scope=KILL_SWITCH_SCOPE_ALL,
            operator_triggered=False,
            system_triggered=False,
        )

    def evaluate(
        self,
        evaluation_input: KillSwitchEvaluationInput,
        policy_input: KillSwitchPolicyInput,
    ) -> KillSwitchDecision | None:
        return self.evaluate_with_trace(
            evaluation_input=evaluation_input,
            policy_input=policy_input,
        ).decision

    def evaluate_with_trace(
        self,
        *,
        evaluation_input: KillSwitchEvaluationInput,
        policy_input: KillSwitchPolicyInput,
    ) -> KillSwitchBuildResult:
        if not isinstance(evaluation_input, KillSwitchEvaluationInput):
            return _blocked_result(
                state=self._state,
                blocked_reason=KILL_SWITCH_BLOCK_INVALID_INPUT_CONTRACT,
                evaluation_attempted=False,
                trace_refs={
                    "contract_errors": {
                        "evaluation_input": {
                            "expected_type": "KillSwitchEvaluationInput",
                            "actual_type": type(evaluation_input).__name__,
                        }
                    }
                },
            )

        if not isinstance(policy_input, KillSwitchPolicyInput):
            return _blocked_result(
                state=self._state,
                blocked_reason=KILL_SWITCH_BLOCK_INVALID_INPUT_CONTRACT,
                evaluation_attempted=False,
                trace_refs={
                    "contract_errors": {
                        "policy_input": {
                            "expected_type": "KillSwitchPolicyInput",
                            "actual_type": type(policy_input).__name__,
                        }
                    }
                },
            )

        trace_refs: dict[str, Any] = {
            "policy": dict(policy_input.policy_trace_refs),
            "evaluation": dict(evaluation_input.upstream_trace_refs),
            "scope": evaluation_input.halt_scope,
        }

        if policy_input.kill_switch_enabled is not True:
            next_state = KillSwitchState(
                armed=False,
                halt_active=False,
                halt_reason=KILL_SWITCH_BLOCK_POLICY_DISABLED,
                halt_scope=evaluation_input.halt_scope,
                operator_triggered=False,
                system_triggered=False,
            )
            self._state = next_state
            return _decision_result(
                state=next_state,
                execution_requested=evaluation_input.execution_requested,
                settlement_requested=evaluation_input.settlement_requested,
                transport_requested=evaluation_input.transport_requested,
                blocked_reason=KILL_SWITCH_BLOCK_POLICY_DISABLED,
                evaluation_attempted=True,
                trace_refs=trace_refs,
                halt_notes={"kill_switch_enabled": False},
            )

        if evaluation_input.system_halt_requested:
            system_reason = _normalized_reason(
                evaluation_input.system_halt_reason,
                fallback=KILL_SWITCH_BLOCK_SYSTEM_HALT,
            )
            self._state = KillSwitchState(
                armed=True,
                halt_active=True,
                halt_reason=system_reason,
                halt_scope=evaluation_input.halt_scope,
                operator_triggered=False,
                system_triggered=True,
            )

        if self._state.halt_active:
            return _decision_result(
                state=self._state,
                execution_requested=evaluation_input.execution_requested,
                settlement_requested=evaluation_input.settlement_requested,
                transport_requested=evaluation_input.transport_requested,
                blocked_reason=self._state.halt_reason or KILL_SWITCH_BLOCK_ACTIVE,
                evaluation_attempted=True,
                trace_refs=trace_refs,
                halt_notes={"halt_source": _halt_source(self._state)},
            )

        if self._state.armed is not True:
            return _decision_result(
                state=self._state,
                execution_requested=evaluation_input.execution_requested,
                settlement_requested=evaluation_input.settlement_requested,
                transport_requested=evaluation_input.transport_requested,
                blocked_reason=KILL_SWITCH_BLOCK_NOT_ARMED,
                evaluation_attempted=True,
                trace_refs=trace_refs,
                halt_notes={"armed": False},
            )

        return KillSwitchBuildResult(
            decision=KillSwitchDecision(
                execution_blocked=False,
                settlement_blocked=False,
                transport_blocked=False,
                allowed_to_proceed=True,
                blocked_reason=None,
                state=self._state,
            ),
            trace=KillSwitchTrace(
                evaluation_attempted=True,
                blocked_reason=None,
                trace_refs=trace_refs,
                halt_notes={"status": "safe_to_proceed"},
            ),
        )

    def arm(self, policy_input: KillSwitchPolicyInput) -> KillSwitchState:
        if not isinstance(policy_input, KillSwitchPolicyInput):
            return self._state

        if policy_input.kill_switch_enabled is not True:
            self._state = KillSwitchState(
                armed=False,
                halt_active=False,
                halt_reason=KILL_SWITCH_BLOCK_POLICY_DISABLED,
                halt_scope=KILL_SWITCH_SCOPE_ALL,
                operator_triggered=False,
                system_triggered=False,
            )
            return self._state

        if policy_input.allow_operator_arm is not True:
            self._state = KillSwitchState(
                armed=False,
                halt_active=True,
                halt_reason=KILL_SWITCH_BLOCK_OPERATOR_ARM_NOT_ALLOWED,
                halt_scope=KILL_SWITCH_SCOPE_ALL,
                operator_triggered=True,
                system_triggered=False,
            )
            return self._state

        if policy_input.operator_request_arm is not True:
            self._state = KillSwitchState(
                armed=False,
                halt_active=True,
                halt_reason=KILL_SWITCH_BLOCK_OPERATOR_REQUEST_MISSING,
                halt_scope=KILL_SWITCH_SCOPE_ALL,
                operator_triggered=True,
                system_triggered=False,
            )
            return self._state

        self._state = KillSwitchState(
            armed=True,
            halt_active=True,
            halt_reason=_normalized_reason(
                policy_input.operator_halt_reason,
                fallback=KILL_SWITCH_BLOCK_OPERATOR_HALT,
            ),
            halt_scope=KILL_SWITCH_SCOPE_ALL,
            operator_triggered=True,
            system_triggered=False,
        )
        return self._state

    def disarm(self, policy_input: KillSwitchPolicyInput) -> KillSwitchState:
        if not isinstance(policy_input, KillSwitchPolicyInput):
            return self._state

        if policy_input.kill_switch_enabled is not True:
            self._state = KillSwitchState(
                armed=False,
                halt_active=False,
                halt_reason=KILL_SWITCH_BLOCK_POLICY_DISABLED,
                halt_scope=KILL_SWITCH_SCOPE_ALL,
                operator_triggered=False,
                system_triggered=False,
            )
            return self._state

        if policy_input.allow_operator_disarm is not True:
            return self._state

        if policy_input.operator_request_disarm is not True:
            return self._state

        self._state = KillSwitchState(
            armed=False,
            halt_active=False,
            halt_reason=None,
            halt_scope=KILL_SWITCH_SCOPE_ALL,
            operator_triggered=False,
            system_triggered=False,
        )
        return self._state


def _decision_result(
    *,
    state: KillSwitchState,
    execution_requested: bool,
    settlement_requested: bool,
    transport_requested: bool,
    blocked_reason: str,
    evaluation_attempted: bool,
    trace_refs: dict[str, Any],
    halt_notes: dict[str, Any] | None = None,
) -> KillSwitchBuildResult:
    execution_blocked = execution_requested
    settlement_blocked = settlement_requested
    transport_blocked = transport_requested
    return KillSwitchBuildResult(
        decision=KillSwitchDecision(
            execution_blocked=execution_blocked,
            settlement_blocked=settlement_blocked,
            transport_blocked=transport_blocked,
            allowed_to_proceed=not (execution_blocked or settlement_blocked or transport_blocked),
            blocked_reason=blocked_reason,
            state=state,
        ),
        trace=KillSwitchTrace(
            evaluation_attempted=evaluation_attempted,
            blocked_reason=blocked_reason,
            trace_refs=trace_refs,
            halt_notes=halt_notes,
        ),
    )


def _blocked_result(
    *,
    state: KillSwitchState,
    blocked_reason: str,
    evaluation_attempted: bool,
    trace_refs: dict[str, Any],
) -> KillSwitchBuildResult:
    return KillSwitchBuildResult(
        decision=KillSwitchDecision(
            execution_blocked=True,
            settlement_blocked=True,
            transport_blocked=True,
            allowed_to_proceed=False,
            blocked_reason=blocked_reason,
            state=state,
        ),
        trace=KillSwitchTrace(
            evaluation_attempted=evaluation_attempted,
            blocked_reason=blocked_reason,
            trace_refs=trace_refs,
            halt_notes={"contract_error": True},
        ),
    )


def _normalized_reason(reason: str | None, *, fallback: str) -> str:
    normalized = (reason or "").strip()
    if normalized:
        return normalized
    return fallback


def _halt_source(state: KillSwitchState) -> str:
    if state.system_triggered:
        return "system"
    if state.operator_triggered:
        return "operator"
    return "unknown"
