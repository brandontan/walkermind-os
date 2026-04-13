from __future__ import annotations

from dataclasses import replace

from projects.polymarket.polyquantbot.platform.execution.fund_settlement import (
    FUND_SETTLEMENT_BLOCK_AUDIT_MISSING,
    FUND_SETTLEMENT_BLOCK_CAPITAL_NOT_AUTHORIZED,
    FUND_SETTLEMENT_BLOCK_FINAL_CONFIRMATION_MISSING,
    FUND_SETTLEMENT_BLOCK_INSUFFICIENT_BALANCE,
    FUND_SETTLEMENT_BLOCK_INVALID_SETTLEMENT_METHOD,
    FUND_SETTLEMENT_BLOCK_INVALID_WALLET_CAPITAL_INPUT_CONTRACT,
    FUND_SETTLEMENT_BLOCK_IRREVERSIBLE_ACK_MISSING,
    FUND_SETTLEMENT_BLOCK_SETTLEMENT_DISABLED,
    FUND_SETTLEMENT_BLOCK_SETTLEMENT_LIMIT_EXCEEDED,
    FUND_SETTLEMENT_BLOCK_WALLET_ACCESS_DENIED,
    FUND_SETTLEMENT_STATUS_COMPLETED,
    FUND_SETTLEMENT_STATUS_SIMULATED,
    FundSettlementEngine,
    FundSettlementExecutionInput,
    FundSettlementPolicyInput,
)
from projects.polymarket.polyquantbot.platform.execution.wallet_capital import (
    CAPITAL_ALLOCATION_SCOPE_SINGLE,
    WalletCapitalResult,
)

VALID_WALLET_CAPITAL_RESULT = WalletCapitalResult(
    capital_authorized=True,
    success=True,
    blocked_reason=None,
    wallet_id="wallet-001",
    capital_amount=250.0,
    currency="USDC",
    allocation_scope=CAPITAL_ALLOCATION_SCOPE_SINGLE,
    capital_locked=True,
    balance_snapshot={"available": 1000.0},
    simulated=False,
    non_executing=False,
)

VALID_EXECUTION_INPUT = FundSettlementExecutionInput(
    wallet_capital_result=VALID_WALLET_CAPITAL_RESULT,
    upstream_trace_refs={"phase": "5.6"},
)

VALID_POLICY_INPUT = FundSettlementPolicyInput(
    settlement_enabled=True,
    allow_real_settlement=True,
    wallet_id="wallet-001",
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
    policy_trace_refs={"policy": "phase5.6"},
)


def test_phase5_6_valid_pipeline_allows_real_settlement() -> None:
    engine = FundSettlementEngine(
        real_settlement_enabled=True,
        transfer_executor=lambda *_: "tx-ref-001",
    )

    build = engine.settle_with_trace(
        execution_input=VALID_EXECUTION_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )

    assert build.result is not None
    assert build.result.settled is True
    assert build.result.success is True
    assert build.result.blocked_reason is None
    assert build.result.settlement_status == FUND_SETTLEMENT_STATUS_COMPLETED
    assert build.result.transfer_reference == "tx-ref-001"
    assert build.result.simulated is False
    assert build.result.non_executing is False


def test_phase5_6_simulated_settlement_default_safe_path() -> None:
    engine = FundSettlementEngine(real_settlement_enabled=False)

    build = engine.settle_with_trace(
        execution_input=VALID_EXECUTION_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )

    assert build.result is not None
    assert build.result.success is True
    assert build.result.settled is False
    assert build.result.settlement_status == FUND_SETTLEMENT_STATUS_SIMULATED
    assert build.result.balance_before == build.result.balance_after
    assert build.result.simulated is True
    assert build.result.non_executing is True


def test_phase5_6_settlement_disabled_is_blocked() -> None:
    engine = FundSettlementEngine(real_settlement_enabled=True)

    build = engine.settle_with_trace(
        execution_input=VALID_EXECUTION_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, settlement_enabled=False),
    )

    assert build.result is not None
    assert build.result.blocked_reason == FUND_SETTLEMENT_BLOCK_SETTLEMENT_DISABLED


def test_phase5_6_capital_not_authorized_is_blocked() -> None:
    engine = FundSettlementEngine(real_settlement_enabled=True)

    build = engine.settle_with_trace(
        execution_input=replace(
            VALID_EXECUTION_INPUT,
            wallet_capital_result=replace(VALID_WALLET_CAPITAL_RESULT, capital_authorized=False),
        ),
        policy_input=VALID_POLICY_INPUT,
    )

    assert build.result is not None
    assert build.result.blocked_reason == FUND_SETTLEMENT_BLOCK_CAPITAL_NOT_AUTHORIZED


def test_phase5_6_wallet_access_denied_is_blocked() -> None:
    engine = FundSettlementEngine(real_settlement_enabled=True)

    build = engine.settle_with_trace(
        execution_input=VALID_EXECUTION_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, wallet_access_granted=False),
    )

    assert build.result is not None
    assert build.result.blocked_reason == FUND_SETTLEMENT_BLOCK_WALLET_ACCESS_DENIED


def test_phase5_6_invalid_method_is_blocked() -> None:
    engine = FundSettlementEngine(real_settlement_enabled=True)

    build = engine.settle_with_trace(
        execution_input=VALID_EXECUTION_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, settlement_method="CRYPTO_RAIL"),
    )

    assert build.result is not None
    assert build.result.blocked_reason == FUND_SETTLEMENT_BLOCK_INVALID_SETTLEMENT_METHOD


def test_phase5_6_settlement_limit_exceeded_is_blocked() -> None:
    engine = FundSettlementEngine(real_settlement_enabled=True)

    build = engine.settle_with_trace(
        execution_input=VALID_EXECUTION_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, amount=501.0),
    )

    assert build.result is not None
    assert build.result.blocked_reason == FUND_SETTLEMENT_BLOCK_SETTLEMENT_LIMIT_EXCEEDED


def test_phase5_6_insufficient_balance_is_blocked() -> None:
    engine = FundSettlementEngine(real_settlement_enabled=True)

    build = engine.settle_with_trace(
        execution_input=VALID_EXECUTION_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, balance_available=100.0),
    )

    assert build.result is not None
    assert build.result.blocked_reason == FUND_SETTLEMENT_BLOCK_INSUFFICIENT_BALANCE


def test_phase5_6_final_confirmation_missing_is_blocked() -> None:
    engine = FundSettlementEngine(real_settlement_enabled=True)

    build = engine.settle_with_trace(
        execution_input=VALID_EXECUTION_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, final_confirmation_present=False),
    )

    assert build.result is not None
    assert build.result.blocked_reason == FUND_SETTLEMENT_BLOCK_FINAL_CONFIRMATION_MISSING


def test_phase5_6_irreversible_ack_missing_is_blocked() -> None:
    engine = FundSettlementEngine(real_settlement_enabled=True)

    build = engine.settle_with_trace(
        execution_input=VALID_EXECUTION_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, irreversible_ack_present=False),
    )

    assert build.result is not None
    assert build.result.blocked_reason == FUND_SETTLEMENT_BLOCK_IRREVERSIBLE_ACK_MISSING


def test_phase5_6_audit_missing_is_blocked() -> None:
    engine = FundSettlementEngine(real_settlement_enabled=True)

    build = engine.settle_with_trace(
        execution_input=VALID_EXECUTION_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, audit_attached=False),
    )

    assert build.result is not None
    assert build.result.blocked_reason == FUND_SETTLEMENT_BLOCK_AUDIT_MISSING


def test_phase5_6_deterministic_behavior() -> None:
    engine = FundSettlementEngine(
        real_settlement_enabled=True,
        transfer_executor=lambda *_: "tx-deterministic",
    )

    first = engine.settle_with_trace(
        execution_input=VALID_EXECUTION_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )
    second = engine.settle_with_trace(
        execution_input=VALID_EXECUTION_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )

    assert first == second


def test_phase5_6_invalid_inputs_do_not_crash() -> None:
    engine = FundSettlementEngine(real_settlement_enabled=True)

    invalid_execution_input = engine.settle_with_trace(
        execution_input=None,  # type: ignore[arg-type]
        policy_input=VALID_POLICY_INPUT,
    )
    invalid_policy_input = engine.settle_with_trace(
        execution_input=VALID_EXECUTION_INPUT,
        policy_input=None,  # type: ignore[arg-type]
    )
    invalid_wallet_contract = engine.settle_with_trace(
        execution_input=replace(VALID_EXECUTION_INPUT, wallet_capital_result=None),  # type: ignore[arg-type]
        policy_input=VALID_POLICY_INPUT,
    )

    assert invalid_execution_input.result is not None
    assert (
        invalid_execution_input.result.blocked_reason
        == FUND_SETTLEMENT_BLOCK_INVALID_WALLET_CAPITAL_INPUT_CONTRACT
    )
    assert invalid_policy_input.result is not None
    assert invalid_policy_input.result.blocked_reason == FUND_SETTLEMENT_BLOCK_INVALID_WALLET_CAPITAL_INPUT_CONTRACT
    assert invalid_wallet_contract.result is not None
    assert invalid_wallet_contract.result.blocked_reason == FUND_SETTLEMENT_BLOCK_INVALID_WALLET_CAPITAL_INPUT_CONTRACT


def test_phase5_6_balance_snapshot_correctness() -> None:
    engine = FundSettlementEngine(
        real_settlement_enabled=True,
        transfer_executor=lambda *_: "tx-balance-check",
    )

    build = engine.settle_with_trace(
        execution_input=VALID_EXECUTION_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )

    assert build.result is not None
    assert build.result.balance_before == VALID_POLICY_INPUT.balance_available
    assert build.result.balance_after == VALID_POLICY_INPUT.balance_available - VALID_POLICY_INPUT.amount
