from __future__ import annotations

from dataclasses import replace

from projects.polymarket.polyquantbot.platform.execution.secure_signing import (
    SIGNING_METHOD_REAL,
    SigningResult,
)
from projects.polymarket.polyquantbot.platform.execution.wallet_capital import (
    WALLET_CAPITAL_BLOCK_AUDIT_MISSING,
    WALLET_CAPITAL_BLOCK_CAPITAL_CONTROL_DISABLED,
    WALLET_CAPITAL_BLOCK_CAPITAL_LIMIT_EXCEEDED,
    WALLET_CAPITAL_BLOCK_CURRENCY_NOT_ALLOWED,
    WALLET_CAPITAL_BLOCK_FUND_LOCK_REQUIRED,
    WALLET_CAPITAL_BLOCK_INSUFFICIENT_BALANCE,
    WALLET_CAPITAL_BLOCK_INVALID_SIGNING_INPUT_CONTRACT,
    WALLET_CAPITAL_BLOCK_OPERATOR_APPROVAL_MISSING,
    WALLET_CAPITAL_BLOCK_WALLET_ACCESS_DENIED,
    WALLET_CAPITAL_BLOCK_WALLET_NOT_REGISTERED,
    WalletCapitalController,
    WalletCapitalExecutionInput,
    WalletCapitalPolicyInput,
)

VALID_SIGNING_RESULT = SigningResult(
    signed=True,
    success=True,
    blocked_reason=None,
    signature="sig-5-5-001",
    payload_hash="hash-5-5-001",
    signing_scheme="ed25519",
    key_reference="key-ref-001",
    signing_method=SIGNING_METHOD_REAL,
    simulated=False,
    non_executing=False,
)

VALID_EXECUTION_INPUT = WalletCapitalExecutionInput(
    signing_result=VALID_SIGNING_RESULT,
    upstream_trace_refs={"phase": "5.5"},
)

VALID_POLICY_INPUT = WalletCapitalPolicyInput(
    capital_control_enabled=True,
    allow_real_capital=True,
    wallet_id="wallet-001",
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
    policy_trace_refs={"policy": "phase5.5"},
)


def test_phase5_5_valid_signing_and_policy_allow_real_capital() -> None:
    controller = WalletCapitalController(real_capital_enabled=True)

    build = controller.authorize_capital_with_trace(
        execution_input=VALID_EXECUTION_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )

    assert build.result is not None
    assert build.result.capital_authorized is True
    assert build.result.success is True
    assert build.result.blocked_reason is None
    assert build.result.capital_locked is True
    assert build.result.simulated is False
    assert build.result.non_executing is False


def test_phase5_5_simulated_capital_path() -> None:
    controller = WalletCapitalController(real_capital_enabled=False)

    build = controller.authorize_capital_with_trace(
        execution_input=VALID_EXECUTION_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )

    assert build.result is not None
    assert build.result.success is True
    assert build.result.capital_authorized is False
    assert build.result.capital_locked is False
    assert build.result.simulated is True
    assert build.result.non_executing is True


def test_phase5_5_capital_disabled_is_blocked() -> None:
    controller = WalletCapitalController(real_capital_enabled=True)

    build = controller.authorize_capital_with_trace(
        execution_input=VALID_EXECUTION_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, capital_control_enabled=False),
    )

    assert build.result is not None
    assert build.result.blocked_reason == WALLET_CAPITAL_BLOCK_CAPITAL_CONTROL_DISABLED


def test_phase5_5_wallet_not_registered_is_blocked() -> None:
    controller = WalletCapitalController(real_capital_enabled=True)

    build = controller.authorize_capital_with_trace(
        execution_input=VALID_EXECUTION_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, wallet_registered=False),
    )

    assert build.result is not None
    assert build.result.blocked_reason == WALLET_CAPITAL_BLOCK_WALLET_NOT_REGISTERED


def test_phase5_5_wallet_access_denied_is_blocked() -> None:
    controller = WalletCapitalController(real_capital_enabled=True)

    build = controller.authorize_capital_with_trace(
        execution_input=VALID_EXECUTION_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, wallet_access_granted=False),
    )

    assert build.result is not None
    assert build.result.blocked_reason == WALLET_CAPITAL_BLOCK_WALLET_ACCESS_DENIED


def test_phase5_5_currency_invalid_is_blocked() -> None:
    controller = WalletCapitalController(real_capital_enabled=True)

    build = controller.authorize_capital_with_trace(
        execution_input=VALID_EXECUTION_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, currency="JPY"),
    )

    assert build.result is not None
    assert build.result.blocked_reason == WALLET_CAPITAL_BLOCK_CURRENCY_NOT_ALLOWED


def test_phase5_5_capital_limit_exceeded_is_blocked() -> None:
    controller = WalletCapitalController(real_capital_enabled=True)

    build = controller.authorize_capital_with_trace(
        execution_input=VALID_EXECUTION_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, requested_capital=501.0),
    )

    assert build.result is not None
    assert build.result.blocked_reason == WALLET_CAPITAL_BLOCK_CAPITAL_LIMIT_EXCEEDED


def test_phase5_5_insufficient_balance_is_blocked() -> None:
    controller = WalletCapitalController(real_capital_enabled=True)

    build = controller.authorize_capital_with_trace(
        execution_input=VALID_EXECUTION_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, balance_available=100.0),
    )

    assert build.result is not None
    assert build.result.blocked_reason == WALLET_CAPITAL_BLOCK_INSUFFICIENT_BALANCE


def test_phase5_5_fund_lock_missing_is_blocked() -> None:
    controller = WalletCapitalController(real_capital_enabled=True)

    build = controller.authorize_capital_with_trace(
        execution_input=VALID_EXECUTION_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, lock_confirmed=False),
    )

    assert build.result is not None
    assert build.result.blocked_reason == WALLET_CAPITAL_BLOCK_FUND_LOCK_REQUIRED


def test_phase5_5_audit_missing_is_blocked() -> None:
    controller = WalletCapitalController(real_capital_enabled=True)

    build = controller.authorize_capital_with_trace(
        execution_input=VALID_EXECUTION_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, audit_attached=False),
    )

    assert build.result is not None
    assert build.result.blocked_reason == WALLET_CAPITAL_BLOCK_AUDIT_MISSING


def test_phase5_5_operator_approval_missing_is_blocked() -> None:
    controller = WalletCapitalController(real_capital_enabled=True)

    build = controller.authorize_capital_with_trace(
        execution_input=VALID_EXECUTION_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, operator_approval_present=False),
    )

    assert build.result is not None
    assert build.result.blocked_reason == WALLET_CAPITAL_BLOCK_OPERATOR_APPROVAL_MISSING


def test_phase5_5_deterministic_gating() -> None:
    controller = WalletCapitalController(real_capital_enabled=True)

    first = controller.authorize_capital_with_trace(
        execution_input=VALID_EXECUTION_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )
    second = controller.authorize_capital_with_trace(
        execution_input=VALID_EXECUTION_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )

    assert first == second


def test_phase5_5_invalid_inputs_do_not_crash() -> None:
    controller = WalletCapitalController(real_capital_enabled=True)

    invalid_execution_input = controller.authorize_capital_with_trace(
        execution_input=None,  # type: ignore[arg-type]
        policy_input=VALID_POLICY_INPUT,
    )
    invalid_policy_input = controller.authorize_capital_with_trace(
        execution_input=VALID_EXECUTION_INPUT,
        policy_input=None,  # type: ignore[arg-type]
    )
    invalid_signing_contract = controller.authorize_capital_with_trace(
        execution_input=replace(VALID_EXECUTION_INPUT, signing_result=None),  # type: ignore[arg-type]
        policy_input=VALID_POLICY_INPUT,
    )

    assert invalid_execution_input.result is not None
    assert invalid_execution_input.result.blocked_reason == WALLET_CAPITAL_BLOCK_INVALID_SIGNING_INPUT_CONTRACT
    assert invalid_policy_input.result is not None
    assert invalid_policy_input.result.blocked_reason == WALLET_CAPITAL_BLOCK_INVALID_SIGNING_INPUT_CONTRACT
    assert invalid_signing_contract.result is not None
    assert invalid_signing_contract.result.blocked_reason == WALLET_CAPITAL_BLOCK_INVALID_SIGNING_INPUT_CONTRACT


def test_phase5_5_no_real_fund_movement() -> None:
    controller = WalletCapitalController(real_capital_enabled=True)

    build = controller.authorize_capital_with_trace(
        execution_input=VALID_EXECUTION_INPUT,
        policy_input=VALID_POLICY_INPUT,
    )

    assert build.result is not None
    assert build.result.balance_snapshot is not None
    assert build.result.balance_snapshot["available"] == VALID_POLICY_INPUT.balance_available
    assert build.result.balance_snapshot["requested"] == VALID_POLICY_INPUT.requested_capital
    assert build.result.balance_snapshot["remaining_after_request"] == (
        VALID_POLICY_INPUT.balance_available - VALID_POLICY_INPUT.requested_capital
    )
