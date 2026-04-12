from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .execution_intent import ExecutionIntent
from .execution_plan import ExecutionPlan
from .execution_risk import ExecutionRiskDecision

DECISION_BLOCK_INVALID_INTENT_CONTRACT = "invalid_intent_contract"
DECISION_BLOCK_INVALID_PLAN_CONTRACT = "invalid_plan_contract"
DECISION_BLOCK_INVALID_RISK_CONTRACT = "invalid_risk_contract"
DECISION_BLOCK_UPSTREAM_CONTRACT_MISMATCH = "upstream_contract_mismatch"
DECISION_BLOCK_UPSTREAM_BLOCKED = "upstream_blocked"


@dataclass(frozen=True)
class ExecutionDecisionIntentInput:
    intent: ExecutionIntent
    source_trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionDecisionPlanInput:
    plan: ExecutionPlan
    source_trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionDecisionRiskInput:
    risk_decision: ExecutionRiskDecision
    source_trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionDecision:
    allowed: bool
    blocked_reason: str | None
    market_id: str
    outcome: str
    side: str
    size: float
    routing_mode: str
    execution_mode: str
    ready_for_execution: bool
    non_activating: bool


@dataclass(frozen=True)
class ExecutionDecisionTrace:
    decision_created: bool
    blocked_reason: str | None
    upstream_trace_refs: dict[str, Any] = field(default_factory=dict)
    aggregation_notes: dict[str, Any] | None = None


@dataclass(frozen=True)
class ExecutionDecisionBuildResult:
    decision: ExecutionDecision | None
    trace: ExecutionDecisionTrace


class ExecutionDecisionAggregator:
    """Phase 3.6 deterministic, non-activating final pre-execution aggregation layer."""

    def aggregate(
        self,
        intent_input: ExecutionDecisionIntentInput,
        plan_input: ExecutionDecisionPlanInput,
        risk_input: ExecutionDecisionRiskInput,
    ) -> ExecutionDecision | None:
        return self.aggregate_with_trace(
            intent_input=intent_input,
            plan_input=plan_input,
            risk_input=risk_input,
        ).decision

    def aggregate_with_trace(
        self,
        *,
        intent_input: ExecutionDecisionIntentInput,
        plan_input: ExecutionDecisionPlanInput,
        risk_input: ExecutionDecisionRiskInput,
    ) -> ExecutionDecisionBuildResult:
        if not isinstance(intent_input, ExecutionDecisionIntentInput):
            return _blocked_invalid_contract_result(
                blocked_reason=DECISION_BLOCK_INVALID_INTENT_CONTRACT,
                contract_name="intent_input",
                contract_input=intent_input,
            )

        if not isinstance(plan_input, ExecutionDecisionPlanInput):
            return _blocked_invalid_contract_result(
                blocked_reason=DECISION_BLOCK_INVALID_PLAN_CONTRACT,
                contract_name="plan_input",
                contract_input=plan_input,
            )

        if not isinstance(risk_input, ExecutionDecisionRiskInput):
            return _blocked_invalid_contract_result(
                blocked_reason=DECISION_BLOCK_INVALID_RISK_CONTRACT,
                contract_name="risk_input",
                contract_input=risk_input,
            )

        upstream_trace_refs: dict[str, Any] = {
            "intent_input": dict(intent_input.source_trace_refs),
            "plan_input": dict(plan_input.source_trace_refs),
            "risk_input": dict(risk_input.source_trace_refs),
        }

        intent_error = _validate_intent(intent_input.intent)
        if intent_error is not None:
            return _blocked_result(
                blocked_reason=DECISION_BLOCK_INVALID_INTENT_CONTRACT,
                market_id="",
                outcome="",
                side="",
                size=0.0,
                routing_mode="",
                execution_mode="",
                upstream_trace_refs={
                    **upstream_trace_refs,
                    "contract_errors": {"intent_input": intent_error},
                },
                aggregation_notes={"intent_error": intent_error},
            )

        plan_error = _validate_plan(plan_input.plan)
        if plan_error is not None:
            return _blocked_result(
                blocked_reason=DECISION_BLOCK_INVALID_PLAN_CONTRACT,
                market_id=intent_input.intent.market_id,
                outcome=intent_input.intent.outcome,
                side=intent_input.intent.side,
                size=intent_input.intent.size,
                routing_mode=intent_input.intent.routing_mode,
                execution_mode="",
                upstream_trace_refs={
                    **upstream_trace_refs,
                    "contract_errors": {"plan_input": plan_error},
                },
                aggregation_notes={"plan_error": plan_error},
            )

        risk_error = _validate_risk(risk_input.risk_decision)
        if risk_error is not None:
            return _blocked_result(
                blocked_reason=DECISION_BLOCK_INVALID_RISK_CONTRACT,
                market_id=plan_input.plan.market_id,
                outcome=plan_input.plan.outcome,
                side=plan_input.plan.side,
                size=plan_input.plan.size,
                routing_mode=plan_input.plan.routing_mode,
                execution_mode=plan_input.plan.execution_mode,
                upstream_trace_refs={
                    **upstream_trace_refs,
                    "contract_errors": {"risk_input": risk_error},
                },
                aggregation_notes={"risk_error": risk_error},
            )

        mismatch = _find_mismatch(
            intent=intent_input.intent,
            plan=plan_input.plan,
            risk_decision=risk_input.risk_decision,
        )
        if mismatch is not None:
            return _blocked_result(
                blocked_reason=DECISION_BLOCK_UPSTREAM_CONTRACT_MISMATCH,
                market_id=plan_input.plan.market_id,
                outcome=plan_input.plan.outcome,
                side=plan_input.plan.side,
                size=plan_input.plan.size,
                routing_mode=plan_input.plan.routing_mode,
                execution_mode=plan_input.plan.execution_mode,
                upstream_trace_refs=upstream_trace_refs,
                aggregation_notes={"mismatch": mismatch},
            )

        if not risk_input.risk_decision.allowed:
            return _blocked_result(
                blocked_reason=DECISION_BLOCK_UPSTREAM_BLOCKED,
                market_id=plan_input.plan.market_id,
                outcome=plan_input.plan.outcome,
                side=plan_input.plan.side,
                size=plan_input.plan.size,
                routing_mode=plan_input.plan.routing_mode,
                execution_mode=plan_input.plan.execution_mode,
                upstream_trace_refs=upstream_trace_refs,
                aggregation_notes={"upstream_risk_blocked_reason": risk_input.risk_decision.blocked_reason},
            )

        decision = ExecutionDecision(
            allowed=True,
            blocked_reason=None,
            market_id=plan_input.plan.market_id,
            outcome=plan_input.plan.outcome,
            side=plan_input.plan.side,
            size=plan_input.plan.size,
            routing_mode=plan_input.plan.routing_mode,
            execution_mode=plan_input.plan.execution_mode,
            ready_for_execution=False,
            non_activating=True,
        )
        return ExecutionDecisionBuildResult(
            decision=decision,
            trace=ExecutionDecisionTrace(
                decision_created=True,
                blocked_reason=None,
                upstream_trace_refs=upstream_trace_refs,
                aggregation_notes={
                    "aggregation_mode": "pre_execution_non_activating",
                    "ready_for_execution": False,
                },
            ),
        )


def _validate_intent(intent: ExecutionIntent) -> str | None:
    if not isinstance(intent, ExecutionIntent):
        return "intent_contract_required"
    if not intent.market_id.strip():
        return "market_id_required"
    if not intent.outcome.strip():
        return "outcome_required"
    if not intent.side.strip():
        return "side_required"
    if not intent.routing_mode.strip():
        return "routing_mode_required"
    if intent.size < 0:
        return "size_must_be_non_negative"
    return None


def _validate_plan(plan: ExecutionPlan) -> str | None:
    if not isinstance(plan, ExecutionPlan):
        return "plan_contract_required"
    if not plan.market_id.strip():
        return "market_id_required"
    if not plan.outcome.strip():
        return "outcome_required"
    if not plan.side.strip():
        return "side_required"
    if not plan.routing_mode.strip():
        return "routing_mode_required"
    if not plan.execution_mode.strip():
        return "execution_mode_required"
    if plan.size < 0:
        return "size_must_be_non_negative"
    return None


def _validate_risk(risk_decision: ExecutionRiskDecision) -> str | None:
    if not isinstance(risk_decision, ExecutionRiskDecision):
        return "risk_contract_required"
    if not isinstance(risk_decision.allowed, bool):
        return "risk_allowed_must_be_bool"
    if not isinstance(risk_decision.non_activating, bool):
        return "risk_non_activating_must_be_bool"
    return None


def _find_mismatch(
    *,
    intent: ExecutionIntent,
    plan: ExecutionPlan,
    risk_decision: ExecutionRiskDecision,
) -> dict[str, Any] | None:
    if intent.market_id != plan.market_id:
        return {
            "field": "market_id",
            "intent_value": intent.market_id,
            "plan_value": plan.market_id,
        }
    if intent.outcome != plan.outcome:
        return {
            "field": "outcome",
            "intent_value": intent.outcome,
            "plan_value": plan.outcome,
        }
    if intent.side != plan.side:
        return {
            "field": "side",
            "intent_value": intent.side,
            "plan_value": plan.side,
        }
    if intent.size != plan.size:
        return {
            "field": "size",
            "intent_value": intent.size,
            "plan_value": plan.size,
        }
    if intent.routing_mode != plan.routing_mode:
        return {
            "field": "routing_mode",
            "intent_value": intent.routing_mode,
            "plan_value": plan.routing_mode,
        }
    if not risk_decision.non_activating:
        return {
            "field": "non_activating",
            "risk_value": risk_decision.non_activating,
            "required": True,
        }
    return None


def _blocked_invalid_contract_result(
    *,
    blocked_reason: str,
    contract_name: str,
    contract_input: Any,
) -> ExecutionDecisionBuildResult:
    return _blocked_result(
        blocked_reason=blocked_reason,
        market_id="",
        outcome="",
        side="",
        size=0.0,
        routing_mode="",
        execution_mode="",
        upstream_trace_refs={
            "contract_errors": {
                contract_name: {
                    "expected_type": contract_name,
                    "actual_type": type(contract_input).__name__,
                }
            }
        },
        aggregation_notes={"contract_name": contract_name},
    )


def _blocked_result(
    *,
    blocked_reason: str,
    market_id: str,
    outcome: str,
    side: str,
    size: float,
    routing_mode: str,
    execution_mode: str,
    upstream_trace_refs: dict[str, Any],
    aggregation_notes: dict[str, Any] | None,
) -> ExecutionDecisionBuildResult:
    decision = ExecutionDecision(
        allowed=False,
        blocked_reason=blocked_reason,
        market_id=market_id,
        outcome=outcome,
        side=side,
        size=size,
        routing_mode=routing_mode,
        execution_mode=execution_mode,
        ready_for_execution=False,
        non_activating=True,
    )
    return ExecutionDecisionBuildResult(
        decision=decision,
        trace=ExecutionDecisionTrace(
            decision_created=True,
            blocked_reason=blocked_reason,
            upstream_trace_refs=upstream_trace_refs,
            aggregation_notes=aggregation_notes,
        ),
    )
