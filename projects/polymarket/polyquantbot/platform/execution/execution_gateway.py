from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .exchange_client_interface import (
    EXCHANGE_CLIENT_BLOCK_INVALID_ORDER_CONTRACT,
    EXCHANGE_CLIENT_BLOCK_INVALID_ORDER_INPUT,
    ExchangeClientInterface,
    ExchangeClientOrderInput,
)
from .execution_adapter import (
    ADAPTER_BLOCK_INVALID_DECISION_CONTRACT,
    ADAPTER_BLOCK_INVALID_DECISION_INPUT,
    ExecutionAdapter,
    ExecutionAdapterDecisionInput,
)
from .execution_decision import ExecutionDecision

GATEWAY_BLOCK_INVALID_GATEWAY_INPUT = "invalid_gateway_input"
GATEWAY_BLOCK_INVALID_DECISION_CONTRACT = "invalid_decision_contract"
GATEWAY_BLOCK_ADAPTER_BLOCKED = "adapter_blocked"
GATEWAY_BLOCK_EXCHANGE_INTERFACE_BLOCKED = "exchange_interface_blocked"
GATEWAY_BLOCK_MOCK_RESPONSE_REJECTED = "mock_response_rejected"

GATEWAY_EXECUTION_STATUS_ACCEPTED = "SIMULATED_EXECUTION_ACCEPTED"
GATEWAY_EXECUTION_STATUS_BLOCKED = "SIMULATED_EXECUTION_BLOCKED"
GATEWAY_EXECUTION_STATUS_REJECTED = "SIMULATED_EXECUTION_REJECTED"


@dataclass(frozen=True)
class ExecutionGatewayDecisionInput:
    decision: ExecutionDecision
    source_trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionGatewayResult:
    accepted: bool
    blocked_reason: str | None
    execution_status: str
    request_built: bool
    response_status: str
    client_order_id: str | None
    simulated: bool
    non_executing: bool


@dataclass(frozen=True)
class ExecutionGatewayTrace:
    gateway_completed: bool
    blocked_reason: str | None
    upstream_trace_refs: dict[str, Any] = field(default_factory=dict)
    gateway_notes: dict[str, Any] | None = None


@dataclass(frozen=True)
class ExecutionGatewayBuildResult:
    result: ExecutionGatewayResult | None
    trace: ExecutionGatewayTrace


class ExecutionGateway:
    """Phase 4.3 deterministic orchestration gateway (non-executing)."""

    def __init__(
        self,
        *,
        adapter: ExecutionAdapter | None = None,
        exchange_client: ExchangeClientInterface | None = None,
    ) -> None:
        self._adapter = adapter or ExecutionAdapter()
        self._exchange_client = exchange_client or ExchangeClientInterface()

    def simulate_execution(
        self,
        decision_input: ExecutionGatewayDecisionInput,
    ) -> ExecutionGatewayResult | None:
        return self.simulate_execution_with_trace(decision_input=decision_input).result

    def simulate_execution_with_trace(
        self,
        *,
        decision_input: ExecutionGatewayDecisionInput,
    ) -> ExecutionGatewayBuildResult:
        if not isinstance(decision_input, ExecutionGatewayDecisionInput):
            return _blocked_build_result(
                blocked_reason=GATEWAY_BLOCK_INVALID_GATEWAY_INPUT,
                upstream_trace_refs={
                    "contract_errors": {
                        "decision_input": {
                            "expected_type": "ExecutionGatewayDecisionInput",
                            "actual_type": type(decision_input).__name__,
                        }
                    }
                },
                gateway_notes={"contract_name": "decision_input"},
            )

        decision_error = _validate_decision_contract(decision_input.decision)
        if decision_error is not None:
            return _blocked_build_result(
                blocked_reason=GATEWAY_BLOCK_INVALID_DECISION_CONTRACT,
                upstream_trace_refs={
                    "gateway_input": dict(decision_input.source_trace_refs),
                    "contract_errors": {"decision": decision_error},
                },
                gateway_notes={"decision_error": decision_error},
            )

        adapter_result = self._adapter.build_order_with_trace(
            decision_input=ExecutionAdapterDecisionInput(
                decision=decision_input.decision,
                source_trace_refs={"gateway_input": dict(decision_input.source_trace_refs)},
            )
        )

        if adapter_result.order is None:
            return _blocked_build_result(
                blocked_reason=GATEWAY_BLOCK_ADAPTER_BLOCKED,
                upstream_trace_refs={
                    "gateway_input": dict(decision_input.source_trace_refs),
                    "adapter_trace": adapter_result.trace.upstream_trace_refs,
                },
                gateway_notes={
                    "adapter_blocked_reason": adapter_result.trace.blocked_reason,
                },
            )

        interface_result = self._exchange_client.build_request_with_trace(
            order_input=ExchangeClientOrderInput(
                order=adapter_result.order,
                source_trace_refs={
                    "gateway_input": dict(decision_input.source_trace_refs),
                    "adapter_trace": dict(adapter_result.trace.upstream_trace_refs),
                },
            )
        )

        if interface_result.request is None:
            return _blocked_build_result(
                blocked_reason=GATEWAY_BLOCK_EXCHANGE_INTERFACE_BLOCKED,
                upstream_trace_refs={
                    "gateway_input": dict(decision_input.source_trace_refs),
                    "adapter_trace": adapter_result.trace.upstream_trace_refs,
                    "exchange_trace": interface_result.trace.upstream_trace_refs,
                },
                gateway_notes={
                    "exchange_interface_blocked_reason": interface_result.trace.blocked_reason,
                },
            )

        response = self._exchange_client.build_mock_response(interface_result.request)
        if not response.accepted:
            return _blocked_build_result(
                blocked_reason=GATEWAY_BLOCK_MOCK_RESPONSE_REJECTED,
                upstream_trace_refs={
                    "gateway_input": dict(decision_input.source_trace_refs),
                    "adapter_trace": adapter_result.trace.upstream_trace_refs,
                    "exchange_trace": interface_result.trace.upstream_trace_refs,
                },
                gateway_notes={
                    "response_code": response.response_code,
                    "response_status": response.status,
                },
                client_order_id=interface_result.request.client_order_id,
                response_status=response.status,
                request_built=True,
                execution_status=GATEWAY_EXECUTION_STATUS_REJECTED,
            )

        result = ExecutionGatewayResult(
            accepted=True,
            blocked_reason=None,
            execution_status=GATEWAY_EXECUTION_STATUS_ACCEPTED,
            request_built=True,
            response_status=response.status,
            client_order_id=interface_result.request.client_order_id,
            simulated=True,
            non_executing=True,
        )
        return ExecutionGatewayBuildResult(
            result=result,
            trace=ExecutionGatewayTrace(
                gateway_completed=True,
                blocked_reason=None,
                upstream_trace_refs={
                    "gateway_input": dict(decision_input.source_trace_refs),
                    "adapter_trace": adapter_result.trace.upstream_trace_refs,
                    "exchange_trace": interface_result.trace.upstream_trace_refs,
                },
                gateway_notes={
                    "adapter_blocked_reason": None,
                    "exchange_interface_blocked_reason": None,
                    "response_code": response.response_code,
                    "response_status": response.status,
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
    return None


def _blocked_build_result(
    *,
    blocked_reason: str,
    upstream_trace_refs: dict[str, Any],
    gateway_notes: dict[str, Any] | None,
    request_built: bool = False,
    response_status: str = "NOT_BUILT",
    client_order_id: str | None = None,
    execution_status: str = GATEWAY_EXECUTION_STATUS_BLOCKED,
) -> ExecutionGatewayBuildResult:
    return ExecutionGatewayBuildResult(
        result=ExecutionGatewayResult(
            accepted=False,
            blocked_reason=blocked_reason,
            execution_status=execution_status,
            request_built=request_built,
            response_status=response_status,
            client_order_id=client_order_id,
            simulated=True,
            non_executing=True,
        ),
        trace=ExecutionGatewayTrace(
            gateway_completed=False,
            blocked_reason=blocked_reason,
            upstream_trace_refs=upstream_trace_refs,
            gateway_notes=gateway_notes,
        ),
    )
