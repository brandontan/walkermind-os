from __future__ import annotations

from dataclasses import replace

from projects.polymarket.polyquantbot.platform.execution.exchange_integration import (
    EXCHANGE_EXECUTION_BLOCK_ENVIRONMENT_NOT_ALLOWED,
    EXCHANGE_EXECUTION_BLOCK_INVALID_ENDPOINT,
    EXCHANGE_EXECUTION_BLOCK_INVALID_POLICY_INPUT_CONTRACT,
    EXCHANGE_EXECUTION_BLOCK_INVALID_TRANSPORT_INPUT_CONTRACT,
    EXCHANGE_EXECUTION_BLOCK_NETWORK_DISABLED,
    EXCHANGE_EXECUTION_BLOCK_REAL_NETWORK_NOT_ALLOWED,
    EXCHANGE_EXECUTION_BLOCK_SIGNING_REQUIRED_MISSING,
    EXCHANGE_EXECUTION_BLOCK_SIMULATED_TRANSPORT,
    EXCHANGE_NETWORK_MODE_REAL,
    EXCHANGE_NETWORK_MODE_SIMULATED,
    ExchangeExecutionPolicyInput,
    ExchangeExecutionTransportInput,
    ExchangeIntegration,
)
from projects.polymarket.polyquantbot.platform.execution.execution_transport import (
    EXECUTION_TRANSPORT_MODE_REAL,
    ExecutionTransportResult,
)

VALID_TRANSPORT_RESULT = ExecutionTransportResult(
    submitted=True,
    success=True,
    blocked_reason=None,
    execution_authorized=True,
    request_payload={"client_order_id": "CID-5-3-001", "side": "BUY", "size": 10},
    exchange_response={"transport": "ok"},
    transport_mode=EXECUTION_TRANSPORT_MODE_REAL,
    simulated=False,
    non_executing=False,
)

VALID_TRANSPORT_INPUT = ExchangeExecutionTransportInput(
    transport_result=VALID_TRANSPORT_RESULT,
    upstream_trace_refs={"phase": "5.3"},
)

VALID_POLICY_INPUT = ExchangeExecutionPolicyInput(
    network_enabled=True,
    allow_real_network=True,
    endpoint_url="https://api.exchange.local/orders",
    http_method="POST",
    signing_required=True,
    signing_key_present=True,
    signing_scheme="ed25519",
    wallet_reference="wallet-ref-001",
    request_timeout_ms=500,
    allow_testnet=False,
    environment="prod",
    allowed_environments=["prod", "staging"],
    policy_trace_refs={"policy": "phase5.3"},
)


def test_phase5_3_valid_transport_and_policy_allows_real_execution() -> None:
    def fake_requester(url: str, method: str, payload: dict[str, object], timeout_ms: int) -> dict[str, object]:
        return {
            "url": url,
            "method": method,
            "timeout_ms": timeout_ms,
            "echo_execution_id": payload["execution_id"],
        }

    integration = ExchangeIntegration(real_network_enabled=True, requester=fake_requester)

    build = integration.execute_with_trace(
        transport_input=VALID_TRANSPORT_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )

    assert build.result is not None
    assert build.result.executed is True
    assert build.result.success is True
    assert build.result.blocked_reason is None
    assert build.result.network_used == VALID_POLICY_INPUT.endpoint_url
    assert build.result.signing_used is True
    assert build.result.simulated is False
    assert build.result.non_executing is False


def test_phase5_3_simulated_transport_is_blocked() -> None:
    integration = ExchangeIntegration(real_network_enabled=True)

    build = integration.execute_with_trace(
        transport_input=replace(
            VALID_TRANSPORT_INPUT,
            transport_result=replace(VALID_TRANSPORT_RESULT, simulated=True),
        ),
        policy_input=VALID_POLICY_INPUT,
    )

    assert build.result is not None
    assert build.result.blocked_reason == EXCHANGE_EXECUTION_BLOCK_SIMULATED_TRANSPORT


def test_phase5_3_network_disabled_is_blocked() -> None:
    integration = ExchangeIntegration(real_network_enabled=True)

    build = integration.execute_with_trace(
        transport_input=VALID_TRANSPORT_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, network_enabled=False),
    )

    assert build.result is not None
    assert build.result.blocked_reason == EXCHANGE_EXECUTION_BLOCK_NETWORK_DISABLED


def test_phase5_3_invalid_endpoint_is_blocked() -> None:
    integration = ExchangeIntegration(real_network_enabled=True)

    build = integration.execute_with_trace(
        transport_input=VALID_TRANSPORT_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, endpoint_url="not-a-url"),
    )

    assert build.result is not None
    assert build.result.blocked_reason == EXCHANGE_EXECUTION_BLOCK_INVALID_ENDPOINT


def test_phase5_3_signing_required_missing_is_blocked() -> None:
    integration = ExchangeIntegration(real_network_enabled=True)

    build = integration.execute_with_trace(
        transport_input=VALID_TRANSPORT_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, signing_key_present=False),
    )

    assert build.result is not None
    assert build.result.blocked_reason == EXCHANGE_EXECUTION_BLOCK_SIGNING_REQUIRED_MISSING


def test_phase5_3_environment_not_allowed_is_blocked() -> None:
    integration = ExchangeIntegration(real_network_enabled=True)

    build = integration.execute_with_trace(
        transport_input=VALID_TRANSPORT_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, environment="dev"),
    )

    assert build.result is not None
    assert build.result.blocked_reason == EXCHANGE_EXECUTION_BLOCK_ENVIRONMENT_NOT_ALLOWED


def test_phase5_3_allow_real_network_false_is_blocked() -> None:
    integration = ExchangeIntegration(real_network_enabled=True)

    build = integration.execute_with_trace(
        transport_input=VALID_TRANSPORT_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, allow_real_network=False),
    )

    assert build.result is not None
    assert build.result.blocked_reason == EXCHANGE_EXECUTION_BLOCK_REAL_NETWORK_NOT_ALLOWED


def test_phase5_3_deterministic_gating() -> None:
    integration = ExchangeIntegration(real_network_enabled=False)

    first = integration.execute_with_trace(
        transport_input=VALID_TRANSPORT_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )
    second = integration.execute_with_trace(
        transport_input=VALID_TRANSPORT_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )

    assert first == second


def test_phase5_3_simulated_vs_real_path_behavior() -> None:
    simulated = ExchangeIntegration(real_network_enabled=False)
    real = ExchangeIntegration(real_network_enabled=True, requester=lambda *_: {"status": "ok"})

    simulated_build = simulated.execute_with_trace(
        transport_input=VALID_TRANSPORT_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )
    real_build = real.execute_with_trace(
        transport_input=VALID_TRANSPORT_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )

    assert simulated_build.result is not None
    assert real_build.result is not None
    assert simulated_build.result.network_used == EXCHANGE_NETWORK_MODE_SIMULATED
    assert real_build.result.simulated is False
    assert real_build.trace.exchange_notes == {"network_mode": EXCHANGE_NETWORK_MODE_REAL}


def test_phase5_3_invalid_inputs_do_not_crash() -> None:
    integration = ExchangeIntegration(real_network_enabled=True)

    invalid_transport = integration.execute_with_trace(
        transport_input=None,  # type: ignore[arg-type]
        policy_input=VALID_POLICY_INPUT,
    )
    invalid_policy = integration.execute_with_trace(
        transport_input=VALID_TRANSPORT_INPUT,
        policy_input=None,  # type: ignore[arg-type]
    )

    assert invalid_transport.result is not None
    assert invalid_transport.result.blocked_reason == EXCHANGE_EXECUTION_BLOCK_INVALID_TRANSPORT_INPUT_CONTRACT
    assert invalid_policy.result is not None
    assert invalid_policy.result.blocked_reason == EXCHANGE_EXECUTION_BLOCK_INVALID_POLICY_INPUT_CONTRACT


def test_phase5_3_allow_testnet_policy_violation_is_blocked() -> None:
    integration = ExchangeIntegration(real_network_enabled=True)

    build = integration.execute_with_trace(
        transport_input=VALID_TRANSPORT_INPUT,
        policy_input=replace(
            VALID_POLICY_INPUT,
            endpoint_url="https://testnet.exchange.local/orders",
            environment="testnet",
            allowed_environments=["testnet", "prod"],
            allow_testnet=False,
        ),
    )

    assert build.result is not None
    assert build.result.blocked_reason == EXCHANGE_EXECUTION_BLOCK_ENVIRONMENT_NOT_ALLOWED


def test_phase5_3_simulated_path_returns_non_executing() -> None:
    integration = ExchangeIntegration(real_network_enabled=False)

    build = integration.execute_with_trace(
        transport_input=VALID_TRANSPORT_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )

    assert build.result is not None
    assert build.result.simulated is True
    assert build.result.non_executing is True
    assert build.result.network_used == EXCHANGE_NETWORK_MODE_SIMULATED
