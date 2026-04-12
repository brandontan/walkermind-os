from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Any

from .execution_decision import ExecutionDecision

EXECUTION_STATUS_BLOCKED = "BLOCKED"
EXECUTION_STATUS_SIMULATED_ACCEPTED = "SIMULATED_ACCEPTED"

ENGINE_BLOCK_INVALID_DECISION_CONTRACT = "invalid_decision_contract"
ENGINE_BLOCK_INVALID_DECISION_INPUT = "invalid_decision_input"
ENGINE_BLOCK_UPSTREAM_DECISION_BLOCKED = "upstream_decision_blocked"
ENGINE_BLOCK_DECISION_NOT_READY = "decision_not_ready"
ENGINE_BLOCK_NON_ACTIVATING_REQUIRED = "non_activating_required"


@dataclass(frozen=True)
class ExecutionEngineDecisionInput:
    decision: ExecutionDecision
    source_trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    blocked_reason: str | None
    execution_id: str
    accepted: bool
    simulated: bool
    non_activating: bool


@dataclass(frozen=True)
class ExecutionResultTrace:
    result_created: bool
    blocked_reason: str | None
    upstream_trace_refs: dict[str, Any] = field(default_factory=dict)
    execution_notes: dict[str, Any] | None = None


@dataclass(frozen=True)
class ExecutionResultBuildResult:
    result: ExecutionResult | None
    trace: ExecutionResultTrace


class ExecutionEngine:
    """Phase 3.7 deterministic non-activating execution skeleton consumer."""

    def execute(self, decision_input: ExecutionEngineDecisionInput) -> ExecutionResult | None:
        return self.execute_with_trace(decision_input=decision_input).result

    def execute_with_trace(
        self,
        *,
        decision_input: ExecutionEngineDecisionInput,
    ) -> ExecutionResultBuildResult:
        if not isinstance(decision_input, ExecutionEngineDecisionInput):
            return _blocked_invalid_input_result(
                blocked_reason=ENGINE_BLOCK_INVALID_DECISION_INPUT,
                input_name="decision_input",
                input_value=decision_input,
            )

        decision_error = _validate_decision_contract(decision_input.decision)
        if decision_error is not None:
            return _blocked_result(
                blocked_reason=ENGINE_BLOCK_INVALID_DECISION_CONTRACT,
                decision=decision_input.decision,
                upstream_trace_refs={
                    "decision_input": dict(decision_input.source_trace_refs),
                    "contract_errors": {"decision": decision_error},
                },
                execution_notes={"decision_error": decision_error},
            )

        if not decision_input.decision.allowed:
            return _blocked_result(
                blocked_reason=ENGINE_BLOCK_UPSTREAM_DECISION_BLOCKED,
                decision=decision_input.decision,
                upstream_trace_refs={"decision_input": dict(decision_input.source_trace_refs)},
                execution_notes={"upstream_blocked_reason": decision_input.decision.blocked_reason},
            )

        if not decision_input.decision.ready_for_execution:
            return _blocked_result(
                blocked_reason=ENGINE_BLOCK_DECISION_NOT_READY,
                decision=decision_input.decision,
                upstream_trace_refs={"decision_input": dict(decision_input.source_trace_refs)},
                execution_notes={"ready_for_execution": decision_input.decision.ready_for_execution},
            )

        if decision_input.decision.non_activating is not True:
            return _blocked_result(
                blocked_reason=ENGINE_BLOCK_NON_ACTIVATING_REQUIRED,
                decision=decision_input.decision,
                upstream_trace_refs={"decision_input": dict(decision_input.source_trace_refs)},
                execution_notes={"non_activating": decision_input.decision.non_activating},
            )

        result = ExecutionResult(
            status=EXECUTION_STATUS_SIMULATED_ACCEPTED,
            blocked_reason=None,
            execution_id=_build_execution_id(
                status=EXECUTION_STATUS_SIMULATED_ACCEPTED,
                blocked_reason=None,
                decision=decision_input.decision,
            ),
            accepted=True,
            simulated=True,
            non_activating=True,
        )
        return ExecutionResultBuildResult(
            result=result,
            trace=ExecutionResultTrace(
                result_created=True,
                blocked_reason=None,
                upstream_trace_refs={"decision_input": dict(decision_input.source_trace_refs)},
                execution_notes={
                    "execution_mode": "deterministic_simulation_only",
                    "side_effects": "none",
                },
            ),
        )


def _validate_decision_contract(decision: ExecutionDecision) -> str | None:
    if not isinstance(decision, ExecutionDecision):
        return "decision_contract_required"
    if not isinstance(decision.allowed, bool):
        return "allowed_must_be_bool"
    if not isinstance(decision.ready_for_execution, bool):
        return "ready_for_execution_must_be_bool"
    if not isinstance(decision.non_activating, bool):
        return "non_activating_must_be_bool"
    if not isinstance(decision.market_id, str):
        return "market_id_must_be_str"
    if not isinstance(decision.outcome, str):
        return "outcome_must_be_str"
    if not isinstance(decision.side, str):
        return "side_must_be_str"
    if not isinstance(decision.routing_mode, str):
        return "routing_mode_must_be_str"
    if not isinstance(decision.execution_mode, str):
        return "execution_mode_must_be_str"
    return None


def _blocked_invalid_input_result(
    *,
    blocked_reason: str,
    input_name: str,
    input_value: Any,
) -> ExecutionResultBuildResult:
    execution_id = _build_execution_id(
        status=EXECUTION_STATUS_BLOCKED,
        blocked_reason=blocked_reason,
        decision=None,
        fallback_parts={"input_name": input_name, "actual_type": type(input_value).__name__},
    )
    return ExecutionResultBuildResult(
        result=ExecutionResult(
            status=EXECUTION_STATUS_BLOCKED,
            blocked_reason=blocked_reason,
            execution_id=execution_id,
            accepted=False,
            simulated=True,
            non_activating=True,
        ),
        trace=ExecutionResultTrace(
            result_created=True,
            blocked_reason=blocked_reason,
            upstream_trace_refs={
                "contract_errors": {
                    input_name: {
                        "expected_type": input_name,
                        "actual_type": type(input_value).__name__,
                    }
                }
            },
            execution_notes={"input_name": input_name},
        ),
    )


def _blocked_result(
    *,
    blocked_reason: str,
    decision: ExecutionDecision,
    upstream_trace_refs: dict[str, Any],
    execution_notes: dict[str, Any] | None,
) -> ExecutionResultBuildResult:
    return ExecutionResultBuildResult(
        result=ExecutionResult(
            status=EXECUTION_STATUS_BLOCKED,
            blocked_reason=blocked_reason,
            execution_id=_build_execution_id(
                status=EXECUTION_STATUS_BLOCKED,
                blocked_reason=blocked_reason,
                decision=decision,
            ),
            accepted=False,
            simulated=True,
            non_activating=True,
        ),
        trace=ExecutionResultTrace(
            result_created=True,
            blocked_reason=blocked_reason,
            upstream_trace_refs=upstream_trace_refs,
            execution_notes=execution_notes,
        ),
    )


def _build_execution_id(
    *,
    status: str,
    blocked_reason: str | None,
    decision: ExecutionDecision | None,
    fallback_parts: dict[str, str] | None = None,
) -> str:
    identity_parts = [
        status,
        blocked_reason or "none",
    ]
    if decision is not None:
        identity_parts.extend(
            [
                decision.market_id,
                decision.outcome,
                decision.side,
                f"{decision.size:.10f}",
                decision.routing_mode,
                decision.execution_mode,
                str(decision.allowed),
                str(decision.ready_for_execution),
                str(decision.non_activating),
            ]
        )
    elif fallback_parts is not None:
        for key in sorted(fallback_parts.keys()):
            identity_parts.append(f"{key}:{fallback_parts[key]}")

    digest = hashlib.sha256("|".join(identity_parts).encode("utf-8")).hexdigest()[:16]
    return f"exec-{digest}"
