from __future__ import annotations

from dataclasses import replace

from projects.polymarket.polyquantbot.platform.execution.exchange_integration import (
    ExchangeExecutionPolicyInput,
    ExchangeExecutionResult,
    ExchangeExecutionTransportInput,
    ExchangeIntegration,
)
from projects.polymarket.polyquantbot.platform.execution.execution_decision import ExecutionDecision
from projects.polymarket.polyquantbot.platform.execution.execution_gateway import (
    ExecutionGateway,
    ExecutionGatewayDecisionInput,
)
from projects.polymarket.polyquantbot.platform.execution.execution_mode_controller import MODE_LIVE
from projects.polymarket.polyquantbot.platform.execution.execution_transport import (
    ExecutionTransport,
    ExecutionTransportAuthorizationInput,
    ExecutionTransportPolicyInput,
)
from projects.polymarket.polyquantbot.platform.execution.fund_settlement import (
    FUND_SETTLEMENT_BLOCK_MONITORING_ANOMALY,
    FUND_SETTLEMENT_HALT_MONITORING_ANOMALY,
    FUND_SETTLEMENT_STATUS_COMPLETED,
    FundSettlementEngine,
    FundSettlementExecutionInput,
    FundSettlementPolicyInput,
)
from projects.polymarket.polyquantbot.platform.execution.live_execution_authorizer import (
    LiveExecutionAuthorizationPolicyInput,
    LiveExecutionAuthorizer,
    LiveExecutionReadinessInput,
)
from projects.polymarket.polyquantbot.platform.execution.live_execution_guardrails import LiveExecutionReadinessDecision
from projects.polymarket.polyquantbot.platform.execution.monitoring_circuit_breaker import (
    ANOMALY_EXPOSURE_THRESHOLD_BREACH,
    ANOMALY_KILL_SWITCH_TRIGGERED,
    MonitoringCircuitBreaker,
    MonitoringContractInput,
)
from projects.polymarket.polyquantbot.platform.execution.secure_signing import (
    SIGNING_METHOD_REAL,
    SecureSigningEngine,
    SigningExecutionInput,
    SigningPolicyInput,
    SigningResult,
)
from projects.polymarket.polyquantbot.platform.execution.wallet_capital import (
    CAPITAL_ALLOCATION_SCOPE_SINGLE,
    WalletCapitalController,
    WalletCapitalExecutionInput,
    WalletCapitalPolicyInput,
    WalletCapitalResult,
)

VALID_MONITORING_INPUT = MonitoringContractInput(
    policy_ref="phase6_4_8_policy",
    eval_ref="phase6_4_8_eval",
    timestamp_ms=1713207600000,
    exposure_ratio=0.10,
    position_notional_usd=100.0,
    total_capital_usd=1_000.0,
    data_freshness_ms=120,
    quality_score=0.93,
    signal_dedup_ok=True,
    kill_switch_armed=True,
    kill_switch_triggered=False,
    monitoring_enabled=True,
    quality_guard_enabled=True,
    exposure_guard_enabled=True,
    max_exposure_ratio=0.10,
    max_data_freshness_ms=500,
    min_quality_score=0.80,
    trace_refs={"target_path": "fund_settlement.settle_with_trace"},
)

VALID_SIGNING_RESULT = SigningResult(
    signed=True,
    success=True,
    blocked_reason=None,
    signature="sig-6-4-8-001",
    payload_hash="hash-6-4-8-001",
    signing_scheme="ed25519",
    key_reference="key-ref-001",
    signing_method=SIGNING_METHOD_REAL,
    simulated=False,
    non_executing=False,
)

VALID_WALLET_CAPITAL_RESULT = WalletCapitalResult(
    capital_authorized=True,
    success=True,
    blocked_reason=None,
    wallet_id="wallet-6-4-8",
    capital_amount=250.0,
    currency="USDC",
    allocation_scope=CAPITAL_ALLOCATION_SCOPE_SINGLE,
    capital_locked=True,
    balance_snapshot={"available": 1000.0},
    simulated=False,
    non_executing=False,
)


def _wallet_policy() -> WalletCapitalPolicyInput:
    return WalletCapitalPolicyInput(
        capital_control_enabled=True,
        allow_real_capital=True,
        wallet_id="wallet-6-4-8",
        wallet_registered=True,
        wallet_access_granted=True,
        currency="USDC",
        allowed_currencies=["USDC", "USD"],
        max_capital_per_trade=500.0,
        requested_capital=250.0,
        balance_check_required=True,
        balance_available=1000.0,
        lock_funds_required=True,
        lock_confirmed=True,
        audit_required=True,
        audit_attached=True,
        operator_approval_required=True,
        operator_approval_present=True,
        policy_trace_refs={"policy": "phase6.4.8.capital"},
    )


def _wallet_execution_input() -> WalletCapitalExecutionInput:
    return WalletCapitalExecutionInput(
        signing_result=VALID_SIGNING_RESULT,
        monitoring_input=VALID_MONITORING_INPUT,
        monitoring_circuit_breaker=MonitoringCircuitBreaker(),
        monitoring_required=True,
        upstream_trace_refs={"phase": "6.4.8"},
    )


def _settlement_policy() -> FundSettlementPolicyInput:
    return FundSettlementPolicyInput(
        settlement_enabled=True,
        allow_real_settlement=True,
        wallet_id="wallet-6-4-8",
        wallet_access_granted=True,
        settlement_method="TRANSFER",
        allowed_methods=["TRANSFER", "WIRE"],
        amount=250.0,
        currency="USDC",
        settlement_limits_enabled=True,
        max_settlement_amount=500.0,
        balance_check_required=True,
        balance_available=1000.0,
        final_confirmation_required=True,
        final_confirmation_present=True,
        irreversible_ack_required=True,
        irreversible_ack_present=True,
        audit_required=True,
        audit_attached=True,
        policy_trace_refs={"policy": "phase6.4.8.settlement"},
    )


def _settlement_execution_input() -> FundSettlementExecutionInput:
    return FundSettlementExecutionInput(
        wallet_capital_result=VALID_WALLET_CAPITAL_RESULT,
        monitoring_input=VALID_MONITORING_INPUT,
        monitoring_circuit_breaker=MonitoringCircuitBreaker(),
        monitoring_required=True,
        upstream_trace_refs={"phase": "6.4.8"},
    )


def test_phase6_4_8_settlement_monitoring_allow_pass_through() -> None:
    engine = FundSettlementEngine(
        real_settlement_enabled=True,
        transfer_executor=lambda *_: "tx-6-4-8-allow",
    )

    build = engine.settle_with_trace(
        execution_input=_settlement_execution_input(),
        policy_input=_settlement_policy(),
    )

    assert build.result is not None
    assert build.result.success is True
    assert build.result.settled is True
    assert build.result.blocked_reason is None
    assert build.result.settlement_status == FUND_SETTLEMENT_STATUS_COMPLETED
    assert build.trace.upstream_trace_refs["monitoring"]["decision"] == "ALLOW"


def test_phase6_4_8_settlement_monitoring_block_prevents_settlement() -> None:
    engine = FundSettlementEngine(real_settlement_enabled=True)
    breaker = MonitoringCircuitBreaker()

    build = engine.settle_with_trace(
        execution_input=replace(
            _settlement_execution_input(),
            monitoring_input=replace(VALID_MONITORING_INPUT, exposure_ratio=0.11),
            monitoring_circuit_breaker=breaker,
        ),
        policy_input=_settlement_policy(),
    )

    assert build.result is not None
    assert build.result.settled is False
    assert build.result.blocked_reason == FUND_SETTLEMENT_BLOCK_MONITORING_ANOMALY
    assert build.trace.upstream_trace_refs["monitoring"]["primary_anomaly"] == ANOMALY_EXPOSURE_THRESHOLD_BREACH
    assert len(breaker.get_events()) == 1


def test_phase6_4_8_settlement_monitoring_halt_stops_settlement() -> None:
    engine = FundSettlementEngine(real_settlement_enabled=True)
    breaker = MonitoringCircuitBreaker()

    build = engine.settle_with_trace(
        execution_input=replace(
            _settlement_execution_input(),
            monitoring_input=replace(VALID_MONITORING_INPUT, kill_switch_triggered=True),
            monitoring_circuit_breaker=breaker,
        ),
        policy_input=_settlement_policy(),
    )

    assert build.result is not None
    assert build.result.settled is False
    assert build.result.blocked_reason == FUND_SETTLEMENT_HALT_MONITORING_ANOMALY
    assert build.trace.upstream_trace_refs["monitoring"]["primary_anomaly"] == ANOMALY_KILL_SWITCH_TRIGGERED
    assert len(breaker.get_events()) == 1


def test_phase6_4_8_existing_six_monitored_paths_remain_intact() -> None:
    authorizer = LiveExecutionAuthorizer()
    gateway = ExecutionGateway()
    transport = ExecutionTransport()
    exchange = ExchangeIntegration(real_network_enabled=False)
    signing_engine = SecureSigningEngine(real_signing_enabled=True)
    capital_controller = WalletCapitalController(real_capital_enabled=True)

    auth_build = authorizer.authorize_with_trace(
        readiness_input=LiveExecutionReadinessInput(
            readiness_decision=LiveExecutionReadinessDecision(
                live_ready=True,
                allowed=True,
                blocked_reason=None,
                selected_mode=MODE_LIVE,
                guardrail_passed=True,
                kill_switch_armed=True,
                simulated=True,
                non_executing=True,
            ),
            monitoring_input=VALID_MONITORING_INPUT,
            monitoring_circuit_breaker=MonitoringCircuitBreaker(),
            source_trace_refs={"phase": "6.4.3"},
        ),
        policy_input=LiveExecutionAuthorizationPolicyInput(
            explicit_execution_enable=True,
            authorization_scope="single_market_first_path",
            allowed_scopes=("single_market_first_path",),
            single_market_only=True,
            target_market_id="market-6-4-8",
            wallet_binding_required=True,
            wallet_binding_present=True,
            audit_required=True,
            audit_attached=True,
            operator_approval_required=True,
            operator_approval_present=True,
            kill_switch_must_remain_armed=True,
            monitoring_required=True,
            policy_trace_refs={"phase": "6.4.3"},
        ),
    )
    assert auth_build.decision is not None
    assert auth_build.decision.execution_authorized is True

    gateway_build = gateway.simulate_execution_with_trace(
        decision_input=ExecutionGatewayDecisionInput(
            decision=ExecutionDecision(
                allowed=True,
                blocked_reason=None,
                market_id="MKT-6-4-8",
                outcome="YES",
                side="YES",
                size=5.0,
                routing_mode="platform-gateway-shadow",
                execution_mode="paper-prep-only",
                ready_for_execution=True,
                non_activating=True,
            ),
            monitoring_input=VALID_MONITORING_INPUT,
            monitoring_circuit_breaker=MonitoringCircuitBreaker(),
            monitoring_required=True,
            source_trace_refs={"phase": "6.4.4"},
        )
    )
    assert gateway_build.result is not None
    assert gateway_build.result.accepted is True

    transport_build = transport.submit_with_trace(
        authorization_input=ExecutionTransportAuthorizationInput(
            authorization=auth_build.decision,
            gateway_result=gateway_build.result,
            monitoring_input=VALID_MONITORING_INPUT,
            monitoring_circuit_breaker=MonitoringCircuitBreaker(),
            source_trace_refs={"phase": "6.4.2"},
        ),
        policy_input=ExecutionTransportPolicyInput(
            transport_enabled=True,
            execution_mode=MODE_LIVE,
            dry_run_force=False,
            allow_real_submission=True,
            single_submission_only=True,
            max_orders=1,
            require_idempotency=True,
            idempotency_key_present=True,
            audit_log_required=True,
            audit_log_attached=True,
            operator_confirm_required=True,
            operator_confirm_present=True,
            monitoring_required=True,
            policy_trace_refs={"phase": "6.4.2"},
        ),
    )
    assert transport_build.result is not None
    assert transport_build.result.submitted is True
    assert transport_build.result.success is True

    exchange_build = exchange.execute_with_trace(
        transport_input=ExchangeExecutionTransportInput(
            transport_result=transport_build.result,
            monitoring_input=VALID_MONITORING_INPUT,
            monitoring_circuit_breaker=MonitoringCircuitBreaker(),
            monitoring_required=True,
            upstream_trace_refs={"phase": "6.4.5"},
        ),
        policy_input=ExchangeExecutionPolicyInput(
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
            policy_trace_refs={"policy": "phase6.4.5.exchange"},
        ),
    )
    assert exchange_build.result is not None
    assert exchange_build.result.executed is True
    assert exchange_build.result.success is True

    signing_build = signing_engine.sign_with_trace(
        signing_input=SigningExecutionInput(
            exchange_result=ExchangeExecutionResult(
                executed=True,
                success=True,
                blocked_reason=None,
                execution_id="EXE-6-4-8-001",
                request_payload={"execution_id": "EXE-6-4-8-001"},
                signed_payload={"execution_id": "EXE-6-4-8-001"},
                exchange_response={"status": "ok"},
                network_used="REAL",
                signing_used=True,
                simulated=False,
                non_executing=False,
            ),
            monitoring_input=VALID_MONITORING_INPUT,
            monitoring_circuit_breaker=MonitoringCircuitBreaker(),
            monitoring_required=True,
            upstream_trace_refs={"phase": "6.4.6"},
        ),
        policy_input=SigningPolicyInput(
            signing_enabled=True,
            allow_real_signing=True,
            signing_scheme="ed25519",
            allowed_schemes=["ed25519", "secp256k1"],
            key_reference="key-ref-001",
            key_registry_enabled=True,
            key_registered=True,
            key_access_granted=True,
            allow_external_signer=True,
            external_signer_used=False,
            simulated_signing_force=False,
            audit_required=True,
            audit_attached=True,
            operator_approval_required=True,
            operator_approval_present=True,
            policy_trace_refs={"policy": "phase6.4.6.signing"},
        ),
    )
    assert signing_build.result is not None
    assert signing_build.result.signed is True
    assert signing_build.result.success is True

    capital_build = capital_controller.authorize_capital_with_trace(
        execution_input=_wallet_execution_input(),
        policy_input=_wallet_policy(),
    )
    assert capital_build.result is not None
    assert capital_build.result.capital_authorized is True
    assert capital_build.result.success is True
