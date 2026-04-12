from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .execution_plan import ExecutionPlan

RISK_BLOCK_INVALID_PLAN_INPUT_CONTRACT = "invalid_plan_input_contract"
RISK_BLOCK_INVALID_POLICY_INPUT_CONTRACT = "invalid_policy_input_contract"
RISK_BLOCK_INVALID_PLAN_INPUT = "invalid_plan_input"
RISK_BLOCK_INVALID_POLICY_INPUT = "invalid_policy_input"
RISK_BLOCK_PLAN_NOT_READY = "plan_not_ready"
RISK_BLOCK_NON_ACTIVATING_REQUIRED = "non_activating_required"
RISK_BLOCK_SIDE_NOT_ALLOWED = "side_not_allowed"
RISK_BLOCK_ROUTING_MODE_NOT_ALLOWED = "routing_mode_not_allowed"
RISK_BLOCK_SIZE_EXCEEDS_POLICY_CAP = "size_exceeds_policy_cap"
RISK_BLOCK_SLIPPAGE_EXCEEDS_POLICY_CAP = "slippage_exceeds_policy_cap"
RISK_BLOCK_EXECUTION_MODE_NOT_ALLOWED = "execution_mode_not_allowed"


@dataclass(frozen=True)
class ExecutionRiskPlanInput:
    plan: ExecutionPlan
    source_trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionRiskPolicyInput:
    max_size: float
    max_slippage_bps: int
    allowed_sides: tuple[str, ...] | list[str]
    allowed_routing_modes: tuple[str, ...] | list[str]
    allowed_execution_modes: tuple[str, ...] | list[str]
    require_non_activating: bool = True
    policy_trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionRiskDecision:
    allowed: bool
    risk_score: float | None
    blocked_reason: str | None
    risk_flags: list[str]
    non_activating: bool


@dataclass(frozen=True)
class ExecutionRiskTrace:
    decision_created: bool
    blocked_reason: str | None
    upstream_trace_refs: dict[str, Any] = field(default_factory=dict)
    risk_notes: dict[str, Any] | None = None


@dataclass(frozen=True)
class ExecutionRiskBuildResult:
    decision: ExecutionRiskDecision | None
    trace: ExecutionRiskTrace


class ExecutionRiskEvaluator:
    """Phase 3.5 deterministic, local-only, non-activating risk evaluator."""

    def evaluate(
        self,
        plan_input: ExecutionRiskPlanInput,
        policy_input: ExecutionRiskPolicyInput,
    ) -> ExecutionRiskDecision | None:
        return self.evaluate_with_trace(
            plan_input=plan_input,
            policy_input=policy_input,
        ).decision

    def evaluate_with_trace(
        self,
        *,
        plan_input: ExecutionRiskPlanInput,
        policy_input: ExecutionRiskPolicyInput,
    ) -> ExecutionRiskBuildResult:
        if not isinstance(plan_input, ExecutionRiskPlanInput):
            return _blocked_invalid_contract_result(
                blocked_reason=RISK_BLOCK_INVALID_PLAN_INPUT_CONTRACT,
                contract_name="plan_input",
                contract_input=plan_input,
            )

        if not isinstance(policy_input, ExecutionRiskPolicyInput):
            return _blocked_invalid_contract_result(
                blocked_reason=RISK_BLOCK_INVALID_POLICY_INPUT_CONTRACT,
                contract_name="policy_input",
                contract_input=policy_input,
            )

        upstream_trace_refs: dict[str, Any] = {
            "plan_input": dict(plan_input.source_trace_refs),
            "policy_input": dict(policy_input.policy_trace_refs),
        }

        plan_error = _validate_plan_input(plan_input)
        if plan_error is not None:
            return _blocked_result(
                blocked_reason=RISK_BLOCK_INVALID_PLAN_INPUT,
                plan_non_activating=True,
                upstream_trace_refs={
                    **upstream_trace_refs,
                    "contract_errors": {"plan_input": plan_error},
                },
                risk_notes={"plan_input_error": plan_error},
            )

        policy_error = _validate_policy_input(policy_input)
        if policy_error is not None:
            return _blocked_result(
                blocked_reason=RISK_BLOCK_INVALID_POLICY_INPUT,
                plan_non_activating=plan_input.plan.non_activating,
                upstream_trace_refs={
                    **upstream_trace_refs,
                    "contract_errors": {"policy_input": policy_error},
                },
                risk_notes={"policy_input_error": policy_error},
            )

        plan = plan_input.plan
        if not plan.plan_ready:
            return _blocked_result(
                blocked_reason=RISK_BLOCK_PLAN_NOT_READY,
                plan_non_activating=plan.non_activating,
                upstream_trace_refs=upstream_trace_refs,
                risk_notes={"plan_ready": False},
            )

        if policy_input.require_non_activating and not plan.non_activating:
            return _blocked_result(
                blocked_reason=RISK_BLOCK_NON_ACTIVATING_REQUIRED,
                plan_non_activating=plan.non_activating,
                upstream_trace_refs=upstream_trace_refs,
                risk_notes={"require_non_activating": True},
            )

        allowed_sides = _normalize_allow_list(policy_input.allowed_sides)
        if plan.side not in allowed_sides:
            return _blocked_result(
                blocked_reason=RISK_BLOCK_SIDE_NOT_ALLOWED,
                plan_non_activating=plan.non_activating,
                upstream_trace_refs=upstream_trace_refs,
                risk_notes={"side": plan.side, "allowed_sides": sorted(allowed_sides)},
            )

        allowed_routing_modes = _normalize_allow_list(policy_input.allowed_routing_modes)
        if plan.routing_mode not in allowed_routing_modes:
            return _blocked_result(
                blocked_reason=RISK_BLOCK_ROUTING_MODE_NOT_ALLOWED,
                plan_non_activating=plan.non_activating,
                upstream_trace_refs=upstream_trace_refs,
                risk_notes={
                    "routing_mode": plan.routing_mode,
                    "allowed_routing_modes": sorted(allowed_routing_modes),
                },
            )

        if plan.size > policy_input.max_size:
            return _blocked_result(
                blocked_reason=RISK_BLOCK_SIZE_EXCEEDS_POLICY_CAP,
                plan_non_activating=plan.non_activating,
                upstream_trace_refs=upstream_trace_refs,
                risk_notes={"size": plan.size, "max_size": policy_input.max_size},
            )

        slippage_bps = plan.slippage_bps if plan.slippage_bps is not None else 0
        if slippage_bps > policy_input.max_slippage_bps:
            return _blocked_result(
                blocked_reason=RISK_BLOCK_SLIPPAGE_EXCEEDS_POLICY_CAP,
                plan_non_activating=plan.non_activating,
                upstream_trace_refs=upstream_trace_refs,
                risk_notes={
                    "slippage_bps": slippage_bps,
                    "max_slippage_bps": policy_input.max_slippage_bps,
                },
            )

        allowed_execution_modes = _normalize_allow_list(policy_input.allowed_execution_modes)
        if plan.execution_mode not in allowed_execution_modes:
            return _blocked_result(
                blocked_reason=RISK_BLOCK_EXECUTION_MODE_NOT_ALLOWED,
                plan_non_activating=plan.non_activating,
                upstream_trace_refs=upstream_trace_refs,
                risk_notes={
                    "execution_mode": plan.execution_mode,
                    "allowed_execution_modes": sorted(allowed_execution_modes),
                },
            )

        risk_score = _compute_risk_score(
            size=plan.size,
            max_size=policy_input.max_size,
            slippage_bps=slippage_bps,
            max_slippage_bps=policy_input.max_slippage_bps,
        )

        decision = ExecutionRiskDecision(
            allowed=True,
            risk_score=risk_score,
            blocked_reason=None,
            risk_flags=[],
            non_activating=plan.non_activating,
        )
        return ExecutionRiskBuildResult(
            decision=decision,
            trace=ExecutionRiskTrace(
                decision_created=True,
                blocked_reason=None,
                upstream_trace_refs=upstream_trace_refs,
                risk_notes={
                    "risk_score_method": "normalized_size_slippage_average",
                    "normalized_size": round(plan.size / policy_input.max_size, 6),
                    "normalized_slippage": round(slippage_bps / policy_input.max_slippage_bps, 6)
                    if policy_input.max_slippage_bps > 0
                    else 0.0,
                },
            ),
        )


def _validate_plan_input(plan_input: ExecutionRiskPlanInput) -> str | None:
    if not isinstance(plan_input.plan, ExecutionPlan):
        return "plan_contract_required"

    plan = plan_input.plan
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
    if plan.slippage_bps is not None and plan.slippage_bps < 0:
        return "slippage_bps_must_be_non_negative"
    return None


def _validate_policy_input(policy_input: ExecutionRiskPolicyInput) -> str | None:
    if policy_input.max_size <= 0:
        return "max_size_must_be_positive"
    if policy_input.max_slippage_bps < 0:
        return "max_slippage_bps_must_be_non_negative"
    if not isinstance(policy_input.require_non_activating, bool):
        return "require_non_activating_must_be_bool"

    if not _is_valid_allow_list(policy_input.allowed_sides):
        return "allowed_sides_invalid"
    if not _is_valid_allow_list(policy_input.allowed_routing_modes):
        return "allowed_routing_modes_invalid"
    if not _is_valid_allow_list(policy_input.allowed_execution_modes):
        return "allowed_execution_modes_invalid"
    return None


def _is_valid_allow_list(values: tuple[str, ...] | list[str]) -> bool:
    if not isinstance(values, (tuple, list)):
        return False
    if not values:
        return False
    return all(isinstance(value, str) and value.strip() for value in values)


def _normalize_allow_list(values: tuple[str, ...] | list[str]) -> set[str]:
    return {item.strip() for item in values}


def _compute_risk_score(
    *,
    size: float,
    max_size: float,
    slippage_bps: int,
    max_slippage_bps: int,
) -> float:
    normalized_size = size / max_size
    normalized_slippage = slippage_bps / max_slippage_bps if max_slippage_bps > 0 else 0.0
    return round((normalized_size + normalized_slippage) / 2.0, 6)


def _blocked_invalid_contract_result(
    *,
    blocked_reason: str,
    contract_name: str,
    contract_input: Any,
) -> ExecutionRiskBuildResult:
    return _blocked_result(
        blocked_reason=blocked_reason,
        plan_non_activating=True,
        upstream_trace_refs={
            "contract_errors": {
                contract_name: {
                    "expected_type": contract_name,
                    "actual_type": type(contract_input).__name__,
                }
            }
        },
        risk_notes={"contract_name": contract_name},
    )


def _blocked_result(
    *,
    blocked_reason: str,
    plan_non_activating: bool,
    upstream_trace_refs: dict[str, Any],
    risk_notes: dict[str, Any] | None,
) -> ExecutionRiskBuildResult:
    decision = ExecutionRiskDecision(
        allowed=False,
        risk_score=None,
        blocked_reason=blocked_reason,
        risk_flags=[blocked_reason],
        non_activating=plan_non_activating,
    )
    return ExecutionRiskBuildResult(
        decision=decision,
        trace=ExecutionRiskTrace(
            decision_created=True,
            blocked_reason=blocked_reason,
            upstream_trace_refs=upstream_trace_refs,
            risk_notes=risk_notes,
        ),
    )
