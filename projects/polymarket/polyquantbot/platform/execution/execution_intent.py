from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

INTENT_BLOCK_READINESS_FAILED = "readiness_failed"
INTENT_BLOCK_RISK_VALIDATION_FAILED = "risk_validation_failed"


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
    """Phase 3.2 deterministic, non-activating intent modeling builder."""

    def build_from_readiness(
        self,
        readiness_result: Any,
        routing_result: Any,
        signal: Any,
    ) -> ExecutionIntent | None:
        return self.build_with_trace(
            readiness_result=readiness_result,
            routing_result=routing_result,
            signal=signal,
        ).intent

    def build_with_trace(
        self,
        *,
        readiness_result: Any,
        routing_result: Any,
        signal: Any,
    ) -> ExecutionIntentBuildResult:
        readiness_can_execute = bool(_extract_field(readiness_result, "can_execute", False))
        readiness_block_reason = _extract_field(readiness_result, "block_reason", None)
        risk_decision = _extract_risk_decision(readiness_result)
        risk_validated = risk_decision == "ALLOW"

        upstream_trace_refs: dict[str, Any] = {
            "readiness": {
                "can_execute": readiness_can_execute,
                "block_reason": readiness_block_reason,
                "risk_validation_decision": risk_decision,
            },
            "routing": {
                "selected_mode": _extract_routing_mode(routing_result),
            },
            "signal": {
                "source_signal_id": _extract_field(signal, "source_signal_id", None),
            },
        }

        if not readiness_can_execute:
            return ExecutionIntentBuildResult(
                intent=None,
                trace=ExecutionIntentTrace(
                    intent_created=False,
                    blocked_reason=str(readiness_block_reason or INTENT_BLOCK_READINESS_FAILED),
                    upstream_trace_refs=upstream_trace_refs,
                ),
            )

        if not risk_validated:
            return ExecutionIntentBuildResult(
                intent=None,
                trace=ExecutionIntentTrace(
                    intent_created=False,
                    blocked_reason=INTENT_BLOCK_RISK_VALIDATION_FAILED,
                    upstream_trace_refs=upstream_trace_refs,
                ),
            )

        intent = ExecutionIntent(
            market_id=str(_extract_field(signal, "market_id", "")),
            outcome=str(_extract_field(signal, "outcome", "")),
            side=str(_extract_field(signal, "side", "BUY")),
            size=float(_extract_field(signal, "size", 0.0)),
            price=_coerce_optional_float(_extract_field(signal, "price", None)),
            confidence=_coerce_optional_float(_extract_field(signal, "confidence", None)),
            source_signal_id=_coerce_optional_str(_extract_field(signal, "source_signal_id", None)),
            routing_mode=_extract_routing_mode(routing_result),
            risk_validated=risk_validated,
            readiness_passed=readiness_can_execute,
        )

        return ExecutionIntentBuildResult(
            intent=intent,
            trace=ExecutionIntentTrace(
                intent_created=True,
                blocked_reason=None,
                upstream_trace_refs=upstream_trace_refs,
            ),
        )


def _extract_field(source: Any, key: str, default: Any) -> Any:
    if source is None:
        return default
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _extract_routing_mode(routing_result: Any) -> str:
    return str(
        _extract_field(routing_result, "selected_mode", None)
        or _extract_field(routing_result, "routing_mode", None)
        or "unknown"
    )


def _extract_risk_decision(readiness_result: Any) -> str | None:
    readiness_checks = _extract_field(readiness_result, "readiness_checks", None)
    if isinstance(readiness_checks, dict):
        decision = readiness_checks.get("risk_validation_decision")
        if decision is None:
            return None
        return str(decision)
    return None


def _coerce_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _coerce_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
