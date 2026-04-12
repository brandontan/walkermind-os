from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PLAN_BLOCK_INVALID_INTENT_CONTRACT = "invalid_intent_contract"
PLAN_BLOCK_INVALID_MARKET_CONTEXT_CONTRACT = "invalid_market_context_contract"
PLAN_BLOCK_INVALID_INTENT_INPUT = "invalid_intent_input"
PLAN_BLOCK_INVALID_MARKET_CONTEXT = "invalid_market_context"
PLAN_BLOCK_MARKET_CONTEXT_MISMATCH = "market_context_mismatch"
PLAN_BLOCK_MARKET_NOT_PLANNABLE = "market_not_plannable"

_ALLOWED_SIDES: frozenset[str] = frozenset({"BUY", "SELL"})
_ALLOWED_ROUTING_MODES: frozenset[str] = frozenset(
    {
        "disabled",
        "legacy-only",
        "platform-gateway-shadow",
        "platform-gateway-primary",
    }
)


@dataclass(frozen=True)
class ExecutionPlanIntentInput:
    market_id: str
    outcome: str
    side: str
    size: float
    routing_mode: str
    limit_price_hint: float | None = None
    source_trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionPlanMarketContextInput:
    market_id: str
    outcome: str
    planning_allowed: bool
    execution_mode_label: str
    reference_price: float | None = None
    slippage_bps_hint: int | None = None
    upstream_trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionPlan:
    market_id: str
    outcome: str
    side: str
    size: float
    routing_mode: str
    execution_mode: str
    limit_price: float | None
    slippage_bps: int | None
    plan_ready: bool
    non_activating: bool


@dataclass(frozen=True)
class ExecutionPlanTrace:
    plan_created: bool
    blocked_reason: str | None
    upstream_trace_refs: dict[str, Any] = field(default_factory=dict)
    planning_notes: dict[str, Any] | None = None


@dataclass(frozen=True)
class ExecutionPlanBuildResult:
    plan: ExecutionPlan | None
    trace: ExecutionPlanTrace


class ExecutionPlanBuilder:
    """Phase 3.4 deterministic, non-activating execution planning builder."""

    def build_from_intent(
        self,
        intent_input: ExecutionPlanIntentInput,
        market_context_input: ExecutionPlanMarketContextInput,
    ) -> ExecutionPlan | None:
        return self.build_with_trace(
            intent_input=intent_input,
            market_context_input=market_context_input,
        ).plan

    def build_with_trace(
        self,
        *,
        intent_input: ExecutionPlanIntentInput,
        market_context_input: ExecutionPlanMarketContextInput,
    ) -> ExecutionPlanBuildResult:
        if not isinstance(intent_input, ExecutionPlanIntentInput):
            return _blocked_invalid_contract_result(
                blocked_reason=PLAN_BLOCK_INVALID_INTENT_CONTRACT,
                contract_name="intent",
                contract_input=intent_input,
            )

        if not isinstance(market_context_input, ExecutionPlanMarketContextInput):
            return _blocked_invalid_contract_result(
                blocked_reason=PLAN_BLOCK_INVALID_MARKET_CONTEXT_CONTRACT,
                contract_name="market_context",
                contract_input=market_context_input,
            )

        upstream_trace_refs: dict[str, Any] = {
            "intent": dict(intent_input.source_trace_refs),
            "market_context": dict(market_context_input.upstream_trace_refs),
        }

        intent_error = _validate_intent_input(intent_input)
        if intent_error is not None:
            return ExecutionPlanBuildResult(
                plan=None,
                trace=ExecutionPlanTrace(
                    plan_created=False,
                    blocked_reason=PLAN_BLOCK_INVALID_INTENT_INPUT,
                    upstream_trace_refs={
                        **upstream_trace_refs,
                        "contract_errors": {"intent": intent_error},
                    },
                    planning_notes={"intent_error": intent_error},
                ),
            )

        context_error = _validate_market_context_input(market_context_input)
        if context_error is not None:
            return ExecutionPlanBuildResult(
                plan=None,
                trace=ExecutionPlanTrace(
                    plan_created=False,
                    blocked_reason=PLAN_BLOCK_INVALID_MARKET_CONTEXT,
                    upstream_trace_refs={
                        **upstream_trace_refs,
                        "contract_errors": {"market_context": context_error},
                    },
                    planning_notes={"market_context_error": context_error},
                ),
            )

        if (
            intent_input.market_id != market_context_input.market_id
            or intent_input.outcome != market_context_input.outcome
        ):
            return ExecutionPlanBuildResult(
                plan=None,
                trace=ExecutionPlanTrace(
                    plan_created=False,
                    blocked_reason=PLAN_BLOCK_MARKET_CONTEXT_MISMATCH,
                    upstream_trace_refs=upstream_trace_refs,
                    planning_notes={
                        "intent_market_id": intent_input.market_id,
                        "context_market_id": market_context_input.market_id,
                        "intent_outcome": intent_input.outcome,
                        "context_outcome": market_context_input.outcome,
                    },
                ),
            )

        if not market_context_input.planning_allowed:
            return ExecutionPlanBuildResult(
                plan=None,
                trace=ExecutionPlanTrace(
                    plan_created=False,
                    blocked_reason=PLAN_BLOCK_MARKET_NOT_PLANNABLE,
                    upstream_trace_refs=upstream_trace_refs,
                    planning_notes={"planning_allowed": False},
                ),
            )

        plan = ExecutionPlan(
            market_id=intent_input.market_id,
            outcome=intent_input.outcome,
            side=intent_input.side,
            size=intent_input.size,
            routing_mode=intent_input.routing_mode,
            execution_mode=market_context_input.execution_mode_label,
            limit_price=_derive_limit_price(intent_input, market_context_input),
            slippage_bps=_derive_slippage_bps(market_context_input),
            plan_ready=True,
            non_activating=True,
        )

        return ExecutionPlanBuildResult(
            plan=plan,
            trace=ExecutionPlanTrace(
                plan_created=True,
                blocked_reason=None,
                upstream_trace_refs=upstream_trace_refs,
                planning_notes={
                    "limit_price_source": _limit_price_source(intent_input, market_context_input),
                    "execution_mode_label": market_context_input.execution_mode_label,
                    "non_activating": True,
                },
            ),
        )


def _validate_intent_input(intent_input: ExecutionPlanIntentInput) -> str | None:
    if not intent_input.market_id.strip():
        return "market_id_required"
    if not intent_input.outcome.strip():
        return "outcome_required"
    if intent_input.side not in _ALLOWED_SIDES:
        return "side_not_allowed"
    if intent_input.routing_mode not in _ALLOWED_ROUTING_MODES:
        return "routing_mode_not_allowed"
    if intent_input.size < 0:
        return "size_must_be_non_negative"
    if intent_input.limit_price_hint is not None and intent_input.limit_price_hint < 0:
        return "limit_price_hint_must_be_non_negative"
    return None


def _validate_market_context_input(
    market_context_input: ExecutionPlanMarketContextInput,
) -> str | None:
    if not market_context_input.market_id.strip():
        return "market_id_required"
    if not market_context_input.outcome.strip():
        return "outcome_required"
    if not market_context_input.execution_mode_label.strip():
        return "execution_mode_label_required"
    if (
        market_context_input.slippage_bps_hint is not None
        and market_context_input.slippage_bps_hint < 0
    ):
        return "slippage_bps_hint_must_be_non_negative"
    if market_context_input.reference_price is not None and market_context_input.reference_price < 0:
        return "reference_price_must_be_non_negative"
    return None


def _derive_limit_price(
    intent_input: ExecutionPlanIntentInput,
    market_context_input: ExecutionPlanMarketContextInput,
) -> float | None:
    if intent_input.limit_price_hint is not None:
        return intent_input.limit_price_hint
    return market_context_input.reference_price


def _derive_slippage_bps(market_context_input: ExecutionPlanMarketContextInput) -> int | None:
    if market_context_input.slippage_bps_hint is not None:
        return market_context_input.slippage_bps_hint
    return 0


def _limit_price_source(
    intent_input: ExecutionPlanIntentInput,
    market_context_input: ExecutionPlanMarketContextInput,
) -> str:
    if intent_input.limit_price_hint is not None:
        return "intent_limit_price_hint"
    if market_context_input.reference_price is not None:
        return "market_context_reference_price"
    return "none"


def _blocked_invalid_contract_result(
    *,
    blocked_reason: str,
    contract_name: str,
    contract_input: Any,
) -> ExecutionPlanBuildResult:
    return ExecutionPlanBuildResult(
        plan=None,
        trace=ExecutionPlanTrace(
            plan_created=False,
            blocked_reason=blocked_reason,
            upstream_trace_refs={
                "contract_errors": {
                    contract_name: "invalid_contract_object",
                },
                "invalid_contract_input": {
                    contract_name: _describe_contract_input(contract_input),
                },
            },
            planning_notes={"contract_name": contract_name},
        ),
    )


def _describe_contract_input(contract_input: Any) -> dict[str, Any]:
    if contract_input is None:
        return {"type": "NoneType", "value": None}
    if isinstance(contract_input, dict):
        return {
            "type": "dict",
            "keys": sorted([str(key) for key in contract_input.keys()]),
        }
    return {
        "type": type(contract_input).__name__,
        "repr": repr(contract_input),
    }
