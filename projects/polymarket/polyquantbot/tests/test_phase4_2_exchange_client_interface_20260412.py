from __future__ import annotations

from dataclasses import fields, replace

from projects.polymarket.polyquantbot.platform.execution.exchange_client_interface import (
    EXCHANGE_CLIENT_BLOCK_INVALID_ORDER_CONTRACT,
    EXCHANGE_CLIENT_BLOCK_INVALID_ORDER_INPUT,
    EXCHANGE_CLIENT_BLOCK_NON_EXECUTING_REQUIRED,
    SIMULATED_STATUS_ACCEPTED,
    SIMULATED_TRANSPORT_MODE,
    ExchangeClientInterface,
    ExchangeClientOrderInput,
    ExchangeRequest,
)
from projects.polymarket.polyquantbot.platform.execution.execution_adapter import ExecutionOrderSpec

VALID_ORDER = ExecutionOrderSpec(
    market_id="MKT-4-2",
    outcome="YES",
    side="YES",
    size=7.25,
    order_type="LIMIT",
    limit_price=0.52,
    slippage_bps=30,
    routing_mode="platform-gateway-shadow",
    execution_mode="LIMIT",
    external_symbol="MKT-4-2::YES",
    external_side="BUY",
    external_order_type="LIMIT",
    non_executing=True,
)

VALID_INPUT = ExchangeClientOrderInput(
    order=VALID_ORDER,
    source_trace_refs={"adapter_trace_id": "ADP-4-2"},
)


def test_phase4_2_valid_order_spec_produces_request_and_mocked_response() -> None:
    client = ExchangeClientInterface()

    result = client.build_request_with_trace(order_input=VALID_INPUT)
    response = client.build_mock_response(result.request)

    assert result.request is not None
    assert result.trace.request_created is True
    assert result.trace.blocked_reason is None
    assert result.request.transport_mode == SIMULATED_TRANSPORT_MODE
    assert response.accepted is True
    assert response.status == SIMULATED_STATUS_ACCEPTED
    assert response.simulated is True
    assert response.non_executing is True


def test_phase4_2_invalid_order_contract_blocked_deterministically() -> None:
    client = ExchangeClientInterface()

    result = client.build_request_with_trace(
        order_input=ExchangeClientOrderInput(
            order=None,  # type: ignore[arg-type]
        )
    )

    assert result.request is None
    assert result.trace.request_created is False
    assert result.trace.blocked_reason == EXCHANGE_CLIENT_BLOCK_INVALID_ORDER_CONTRACT


def test_phase4_2_invalid_top_level_input_blocked_deterministically() -> None:
    client = ExchangeClientInterface()

    result = client.build_request_with_trace(order_input=None)  # type: ignore[arg-type]

    assert result.request is None
    assert result.trace.request_created is False
    assert result.trace.blocked_reason == EXCHANGE_CLIENT_BLOCK_INVALID_ORDER_INPUT


def test_phase4_2_non_executing_false_blocked() -> None:
    client = ExchangeClientInterface()

    result = client.build_request_with_trace(
        order_input=ExchangeClientOrderInput(order=replace(VALID_ORDER, non_executing=False))
    )

    assert result.request is None
    assert result.trace.request_created is False
    assert result.trace.blocked_reason == EXCHANGE_CLIENT_BLOCK_NON_EXECUTING_REQUIRED


def test_phase4_2_deterministic_client_order_id() -> None:
    client = ExchangeClientInterface()

    first = client.build_request_with_trace(order_input=VALID_INPUT)
    second = client.build_request_with_trace(order_input=VALID_INPUT)

    assert first.request is not None
    assert second.request is not None
    assert first.request.client_order_id == second.request.client_order_id


def test_phase4_2_deterministic_request_equality() -> None:
    client = ExchangeClientInterface()

    first = client.build_request_with_trace(order_input=VALID_INPUT)
    second = client.build_request_with_trace(order_input=VALID_INPUT)

    assert first == second


def test_phase4_2_correct_field_mapping() -> None:
    client = ExchangeClientInterface()

    result = client.build_request_with_trace(order_input=VALID_INPUT)

    assert result.request is not None
    assert result.request.external_symbol == VALID_ORDER.external_symbol
    assert result.request.side == VALID_ORDER.external_side
    assert result.request.order_type == VALID_ORDER.external_order_type
    assert result.request.size == float(VALID_ORDER.size)
    assert result.request.limit_price == float(VALID_ORDER.limit_price)
    assert result.request.slippage_bps == VALID_ORDER.slippage_bps


def test_phase4_2_no_network_api_fields_introduced() -> None:
    field_names = {item.name for item in fields(ExchangeRequest)}

    assert "api_key" not in field_names
    assert "private_key" not in field_names
    assert "wallet_address" not in field_names
    assert "signature" not in field_names
    assert "http_client" not in field_names
    assert "sdk_client" not in field_names


def test_phase4_2_none_dict_wrong_object_inputs_do_not_crash() -> None:
    client = ExchangeClientInterface()

    none_input_result = client.build_request_with_trace(order_input=None)  # type: ignore[arg-type]
    assert none_input_result.trace.blocked_reason == EXCHANGE_CLIENT_BLOCK_INVALID_ORDER_INPUT

    dict_input_result = client.build_request_with_trace(
        order_input={"order": VALID_ORDER},  # type: ignore[arg-type]
    )
    assert dict_input_result.trace.blocked_reason == EXCHANGE_CLIENT_BLOCK_INVALID_ORDER_INPUT

    wrong_inner_result = client.build_request_with_trace(
        order_input=ExchangeClientOrderInput(
            order=object(),  # type: ignore[arg-type]
        )
    )
    assert wrong_inner_result.trace.blocked_reason == EXCHANGE_CLIENT_BLOCK_INVALID_ORDER_CONTRACT
