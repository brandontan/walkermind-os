from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

INTENT_BLOCK_READINESS_FAILED = "readiness_failed"
INTENT_BLOCK_RISK_VALIDATION_FAILED = "risk_validation_failed"
INTENT_BLOCK_INVALID_ROUTING_CONTRACT = "invalid_routing_contract"
INTENT_BLOCK_INVALID_SIGNAL_CONTRACT = "invalid_signal_contract"

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
class ExecutionIntentSignalInput:
    market_id: str
    outcome: str
    side: str
    size: float
    price: float | None
    confidence: float | None
    source_signal_id: str | None


@dataclass(frozen=True)
class ExecutionIntentRoutingInput:
    routing_mode: str


@dataclass(frozen=True)
class ExecutionIntentReadinessInput:
    can_execute: bool
    block_reason: str | None
    risk_validation_decision: str | None


@dataclass(frozen=True)
class ExecutionIntent:
    market_id: str
    outcome: str
    side: str
    size: float
    price: float | None
    confidence: float | None
    source_signal_id: str | None
    routing_mode: str
    risk_validated: bool
    readiness_passed: bool


@dataclass(frozen=True)
class ExecutionIntentTrace:
    intent_created: bool
    blocked_reason: str | None
    upstream_trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionIntentBuildResult:
    intent: ExecutionIntent | None
    trace: ExecutionIntentTrace


class ExecutionIntentBuilder:
    """Phase 3.3 deterministic, non-activating intent contract builder."""

    def build_from_readiness(
        self,
        readiness_input: ExecutionIntentReadinessInput,
        routing_input: ExecutionIntentRoutingInput,
        signal_input: ExecutionIntentSignalInput,
    ) -> ExecutionIntent | None:
        return self.build_with_trace(
            readiness_input=readiness_input,
            routing_input=routing_input,
            signal_input=signal_input,
        ).intent

    def build_with_trace(
        self,
        *,
        readiness_input: ExecutionIntentReadinessInput,
        routing_input: ExecutionIntentRoutingInput,
        signal_input: ExecutionIntentSignalInput,
    ) -> ExecutionIntentBuildResult:
        upstream_trace_refs: dict[str, Any] = {
            "readiness": {
                "can_execute": readiness_input.can_execute,
                "block_reason": readiness_input.block_reason,
                "risk_validation_decision": readiness_input.risk_validation_decision,
            },
            "routing": {
                "selected_mode": routing_input.routing_mode,
            },
            "signal": {
                "source_signal_id": signal_input.source_signal_id,
            },
        }

        if not readiness_input.can_execute:
            return ExecutionIntentBuildResult(
                intent=None,
                trace=ExecutionIntentTrace(
                    intent_created=False,
                    blocked_reason=str(readiness_input.block_reason or INTENT_BLOCK_READINESS_FAILED),
                    upstream_trace_refs=upstream_trace_refs,
                ),
            )

        if readiness_input.risk_validation_decision != "ALLOW":
            return ExecutionIntentBuildResult(
                intent=None,
                trace=ExecutionIntentTrace(
                    intent_created=False,
                    blocked_reason=INTENT_BLOCK_RISK_VALIDATION_FAILED,
                    upstream_trace_refs=upstream_trace_refs,
                ),
            )

        routing_error = _validate_routing_contract(routing_input)
        if routing_error is not None:
            return ExecutionIntentBuildResult(
                intent=None,
                trace=ExecutionIntentTrace(
                    intent_created=False,
                    blocked_reason=INTENT_BLOCK_INVALID_ROUTING_CONTRACT,
                    upstream_trace_refs={
                        **upstream_trace_refs,
                        "contract_errors": {"routing": routing_error},
                    },
                ),
            )

        signal_error = _validate_signal_contract(signal_input)
        if signal_error is not None:
            return ExecutionIntentBuildResult(
                intent=None,
                trace=ExecutionIntentTrace(
                    intent_created=False,
                    blocked_reason=INTENT_BLOCK_INVALID_SIGNAL_CONTRACT,
                    upstream_trace_refs={
                        **upstream_trace_refs,
                        "contract_errors": {"signal": signal_error},
                    },
                ),
            )

        intent = ExecutionIntent(
            market_id=signal_input.market_id,
            outcome=signal_input.outcome,
            side=signal_input.side,
            size=signal_input.size,
            price=signal_input.price,
            confidence=signal_input.confidence,
            source_signal_id=signal_input.source_signal_id,
            routing_mode=routing_input.routing_mode,
            risk_validated=True,
            readiness_passed=True,
        )

        return ExecutionIntentBuildResult(
            intent=intent,
            trace=ExecutionIntentTrace(
                intent_created=True,
                blocked_reason=None,
                upstream_trace_refs=upstream_trace_refs,
            ),
        )


def _validate_routing_contract(routing_input: ExecutionIntentRoutingInput) -> str | None:
    routing_mode = routing_input.routing_mode.strip()
    if not routing_mode:
        return "routing_mode_required"
    if routing_mode not in _ALLOWED_ROUTING_MODES:
        return "routing_mode_not_allowed"
    return None


def _validate_signal_contract(signal_input: ExecutionIntentSignalInput) -> str | None:
    if not signal_input.market_id.strip():
        return "market_id_required"
    if not signal_input.outcome.strip():
        return "outcome_required"
    if signal_input.side not in _ALLOWED_SIDES:
        return "side_not_allowed"
    if signal_input.size < 0:
        return "size_must_be_non_negative"
    return None
