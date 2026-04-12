from __future__ import annotations

from dataclasses import fields, replace

from projects.polymarket.polyquantbot.platform.execution.exchange_client_interface import (
    EXCHANGE_CLIENT_BLOCK_INVALID_TRANSPORT_FIELD,
    ExchangeClientInterface,
    ExchangeClientOrderInput,
    ExchangeRequestBuildResult,
    ExchangeRequestTrace,
    ExchangeResponse,
    SIMULATED_STATUS_REJECTED,
)
from projects.polymarket.polyquantbot.platform.execution.execution_adapter import ExecutionAdapter
from projects.polymarket.polyquantbot.platform.execution.execution_adapter import ExecutionAdapterDecisionInput
from projects.polymarket.polyquantbot.platform.execution.execution_decision import ExecutionDecision
from projects.polymarket.polyquantbot.platform.execution.execution_gateway import (
    GATEWAY_BLOCK_ADAPTER_BLOCKED,
    GATEWAY_BLOCK_EXCHANGE_INTERFACE_BLOCKED,
    GATEWAY_BLOCK_INVALID_DECISION_CONTRACT,
    GATEWAY_BLOCK_INVALID_GATEWAY_INPUT,
    GATEWAY_BLOCK_MOCK_RESPONSE_REJECTED,
    GATEWAY_EXECUTION_STATUS_ACCEPTED,
    GATEWAY_EXECUTION_STATUS_REJECTED,
    ExecutionGateway,
    ExecutionGatewayDecisionInput,
    ExecutionGatewayResult,
)

VALID_DECISION = ExecutionDecision(
    allowed=True,
    blocked_reason=None,
    market_id="MKT-4-3",
    outcome="YES",
    side="YES",
    size=9.5,
    routing_mode="platform-gateway-shadow",
    execution_mode="paper-prep-only",
    ready_for_execution=True,
    non_activating=True,
)

VALID_INPUT = ExecutionGatewayDecisionInput(
    decision=VALID_DECISION,
    source_trace_refs={"decision_trace_id": "DEC-4-3"},
)


def test_phase4_3_valid_decision_full_simulated_flow_accepted() -> None:
    gateway = ExecutionGateway()

    result = gateway.simulate_execution_with_trace(decision_input=VALID_INPUT)

    assert result.result is not None
    assert result.result.accepted is True
    assert result.result.blocked_reason is None
    assert result.result.execution_status == GATEWAY_EXECUTION_STATUS_ACCEPTED
    assert result.result.request_built is True
    assert result.result.simulated is True
    assert result.result.non_executing is True
    assert result.trace.gateway_completed is True


def test_phase4_3_invalid_gateway_input_blocked_deterministically() -> None:
    gateway = ExecutionGateway()

    result = gateway.simulate_execution_with_trace(decision_input=None)  # type: ignore[arg-type]

    assert result.result is not None
    assert result.result.accepted is False
    assert result.result.blocked_reason == GATEWAY_BLOCK_INVALID_GATEWAY_INPUT
    assert result.trace.blocked_reason == GATEWAY_BLOCK_INVALID_GATEWAY_INPUT


def test_phase4_3_invalid_decision_contract_blocked_deterministically() -> None:
    gateway = ExecutionGateway()

    result = gateway.simulate_execution_with_trace(
        decision_input=ExecutionGatewayDecisionInput(
            decision=None,  # type: ignore[arg-type]
        )
    )

    assert result.result is not None
    assert result.result.accepted is False
    assert result.result.blocked_reason == GATEWAY_BLOCK_INVALID_DECISION_CONTRACT
    assert result.trace.blocked_reason == GATEWAY_BLOCK_INVALID_DECISION_CONTRACT


def test_phase4_3_adapter_blocked_path_propagates_deterministically() -> None:
    gateway = ExecutionGateway()

    result = gateway.simulate_execution_with_trace(
        decision_input=ExecutionGatewayDecisionInput(
            decision=replace(VALID_DECISION, allowed=False, blocked_reason="risk_blocked")
        )
    )

    assert result.result is not None
    assert result.result.accepted is False
    assert result.result.blocked_reason == GATEWAY_BLOCK_ADAPTER_BLOCKED
    assert result.trace.gateway_notes is not None
    assert result.trace.gateway_notes["adapter_blocked_reason"] is not None


def test_phase4_3_exchange_interface_blocked_path_propagates_deterministically() -> None:
    class BlockingExchangeClient(ExchangeClientInterface):
        def build_request_with_trace(self, *, order_input):  # type: ignore[override]
            return ExchangeRequestBuildResult(
                request=None,
                trace=ExchangeRequestTrace(
                    request_created=False,
                    blocked_reason=EXCHANGE_CLIENT_BLOCK_INVALID_TRANSPORT_FIELD,
                    upstream_trace_refs={"forced_path": "exchange_interface_block"},
                    transport_notes={"forced": True},
                ),
            )

    gateway = ExecutionGateway(exchange_client=BlockingExchangeClient())

    result = gateway.simulate_execution_with_trace(
        decision_input=VALID_INPUT
    )

    assert result.result is not None
    assert result.result.accepted is False
    assert result.result.blocked_reason == GATEWAY_BLOCK_EXCHANGE_INTERFACE_BLOCKED
    assert result.trace.gateway_notes is not None
    assert result.trace.gateway_notes["exchange_interface_blocked_reason"] is not None


class RejectingExchangeClient(ExchangeClientInterface):
    def build_mock_response(self, request):  # type: ignore[override]
        return ExchangeResponse(
            status=SIMULATED_STATUS_REJECTED,
            accepted=False,
            response_code="SIM_FORCED_REJECT",
            response_message="Forced deterministic reject for gateway test.",
            simulated=True,
            non_executing=True,
        )


def test_phase4_3_mocked_response_rejected_path_propagates_deterministically() -> None:
    gateway = ExecutionGateway(exchange_client=RejectingExchangeClient())

    result = gateway.simulate_execution_with_trace(decision_input=VALID_INPUT)

    assert result.result is not None
    assert result.result.accepted is False
    assert result.result.blocked_reason == GATEWAY_BLOCK_MOCK_RESPONSE_REJECTED
    assert result.result.execution_status == GATEWAY_EXECUTION_STATUS_REJECTED
    assert result.trace.gateway_notes is not None
    assert result.trace.gateway_notes["response_code"] == "SIM_FORCED_REJECT"


def test_phase4_3_deterministic_equality_for_same_valid_input() -> None:
    gateway = ExecutionGateway()

    first = gateway.simulate_execution_with_trace(decision_input=VALID_INPUT)
    second = gateway.simulate_execution_with_trace(decision_input=VALID_INPUT)

    assert first == second


def test_phase4_3_deterministic_client_order_id_preserved_through_gateway() -> None:
    gateway = ExecutionGateway()
    adapter = ExecutionAdapter()
    exchange_client = ExchangeClientInterface()

    gateway_result = gateway.simulate_execution_with_trace(decision_input=VALID_INPUT)
    adapter_result = adapter.build_order_with_trace(
        decision_input=ExecutionAdapterDecisionInput(
            decision=VALID_DECISION,
            source_trace_refs=VALID_INPUT.source_trace_refs,
        )
    )
    assert adapter_result.order is not None
    request_result = exchange_client.build_request_with_trace(
        order_input=ExchangeClientOrderInput(order=adapter_result.order)
    )

    assert gateway_result.result is not None
    assert request_result.request is not None
    assert gateway_result.result.client_order_id == request_result.request.client_order_id


def test_phase4_3_no_network_api_wallet_signing_capital_fields_introduced() -> None:
    field_names = {item.name for item in fields(ExecutionGatewayResult)}

    assert "api_key" not in field_names
    assert "private_key" not in field_names
    assert "wallet_address" not in field_names
    assert "signature" not in field_names
    assert "network_client" not in field_names
    assert "capital_transfer" not in field_names


def test_phase4_3_none_dict_wrong_object_inputs_do_not_crash() -> None:
    gateway = ExecutionGateway()

    none_result = gateway.simulate_execution_with_trace(decision_input=None)  # type: ignore[arg-type]
    assert none_result.result is not None
    assert none_result.result.blocked_reason == GATEWAY_BLOCK_INVALID_GATEWAY_INPUT

    dict_result = gateway.simulate_execution_with_trace(
        decision_input={"decision": VALID_DECISION},  # type: ignore[arg-type]
    )
    assert dict_result.result is not None
    assert dict_result.result.blocked_reason == GATEWAY_BLOCK_INVALID_GATEWAY_INPUT

    wrong_inner_result = gateway.simulate_execution_with_trace(
        decision_input=ExecutionGatewayDecisionInput(
            decision=object(),  # type: ignore[arg-type]
        )
    )
    assert wrong_inner_result.result is not None
    assert wrong_inner_result.result.blocked_reason == GATEWAY_BLOCK_INVALID_DECISION_CONTRACT
