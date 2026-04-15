from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .monitoring_circuit_breaker import (
    MONITORING_DECISION_BLOCK,
    MONITORING_DECISION_HALT,
    MonitoringCircuitBreaker,
    MonitoringContractInput,
)
from .secure_signing import SigningResult

CAPITAL_ALLOCATION_SCOPE_SINGLE = "single_allocation"

WALLET_CAPITAL_BLOCK_INVALID_SIGNING_INPUT_CONTRACT = "invalid_signing_input_contract"
WALLET_CAPITAL_BLOCK_CAPITAL_CONTROL_DISABLED = "capital_control_disabled"
WALLET_CAPITAL_BLOCK_REAL_CAPITAL_NOT_ALLOWED = "real_capital_not_allowed"
WALLET_CAPITAL_BLOCK_WALLET_NOT_REGISTERED = "wallet_not_registered"
WALLET_CAPITAL_BLOCK_WALLET_ACCESS_DENIED = "wallet_access_denied"
WALLET_CAPITAL_BLOCK_CURRENCY_NOT_ALLOWED = "currency_not_allowed"
WALLET_CAPITAL_BLOCK_CAPITAL_LIMIT_EXCEEDED = "capital_limit_exceeded"
WALLET_CAPITAL_BLOCK_INSUFFICIENT_BALANCE = "insufficient_balance"
WALLET_CAPITAL_BLOCK_FUND_LOCK_REQUIRED = "fund_lock_required"
WALLET_CAPITAL_BLOCK_AUDIT_MISSING = "audit_missing"
WALLET_CAPITAL_BLOCK_OPERATOR_APPROVAL_MISSING = "operator_approval_missing"
WALLET_CAPITAL_BLOCK_MONITORING_EVALUATION_REQUIRED = "monitoring_evaluation_required"
WALLET_CAPITAL_BLOCK_MONITORING_ANOMALY = "monitoring_anomaly_block"
WALLET_CAPITAL_HALT_MONITORING_ANOMALY = "monitoring_anomaly_halt"


@dataclass(frozen=True)
class WalletCapitalExecutionInput:
    signing_result: SigningResult
    monitoring_input: MonitoringContractInput | None = None
    monitoring_circuit_breaker: MonitoringCircuitBreaker | None = None
    monitoring_required: bool = False
    upstream_trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WalletCapitalPolicyInput:
    capital_control_enabled: bool
    allow_real_capital: bool
    wallet_id: str
    wallet_registered: bool
    wallet_access_granted: bool
    currency: str
    allowed_currencies: list[str]
    max_capital_per_trade: float
    requested_capital: float
    balance_check_required: bool
    balance_available: float
    lock_funds_required: bool
    lock_confirmed: bool
    audit_required: bool
    audit_attached: bool
    operator_approval_required: bool
    operator_approval_present: bool
    policy_trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WalletCapitalResult:
    capital_authorized: bool
    success: bool
    blocked_reason: str | None
    wallet_id: str | None
    capital_amount: float | None
    currency: str | None
    allocation_scope: str
    capital_locked: bool
    balance_snapshot: dict[str, Any] | None
    simulated: bool
    non_executing: bool


@dataclass(frozen=True)
class WalletCapitalTrace:
    capital_check_performed: bool
    blocked_reason: str | None
    upstream_trace_refs: dict[str, Any] = field(default_factory=dict)
    capital_notes: dict[str, Any] | None = None


@dataclass(frozen=True)
class WalletCapitalBuildResult:
    result: WalletCapitalResult | None
    trace: WalletCapitalTrace


class WalletCapitalController:
    """Phase 5.5 wallet-capital boundary with deterministic policy gating."""

    def __init__(self, *, real_capital_enabled: bool = False) -> None:
        self._real_capital_enabled = real_capital_enabled

    def authorize_capital(
        self,
        execution_input: WalletCapitalExecutionInput,
        policy_input: WalletCapitalPolicyInput,
    ) -> WalletCapitalResult | None:
        return self.authorize_capital_with_trace(
            execution_input=execution_input,
            policy_input=policy_input,
        ).result

    def authorize_capital_with_trace(
        self,
        *,
        execution_input: WalletCapitalExecutionInput,
        policy_input: WalletCapitalPolicyInput,
    ) -> WalletCapitalBuildResult:
        if not isinstance(execution_input, WalletCapitalExecutionInput):
            return _blocked_build_result(
                blocked_reason=WALLET_CAPITAL_BLOCK_INVALID_SIGNING_INPUT_CONTRACT,
                capital_check_performed=False,
                wallet_id=None,
                capital_amount=None,
                currency=None,
                upstream_trace_refs={
                    "contract_errors": {
                        "execution_input": {
                            "expected_type": "WalletCapitalExecutionInput",
                            "actual_type": type(execution_input).__name__,
                        }
                    }
                },
            )

        if not isinstance(policy_input, WalletCapitalPolicyInput):
            return _blocked_build_result(
                blocked_reason=WALLET_CAPITAL_BLOCK_INVALID_SIGNING_INPUT_CONTRACT,
                capital_check_performed=False,
                wallet_id=None,
                capital_amount=None,
                currency=None,
                upstream_trace_refs={
                    "contract_errors": {
                        "policy_input": {
                            "expected_type": "WalletCapitalPolicyInput",
                            "actual_type": type(policy_input).__name__,
                        }
                    }
                },
            )

        upstream_trace_refs: dict[str, Any] = {
            "execution_input": dict(execution_input.upstream_trace_refs),
            "policy_input": dict(policy_input.policy_trace_refs),
        }

        if not isinstance(execution_input.signing_result, SigningResult):
            return _blocked_build_result(
                blocked_reason=WALLET_CAPITAL_BLOCK_INVALID_SIGNING_INPUT_CONTRACT,
                capital_check_performed=False,
                wallet_id=policy_input.wallet_id,
                capital_amount=policy_input.requested_capital,
                currency=policy_input.currency,
                upstream_trace_refs=upstream_trace_refs,
            )

        monitoring_result = None
        if execution_input.monitoring_required:
            if not isinstance(execution_input.monitoring_input, MonitoringContractInput):
                return _blocked_build_result(
                    blocked_reason=WALLET_CAPITAL_BLOCK_MONITORING_EVALUATION_REQUIRED,
                    capital_check_performed=False,
                    wallet_id=policy_input.wallet_id,
                    capital_amount=policy_input.requested_capital,
                    currency=policy_input.currency,
                    upstream_trace_refs=upstream_trace_refs,
                )
            if execution_input.monitoring_circuit_breaker is not None and not isinstance(
                execution_input.monitoring_circuit_breaker,
                MonitoringCircuitBreaker,
            ):
                return _blocked_build_result(
                    blocked_reason=WALLET_CAPITAL_BLOCK_MONITORING_EVALUATION_REQUIRED,
                    capital_check_performed=False,
                    wallet_id=policy_input.wallet_id,
                    capital_amount=policy_input.requested_capital,
                    currency=policy_input.currency,
                    upstream_trace_refs=upstream_trace_refs,
                )
            breaker = execution_input.monitoring_circuit_breaker or MonitoringCircuitBreaker()
            monitoring_result = breaker.evaluate(execution_input.monitoring_input)
            upstream_trace_refs["monitoring"] = {
                "decision": monitoring_result.decision,
                "primary_anomaly": monitoring_result.primary_anomaly,
                "anomalies": list(monitoring_result.anomalies),
                "eval_ref": monitoring_result.event.eval_ref,
            }
            if monitoring_result.decision == MONITORING_DECISION_HALT:
                return _blocked_build_result(
                    blocked_reason=WALLET_CAPITAL_HALT_MONITORING_ANOMALY,
                    capital_check_performed=False,
                    wallet_id=policy_input.wallet_id,
                    capital_amount=policy_input.requested_capital,
                    currency=policy_input.currency,
                    upstream_trace_refs=upstream_trace_refs,
                )
            if monitoring_result.decision == MONITORING_DECISION_BLOCK:
                return _blocked_build_result(
                    blocked_reason=WALLET_CAPITAL_BLOCK_MONITORING_ANOMALY,
                    capital_check_performed=False,
                    wallet_id=policy_input.wallet_id,
                    capital_amount=policy_input.requested_capital,
                    currency=policy_input.currency,
                    upstream_trace_refs=upstream_trace_refs,
                )

        block_reason = _determine_blocked_reason(
            signing_result=execution_input.signing_result,
            policy_input=policy_input,
        )
        if block_reason is not None:
            return _blocked_build_result(
                blocked_reason=block_reason,
                capital_check_performed=True,
                wallet_id=policy_input.wallet_id,
                capital_amount=policy_input.requested_capital,
                currency=policy_input.currency,
                upstream_trace_refs=upstream_trace_refs,
            )

        balance_snapshot = {
            "wallet_id": policy_input.wallet_id,
            "currency": policy_input.currency,
            "available": policy_input.balance_available,
            "requested": policy_input.requested_capital,
            "remaining_after_request": policy_input.balance_available - policy_input.requested_capital,
        }

        if not self._real_capital_enabled:
            return WalletCapitalBuildResult(
                result=WalletCapitalResult(
                    capital_authorized=False,
                    success=True,
                    blocked_reason=None,
                    wallet_id=policy_input.wallet_id,
                    capital_amount=policy_input.requested_capital,
                    currency=policy_input.currency,
                    allocation_scope=CAPITAL_ALLOCATION_SCOPE_SINGLE,
                    capital_locked=False,
                    balance_snapshot=balance_snapshot,
                    simulated=True,
                    non_executing=True,
                ),
                trace=WalletCapitalTrace(
                    capital_check_performed=True,
                    blocked_reason=None,
                    upstream_trace_refs=upstream_trace_refs,
                    capital_notes={"capital_mode": "SIMULATED_CAPITAL"},
                ),
            )

        return WalletCapitalBuildResult(
            result=WalletCapitalResult(
                capital_authorized=True,
                success=True,
                blocked_reason=None,
                wallet_id=policy_input.wallet_id,
                capital_amount=policy_input.requested_capital,
                currency=policy_input.currency,
                allocation_scope=CAPITAL_ALLOCATION_SCOPE_SINGLE,
                capital_locked=True,
                balance_snapshot=balance_snapshot,
                simulated=False,
                non_executing=False,
            ),
            trace=WalletCapitalTrace(
                capital_check_performed=True,
                blocked_reason=None,
                upstream_trace_refs=upstream_trace_refs,
                capital_notes={"capital_mode": "REAL_CAPITAL"},
            ),
        )


def _determine_blocked_reason(
    *,
    signing_result: SigningResult,
    policy_input: WalletCapitalPolicyInput,
) -> str | None:
    if signing_result.signed is not True or signing_result.success is not True:
        return WALLET_CAPITAL_BLOCK_INVALID_SIGNING_INPUT_CONTRACT

    if signing_result.simulated is True:
        return WALLET_CAPITAL_BLOCK_INVALID_SIGNING_INPUT_CONTRACT

    if policy_input.capital_control_enabled is not True:
        return WALLET_CAPITAL_BLOCK_CAPITAL_CONTROL_DISABLED

    if policy_input.allow_real_capital is not True:
        return WALLET_CAPITAL_BLOCK_REAL_CAPITAL_NOT_ALLOWED

    if policy_input.wallet_registered is not True:
        return WALLET_CAPITAL_BLOCK_WALLET_NOT_REGISTERED

    if policy_input.wallet_access_granted is not True:
        return WALLET_CAPITAL_BLOCK_WALLET_ACCESS_DENIED

    if _normalize_text(policy_input.currency) not in {
        _normalize_text(currency) for currency in policy_input.allowed_currencies
    }:
        return WALLET_CAPITAL_BLOCK_CURRENCY_NOT_ALLOWED

    if policy_input.requested_capital > policy_input.max_capital_per_trade:
        return WALLET_CAPITAL_BLOCK_CAPITAL_LIMIT_EXCEEDED

    if policy_input.balance_check_required and policy_input.balance_available < policy_input.requested_capital:
        return WALLET_CAPITAL_BLOCK_INSUFFICIENT_BALANCE

    if policy_input.lock_funds_required and policy_input.lock_confirmed is not True:
        return WALLET_CAPITAL_BLOCK_FUND_LOCK_REQUIRED

    if policy_input.audit_required and policy_input.audit_attached is not True:
        return WALLET_CAPITAL_BLOCK_AUDIT_MISSING

    if policy_input.operator_approval_required and policy_input.operator_approval_present is not True:
        return WALLET_CAPITAL_BLOCK_OPERATOR_APPROVAL_MISSING

    return None


def _blocked_build_result(
    *,
    blocked_reason: str,
    capital_check_performed: bool,
    wallet_id: str | None,
    capital_amount: float | None,
    currency: str | None,
    upstream_trace_refs: dict[str, Any],
) -> WalletCapitalBuildResult:
    return WalletCapitalBuildResult(
        result=WalletCapitalResult(
            capital_authorized=False,
            success=False,
            blocked_reason=blocked_reason,
            wallet_id=wallet_id,
            capital_amount=capital_amount,
            currency=currency,
            allocation_scope=CAPITAL_ALLOCATION_SCOPE_SINGLE,
            capital_locked=False,
            balance_snapshot=None,
            simulated=True,
            non_executing=True,
        ),
        trace=WalletCapitalTrace(
            capital_check_performed=capital_check_performed,
            blocked_reason=blocked_reason,
            upstream_trace_refs=upstream_trace_refs,
            capital_notes={"blocked_reason": blocked_reason},
        ),
    )


def _normalize_text(value: str) -> str:
    return value.strip().upper()
