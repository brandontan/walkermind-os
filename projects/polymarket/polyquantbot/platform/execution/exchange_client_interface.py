from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Any

from .execution_adapter import ExecutionOrderSpec

EXCHANGE_CLIENT_BLOCK_INVALID_ORDER_INPUT = "invalid_order_input"
EXCHANGE_CLIENT_BLOCK_INVALID_ORDER_CONTRACT = "invalid_order_contract"
EXCHANGE_CLIENT_BLOCK_NON_EXECUTING_REQUIRED = "non_executing_required"
EXCHANGE_CLIENT_BLOCK_INVALID_TRANSPORT_FIELD = "invalid_transport_field"

SIMULATED_TRANSPORT_MODE = "SIMULATED_TRANSPORT"
SIMULATED_STATUS_ACCEPTED = "SIMULATED_ACCEPTED"
SIMULATED_STATUS_REJECTED = "SIMULATED_REJECTED"


@dataclass(frozen=True)
class ExchangeClientOrderInput:
    order: ExecutionOrderSpec
    source_trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExchangeRequest:
    external_symbol: str
    side: str
    order_type: str
    size: float
    limit_price: float | None
    slippage_bps: int | None
    client_order_id: str
    transport_mode: str
    non_executing: bool


@dataclass(frozen=True)
class ExchangeResponse:
    status: str
    accepted: bool
    response_code: str
    response_message: str
    simulated: bool
    non_executing: bool


@dataclass(frozen=True)
class ExchangeRequestTrace:
    request_created: bool
    blocked_reason: str | None
    upstream_trace_refs: dict[str, Any] = field(default_factory=dict)
    transport_notes: dict[str, Any] | None = None


@dataclass(frozen=True)
class ExchangeRequestBuildResult:
    request: ExchangeRequest | None
    trace: ExchangeRequestTrace


class ExchangeClientInterface:
    """Phase 4.2 deterministic exchange transport boundary (non-executing, non-network)."""

    def build_request(self, order_input: ExchangeClientOrderInput) -> ExchangeRequest | None:
        return self.build_request_with_trace(order_input=order_input).request

    def build_request_with_trace(
        self,
        *,
        order_input: ExchangeClientOrderInput,
    ) -> ExchangeRequestBuildResult:
        if not isinstance(order_input, ExchangeClientOrderInput):
            return _blocked_result(
                blocked_reason=EXCHANGE_CLIENT_BLOCK_INVALID_ORDER_INPUT,
                upstream_trace_refs={
                    "contract_errors": {
                        "order_input": {
                            "expected_type": "ExchangeClientOrderInput",
                            "actual_type": type(order_input).__name__,
                        }
                    }
                },
                transport_notes={"contract_name": "order_input"},
            )

        order_error = _validate_order(order_input.order)
        if order_error is not None:
            blocked_reason = EXCHANGE_CLIENT_BLOCK_INVALID_ORDER_CONTRACT
            if order_error == "non_executing_required":
                blocked_reason = EXCHANGE_CLIENT_BLOCK_NON_EXECUTING_REQUIRED
            elif order_error.startswith("transport_field_"):
                blocked_reason = EXCHANGE_CLIENT_BLOCK_INVALID_TRANSPORT_FIELD

            return _blocked_result(
                blocked_reason=blocked_reason,
                upstream_trace_refs={
                    "order_input": dict(order_input.source_trace_refs),
                    "contract_errors": {"order": order_error},
                },
                transport_notes={"order_error": order_error},
            )

        order = order_input.order
        request = ExchangeRequest(
            external_symbol=order.external_symbol,
            side=order.external_side,
            order_type=order.external_order_type,
            size=float(order.size),
            limit_price=float(order.limit_price) if isinstance(order.limit_price, (int, float)) else None,
            slippage_bps=int(order.slippage_bps) if isinstance(order.slippage_bps, int) else None,
            client_order_id=_build_deterministic_client_order_id(order),
            transport_mode=SIMULATED_TRANSPORT_MODE,
            non_executing=True,
        )

        return ExchangeRequestBuildResult(
            request=request,
            trace=ExchangeRequestTrace(
                request_created=True,
                blocked_reason=None,
                upstream_trace_refs={"order_input": dict(order_input.source_trace_refs)},
                transport_notes={
                    "mapping": {
                        "ExecutionOrderSpec.external_side": "ExchangeRequest.side",
                        "ExecutionOrderSpec.external_order_type": "ExchangeRequest.order_type",
                        "ExecutionOrderSpec.external_symbol": "ExchangeRequest.external_symbol",
                    },
                    "transport_mode": SIMULATED_TRANSPORT_MODE,
                    "external_effects": "none",
                },
            ),
        )

    def build_mock_response(self, request: ExchangeRequest | None) -> ExchangeResponse:
        if request is None:
            return ExchangeResponse(
                status=SIMULATED_STATUS_REJECTED,
                accepted=False,
                response_code="REQUEST_MISSING",
                response_message="Request is required for simulated response.",
                simulated=True,
                non_executing=True,
            )

        is_valid = _validate_request(request)
        if is_valid:
            return ExchangeResponse(
                status=SIMULATED_STATUS_ACCEPTED,
                accepted=True,
                response_code="SIM_OK",
                response_message="Request accepted in simulated transport mode.",
                simulated=True,
                non_executing=True,
            )

        return ExchangeResponse(
            status=SIMULATED_STATUS_REJECTED,
            accepted=False,
            response_code="SIM_INVALID_REQUEST",
            response_message="Request failed simulated transport validation.",
            simulated=True,
            non_executing=True,
        )


def _build_deterministic_client_order_id(order: ExecutionOrderSpec) -> str:
    stable_payload = "|".join(
        [
            order.market_id,
            order.outcome,
            order.external_symbol,
            order.external_side,
            order.external_order_type,
            f"{float(order.size):.8f}",
            "none" if order.limit_price is None else f"{float(order.limit_price):.8f}",
            "none" if order.slippage_bps is None else str(int(order.slippage_bps)),
            order.routing_mode,
            order.execution_mode,
            str(order.non_executing),
        ]
    )
    digest = hashlib.sha256(stable_payload.encode("utf-8")).hexdigest()[:20]
    return f"SIM-{digest}"


def _validate_order(order: ExecutionOrderSpec) -> str | None:
    if not isinstance(order, ExecutionOrderSpec):
        return "order_contract_required"
    if order.non_executing is not True:
        return "non_executing_required"
    if not isinstance(order.external_symbol, str) or not order.external_symbol.strip():
        return "transport_field_external_symbol_invalid"
    if not isinstance(order.external_side, str) or not order.external_side.strip():
        return "transport_field_external_side_invalid"
    if not isinstance(order.external_order_type, str) or not order.external_order_type.strip():
        return "transport_field_external_order_type_invalid"
    if not isinstance(order.size, (int, float)) or float(order.size) < 0:
        return "transport_field_size_invalid"
    if order.limit_price is not None and (
        not isinstance(order.limit_price, (int, float)) or float(order.limit_price) < 0
    ):
        return "transport_field_limit_price_invalid"
    if order.slippage_bps is not None and (
        not isinstance(order.slippage_bps, int) or order.slippage_bps < 0
    ):
        return "transport_field_slippage_bps_invalid"
    return None


def _validate_request(request: ExchangeRequest) -> bool:
    return (
        isinstance(request.external_symbol, str)
        and bool(request.external_symbol.strip())
        and isinstance(request.side, str)
        and bool(request.side.strip())
        and isinstance(request.order_type, str)
        and bool(request.order_type.strip())
        and isinstance(request.size, float)
        and request.size >= 0
        and (request.limit_price is None or (isinstance(request.limit_price, float) and request.limit_price >= 0))
        and (request.slippage_bps is None or (isinstance(request.slippage_bps, int) and request.slippage_bps >= 0))
        and isinstance(request.client_order_id, str)
        and bool(request.client_order_id.strip())
        and request.transport_mode == SIMULATED_TRANSPORT_MODE
        and request.non_executing is True
    )


def _blocked_result(
    *,
    blocked_reason: str,
    upstream_trace_refs: dict[str, Any],
    transport_notes: dict[str, Any] | None,
) -> ExchangeRequestBuildResult:
    return ExchangeRequestBuildResult(
        request=None,
        trace=ExchangeRequestTrace(
            request_created=False,
            blocked_reason=blocked_reason,
            upstream_trace_refs=upstream_trace_refs,
            transport_notes=transport_notes,
        ),
    )
