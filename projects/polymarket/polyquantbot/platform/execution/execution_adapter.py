from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .execution_decision import ExecutionDecision
from .monitoring_circuit_breaker import (
    MONITORING_DECISION_BLOCK,
    MONITORING_DECISION_HALT,
    MonitoringCircuitBreaker,
    MonitoringContractInput,
)

ADAPTER_BLOCK_INVALID_DECISION_INPUT = "invalid_decision_input"
ADAPTER_BLOCK_INVALID_DECISION_CONTRACT = "invalid_decision_contract"
ADAPTER_BLOCK_UPSTREAM_NOT_ALLOWED = "upstream_not_allowed"
ADAPTER_BLOCK_DECISION_NOT_READY = "decision_not_ready"
ADAPTER_BLOCK_NON_ACTIVATING_REQUIRED = "non_activating_required"
ADAPTER_BLOCK_MONITORING_EVALUATION_REQUIRED = "monitoring_evaluation_required"
ADAPTER_BLOCK_MONITORING_ANOMALY = "monitoring_anomaly_block"
ADAPTER_HALT_MONITORING_ANOMALY = "monitoring_anomaly_halt"


_SIDE_TO_EXTERNAL_SIDE: dict[str, str] = {
    "BUY": "BUY",
    "SELL": "SELL",
    "YES": "BUY",
    "NO": "SELL",
}

_ROUTING_MODE_TO_EXECUTION_MODE: dict[str, str] = {
    "platform-gateway-shadow": "LIMIT",
    "platform-gateway-primary": "LIMIT",
    "legacy-only": "MARKET",
    "disabled": "MARKET",
}


@dataclass(frozen=True)
class ExecutionAdapterDecisionInput:
    decision: ExecutionDecision
    monitoring_input: MonitoringContractInput | None = None
    monitoring_circuit_breaker: MonitoringCircuitBreaker | None = None
    monitoring_required: bool = False
    source_trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionOrderSpec:
    market_id: str
    outcome: str
    side: str
    size: float
    order_type: str
    limit_price: float | None
    slippage_bps: int | None
    routing_mode: str
    execution_mode: str
    external_symbol: str
    external_side: str
    external_order_type: str
    non_executing: bool


@dataclass(frozen=True)
class ExecutionOrderTrace:
    order_created: bool
    blocked_reason: str | None
    upstream_trace_refs: dict[str, Any] = field(default_factory=dict)
    mapping_notes: dict[str, Any] | None = None


@dataclass(frozen=True)
class ExecutionOrderBuildResult:
    order: ExecutionOrderSpec | None
    trace: ExecutionOrderTrace


class ExecutionAdapter:
    """Phase 4.1 deterministic adapter from internal decision to external-order-ready spec."""

    def build_order(self, decision_input: ExecutionAdapterDecisionInput) -> ExecutionOrderSpec | None:
        return self.build_order_with_trace(decision_input=decision_input).order

    def build_order_with_trace(
        self,
        *,
        decision_input: ExecutionAdapterDecisionInput,
    ) -> ExecutionOrderBuildResult:
        if not isinstance(decision_input, ExecutionAdapterDecisionInput):
            return _blocked_result(
                blocked_reason=ADAPTER_BLOCK_INVALID_DECISION_INPUT,
                upstream_trace_refs={
                    "contract_errors": {
                        "decision_input": {
                            "expected_type": "ExecutionAdapterDecisionInput",
                            "actual_type": type(decision_input).__name__,
                        }
                    }
                },
                mapping_notes={"contract_name": "decision_input"},
            )

        decision_error = _validate_decision(decision_input.decision)
        if decision_error is not None:
            return _blocked_result(
                blocked_reason=ADAPTER_BLOCK_INVALID_DECISION_CONTRACT,
                upstream_trace_refs={
                    "decision_input": dict(decision_input.source_trace_refs),
                    "contract_errors": {"decision": decision_error},
                },
                mapping_notes={"decision_error": decision_error},
            )

        decision = decision_input.decision
        monitoring_trace: dict[str, Any] | None = None
        if decision_input.monitoring_required:
            if not isinstance(decision_input.monitoring_input, MonitoringContractInput):
                return _blocked_result(
                    blocked_reason=ADAPTER_BLOCK_MONITORING_EVALUATION_REQUIRED,
                    upstream_trace_refs={"decision_input": dict(decision_input.source_trace_refs)},
                    mapping_notes={
                        "monitoring_required": True,
                        "contract_errors": {
                            "monitoring_input": {
                                "expected_type": "MonitoringContractInput",
                                "actual_type": type(decision_input.monitoring_input).__name__,
                            }
                        },
                    },
                )

            if decision_input.monitoring_circuit_breaker is not None and not isinstance(
                decision_input.monitoring_circuit_breaker,
                MonitoringCircuitBreaker,
            ):
                return _blocked_result(
                    blocked_reason=ADAPTER_BLOCK_MONITORING_EVALUATION_REQUIRED,
                    upstream_trace_refs={"decision_input": dict(decision_input.source_trace_refs)},
                    mapping_notes={
                        "monitoring_required": True,
                        "contract_errors": {
                            "monitoring_circuit_breaker": {
                                "expected_type": "MonitoringCircuitBreaker",
                                "actual_type": type(decision_input.monitoring_circuit_breaker).__name__,
                            }
                        },
                    },
                )

            breaker = decision_input.monitoring_circuit_breaker or MonitoringCircuitBreaker()
            monitoring_result = breaker.evaluate(decision_input.monitoring_input)
            monitoring_trace = {
                "decision": monitoring_result.decision,
                "anomaly_count": len(monitoring_result.anomalies),
                "primary_anomaly": (
                    monitoring_result.anomalies[0] if monitoring_result.anomalies else None
                ),
            }

            if monitoring_result.decision == MONITORING_DECISION_HALT:
                return _blocked_result(
                    blocked_reason=ADAPTER_HALT_MONITORING_ANOMALY,
                    upstream_trace_refs={
                        "decision_input": dict(decision_input.source_trace_refs),
                        "monitoring": monitoring_trace,
                    },
                    mapping_notes={"monitoring_required": True},
                )
            if monitoring_result.decision == MONITORING_DECISION_BLOCK:
                return _blocked_result(
                    blocked_reason=ADAPTER_BLOCK_MONITORING_ANOMALY,
                    upstream_trace_refs={
                        "decision_input": dict(decision_input.source_trace_refs),
                        "monitoring": monitoring_trace,
                    },
                    mapping_notes={"monitoring_required": True},
                )

        if not decision.allowed:
            return _blocked_result(
                blocked_reason=ADAPTER_BLOCK_UPSTREAM_NOT_ALLOWED,
                upstream_trace_refs={"decision_input": dict(decision_input.source_trace_refs)},
                mapping_notes={"upstream_blocked_reason": decision.blocked_reason},
            )

        if not decision.ready_for_execution:
            return _blocked_result(
                blocked_reason=ADAPTER_BLOCK_DECISION_NOT_READY,
                upstream_trace_refs={"decision_input": dict(decision_input.source_trace_refs)},
                mapping_notes={"ready_for_execution": decision.ready_for_execution},
            )

        if decision.non_activating is not True:
            return _blocked_result(
                blocked_reason=ADAPTER_BLOCK_NON_ACTIVATING_REQUIRED,
                upstream_trace_refs={"decision_input": dict(decision_input.source_trace_refs)},
                mapping_notes={"non_activating": decision.non_activating},
            )

        external_side = _SIDE_TO_EXTERNAL_SIDE[decision.side]
        mapped_execution_mode = _ROUTING_MODE_TO_EXECUTION_MODE[decision.routing_mode]
        external_symbol = _build_external_symbol(decision.market_id, decision.outcome)

        order = ExecutionOrderSpec(
            market_id=decision.market_id,
            outcome=decision.outcome,
            side=decision.side,
            size=decision.size,
            order_type=mapped_execution_mode,
            limit_price=None,
            slippage_bps=None,
            routing_mode=decision.routing_mode,
            execution_mode=mapped_execution_mode,
            external_symbol=external_symbol,
            external_side=external_side,
            external_order_type=mapped_execution_mode,
            non_executing=True,
        )

        return ExecutionOrderBuildResult(
            order=order,
            trace=ExecutionOrderTrace(
                order_created=True,
                blocked_reason=None,
                upstream_trace_refs={
                    "decision_input": dict(decision_input.source_trace_refs),
                    **({"monitoring": monitoring_trace} if monitoring_trace is not None else {}),
                },
                mapping_notes={
                    "side_to_external_side": {decision.side: external_side},
                    "routing_mode_to_execution_mode": {decision.routing_mode: mapped_execution_mode},
                    "symbol_mapping": {
                        "market_id": decision.market_id,
                        "outcome": decision.outcome,
                        "external_symbol": external_symbol,
                    },
                    "non_executing_enforced": True,
                    "external_effects": "none",
                },
            ),
        )


def _validate_decision(decision: ExecutionDecision) -> str | None:
    if not isinstance(decision, ExecutionDecision):
        return "decision_contract_required"
    if not isinstance(decision.allowed, bool):
        return "allowed_must_be_bool"
    if not isinstance(decision.ready_for_execution, bool):
        return "ready_for_execution_must_be_bool"
    if not isinstance(decision.non_activating, bool):
        return "non_activating_must_be_bool"
    if not isinstance(decision.market_id, str) or not decision.market_id.strip():
        return "market_id_required"
    if not isinstance(decision.outcome, str) or not decision.outcome.strip():
        return "outcome_required"
    if not isinstance(decision.side, str) or decision.side not in _SIDE_TO_EXTERNAL_SIDE:
        return "side_invalid"
    if not isinstance(decision.routing_mode, str) or decision.routing_mode not in _ROUTING_MODE_TO_EXECUTION_MODE:
        return "routing_mode_invalid"
    if not isinstance(decision.size, (int, float)) or decision.size < 0:
        return "size_must_be_non_negative"
    return None


def _build_external_symbol(market_id: str, outcome: str) -> str:
    return f"{market_id}::{outcome.upper()}"


def _blocked_result(
    *,
    blocked_reason: str,
    upstream_trace_refs: dict[str, Any],
    mapping_notes: dict[str, Any] | None,
) -> ExecutionOrderBuildResult:
    return ExecutionOrderBuildResult(
        order=None,
        trace=ExecutionOrderTrace(
            order_created=False,
            blocked_reason=blocked_reason,
            upstream_trace_refs=upstream_trace_refs,
            mapping_notes=mapping_notes,
        ),
    )
