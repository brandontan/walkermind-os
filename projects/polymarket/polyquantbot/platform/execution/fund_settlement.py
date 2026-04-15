from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Any, Callable

from .monitoring_circuit_breaker import (
    MONITORING_DECISION_BLOCK,
    MONITORING_DECISION_HALT,
    MonitoringCircuitBreaker,
    MonitoringContractInput,
)
from .wallet_capital import WalletCapitalResult

FUND_SETTLEMENT_STATUS_BLOCKED = "BLOCKED"
FUND_SETTLEMENT_STATUS_SIMULATED = "SIMULATED"
FUND_SETTLEMENT_STATUS_COMPLETED = "COMPLETED"

FUND_SETTLEMENT_BLOCK_INVALID_WALLET_CAPITAL_INPUT_CONTRACT = "invalid_wallet_capital_input_contract"
FUND_SETTLEMENT_BLOCK_CAPITAL_NOT_AUTHORIZED = "capital_not_authorized"
FUND_SETTLEMENT_BLOCK_SETTLEMENT_DISABLED = "settlement_disabled"
FUND_SETTLEMENT_BLOCK_REAL_SETTLEMENT_NOT_ALLOWED = "real_settlement_not_allowed"
FUND_SETTLEMENT_BLOCK_WALLET_ACCESS_DENIED = "wallet_access_denied"
FUND_SETTLEMENT_BLOCK_INVALID_SETTLEMENT_METHOD = "invalid_settlement_method"
FUND_SETTLEMENT_BLOCK_SETTLEMENT_LIMIT_EXCEEDED = "settlement_limit_exceeded"
FUND_SETTLEMENT_BLOCK_INSUFFICIENT_BALANCE = "insufficient_balance"
FUND_SETTLEMENT_BLOCK_FINAL_CONFIRMATION_MISSING = "final_confirmation_missing"
FUND_SETTLEMENT_BLOCK_IRREVERSIBLE_ACK_MISSING = "irreversible_ack_missing"
FUND_SETTLEMENT_BLOCK_AUDIT_MISSING = "audit_missing"
FUND_SETTLEMENT_BLOCK_MONITORING_EVALUATION_REQUIRED = "monitoring_evaluation_required"
FUND_SETTLEMENT_BLOCK_MONITORING_ANOMALY = "monitoring_anomaly_block"
FUND_SETTLEMENT_HALT_MONITORING_ANOMALY = "monitoring_anomaly_halt"


@dataclass(frozen=True)
class FundSettlementExecutionInput:
    wallet_capital_result: WalletCapitalResult
    monitoring_input: MonitoringContractInput | None = None
    monitoring_circuit_breaker: MonitoringCircuitBreaker | None = None
    monitoring_required: bool = False
    upstream_trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FundSettlementPolicyInput:
    settlement_enabled: bool
    allow_real_settlement: bool
    wallet_id: str
    wallet_access_granted: bool
    settlement_method: str
    allowed_methods: list[str]
    amount: float
    currency: str
    settlement_limits_enabled: bool
    max_settlement_amount: float
    balance_check_required: bool
    balance_available: float
    final_confirmation_required: bool
    final_confirmation_present: bool
    irreversible_ack_required: bool
    irreversible_ack_present: bool
    audit_required: bool
    audit_attached: bool
    policy_trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FundSettlementResult:
    settled: bool
    success: bool
    blocked_reason: str | None
    settlement_id: str | None
    wallet_id: str | None
    amount: float | None
    currency: str | None
    transfer_reference: str | None
    settlement_status: str
    balance_before: float | None
    balance_after: float | None
    simulated: bool
    non_executing: bool


@dataclass(frozen=True)
class FundSettlementTrace:
    settlement_attempted: bool
    blocked_reason: str | None
    upstream_trace_refs: dict[str, Any] = field(default_factory=dict)
    settlement_notes: dict[str, Any] | None = None


@dataclass(frozen=True)
class FundSettlementBuildResult:
    result: FundSettlementResult | None
    trace: FundSettlementTrace


class FundSettlementEngine:
    """Phase 5.6 single-shot settlement boundary with deterministic policy gating."""

    def __init__(
        self,
        *,
        real_settlement_enabled: bool = False,
        transfer_executor: Callable[[str, float, str, str], str] | None = None,
    ) -> None:
        self._real_settlement_enabled = real_settlement_enabled
        self._transfer_executor = transfer_executor or _default_transfer_executor

    def settle(
        self,
        execution_input: FundSettlementExecutionInput,
        policy_input: FundSettlementPolicyInput,
    ) -> FundSettlementResult | None:
        return self.settle_with_trace(
            execution_input=execution_input,
            policy_input=policy_input,
        ).result

    def settle_with_trace(
        self,
        *,
        execution_input: FundSettlementExecutionInput,
        policy_input: FundSettlementPolicyInput,
    ) -> FundSettlementBuildResult:
        if not isinstance(execution_input, FundSettlementExecutionInput):
            return _blocked_build_result(
                blocked_reason=FUND_SETTLEMENT_BLOCK_INVALID_WALLET_CAPITAL_INPUT_CONTRACT,
                settlement_attempted=False,
                wallet_id=None,
                amount=None,
                currency=None,
                upstream_trace_refs={
                    "contract_errors": {
                        "execution_input": {
                            "expected_type": "FundSettlementExecutionInput",
                            "actual_type": type(execution_input).__name__,
                        }
                    }
                },
            )

        if not isinstance(policy_input, FundSettlementPolicyInput):
            return _blocked_build_result(
                blocked_reason=FUND_SETTLEMENT_BLOCK_INVALID_WALLET_CAPITAL_INPUT_CONTRACT,
                settlement_attempted=False,
                wallet_id=None,
                amount=None,
                currency=None,
                upstream_trace_refs={
                    "contract_errors": {
                        "policy_input": {
                            "expected_type": "FundSettlementPolicyInput",
                            "actual_type": type(policy_input).__name__,
                        }
                    }
                },
            )

        upstream_trace_refs: dict[str, Any] = {
            "execution_input": dict(execution_input.upstream_trace_refs),
            "policy_input": dict(policy_input.policy_trace_refs),
        }

        if not isinstance(execution_input.wallet_capital_result, WalletCapitalResult):
            return _blocked_build_result(
                blocked_reason=FUND_SETTLEMENT_BLOCK_INVALID_WALLET_CAPITAL_INPUT_CONTRACT,
                settlement_attempted=False,
                wallet_id=policy_input.wallet_id,
                amount=policy_input.amount,
                currency=policy_input.currency,
                upstream_trace_refs=upstream_trace_refs,
            )

        monitoring_result = None
        if execution_input.monitoring_required:
            if not isinstance(execution_input.monitoring_input, MonitoringContractInput):
                return _blocked_build_result(
                    blocked_reason=FUND_SETTLEMENT_BLOCK_MONITORING_EVALUATION_REQUIRED,
                    settlement_attempted=False,
                    wallet_id=policy_input.wallet_id,
                    amount=policy_input.amount,
                    currency=policy_input.currency,
                    upstream_trace_refs=upstream_trace_refs,
                )
            if execution_input.monitoring_circuit_breaker is not None and not isinstance(
                execution_input.monitoring_circuit_breaker,
                MonitoringCircuitBreaker,
            ):
                return _blocked_build_result(
                    blocked_reason=FUND_SETTLEMENT_BLOCK_MONITORING_EVALUATION_REQUIRED,
                    settlement_attempted=False,
                    wallet_id=policy_input.wallet_id,
                    amount=policy_input.amount,
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
                    blocked_reason=FUND_SETTLEMENT_HALT_MONITORING_ANOMALY,
                    settlement_attempted=False,
                    wallet_id=policy_input.wallet_id,
                    amount=policy_input.amount,
                    currency=policy_input.currency,
                    upstream_trace_refs=upstream_trace_refs,
                )
            if monitoring_result.decision == MONITORING_DECISION_BLOCK:
                return _blocked_build_result(
                    blocked_reason=FUND_SETTLEMENT_BLOCK_MONITORING_ANOMALY,
                    settlement_attempted=False,
                    wallet_id=policy_input.wallet_id,
                    amount=policy_input.amount,
                    currency=policy_input.currency,
                    upstream_trace_refs=upstream_trace_refs,
                )

        block_reason = _determine_blocked_reason(
            wallet_capital=execution_input.wallet_capital_result,
            policy_input=policy_input,
        )
        if block_reason is not None:
            return _blocked_build_result(
                blocked_reason=block_reason,
                settlement_attempted=False,
                wallet_id=policy_input.wallet_id,
                amount=policy_input.amount,
                currency=policy_input.currency,
                upstream_trace_refs=upstream_trace_refs,
            )

        balance_before = policy_input.balance_available
        balance_after = balance_before

        if not self._real_settlement_enabled:
            return FundSettlementBuildResult(
                result=FundSettlementResult(
                    settled=False,
                    success=True,
                    blocked_reason=None,
                    settlement_id=None,
                    wallet_id=policy_input.wallet_id,
                    amount=policy_input.amount,
                    currency=policy_input.currency,
                    transfer_reference=None,
                    settlement_status=FUND_SETTLEMENT_STATUS_SIMULATED,
                    balance_before=balance_before,
                    balance_after=balance_after,
                    simulated=True,
                    non_executing=True,
                ),
                trace=FundSettlementTrace(
                    settlement_attempted=True,
                    blocked_reason=None,
                    upstream_trace_refs=upstream_trace_refs,
                    settlement_notes={"settlement_mode": FUND_SETTLEMENT_STATUS_SIMULATED},
                ),
            )

        transfer_reference = self._transfer_executor(
            policy_input.wallet_id,
            policy_input.amount,
            policy_input.currency,
            policy_input.settlement_method,
        )
        settlement_id = _build_settlement_id(
            wallet_id=policy_input.wallet_id,
            amount=policy_input.amount,
            currency=policy_input.currency,
            method=policy_input.settlement_method,
            transfer_reference=transfer_reference,
        )
        balance_after = balance_before - policy_input.amount

        return FundSettlementBuildResult(
            result=FundSettlementResult(
                settled=True,
                success=True,
                blocked_reason=None,
                settlement_id=settlement_id,
                wallet_id=policy_input.wallet_id,
                amount=policy_input.amount,
                currency=policy_input.currency,
                transfer_reference=transfer_reference,
                settlement_status=FUND_SETTLEMENT_STATUS_COMPLETED,
                balance_before=balance_before,
                balance_after=balance_after,
                simulated=False,
                non_executing=False,
            ),
            trace=FundSettlementTrace(
                settlement_attempted=True,
                blocked_reason=None,
                upstream_trace_refs=upstream_trace_refs,
                settlement_notes={"settlement_mode": FUND_SETTLEMENT_STATUS_COMPLETED},
            ),
        )


def _determine_blocked_reason(
    *,
    wallet_capital: WalletCapitalResult,
    policy_input: FundSettlementPolicyInput,
) -> str | None:
    if wallet_capital.capital_authorized is not True:
        return FUND_SETTLEMENT_BLOCK_CAPITAL_NOT_AUTHORIZED

    if wallet_capital.success is not True:
        return FUND_SETTLEMENT_BLOCK_CAPITAL_NOT_AUTHORIZED

    if wallet_capital.simulated is True:
        return FUND_SETTLEMENT_BLOCK_CAPITAL_NOT_AUTHORIZED

    if policy_input.settlement_enabled is not True:
        return FUND_SETTLEMENT_BLOCK_SETTLEMENT_DISABLED

    if policy_input.allow_real_settlement is not True:
        return FUND_SETTLEMENT_BLOCK_REAL_SETTLEMENT_NOT_ALLOWED

    if policy_input.wallet_access_granted is not True:
        return FUND_SETTLEMENT_BLOCK_WALLET_ACCESS_DENIED

    if _normalize_text(policy_input.settlement_method) not in {
        _normalize_text(method) for method in policy_input.allowed_methods
    }:
        return FUND_SETTLEMENT_BLOCK_INVALID_SETTLEMENT_METHOD

    if policy_input.settlement_limits_enabled and policy_input.amount > policy_input.max_settlement_amount:
        return FUND_SETTLEMENT_BLOCK_SETTLEMENT_LIMIT_EXCEEDED

    if policy_input.balance_check_required and policy_input.balance_available < policy_input.amount:
        return FUND_SETTLEMENT_BLOCK_INSUFFICIENT_BALANCE

    if policy_input.final_confirmation_required and policy_input.final_confirmation_present is not True:
        return FUND_SETTLEMENT_BLOCK_FINAL_CONFIRMATION_MISSING

    if policy_input.irreversible_ack_required and policy_input.irreversible_ack_present is not True:
        return FUND_SETTLEMENT_BLOCK_IRREVERSIBLE_ACK_MISSING

    if policy_input.audit_required and policy_input.audit_attached is not True:
        return FUND_SETTLEMENT_BLOCK_AUDIT_MISSING

    return None


def _blocked_build_result(
    *,
    blocked_reason: str,
    settlement_attempted: bool,
    wallet_id: str | None,
    amount: float | None,
    currency: str | None,
    upstream_trace_refs: dict[str, Any],
) -> FundSettlementBuildResult:
    return FundSettlementBuildResult(
        result=FundSettlementResult(
            settled=False,
            success=False,
            blocked_reason=blocked_reason,
            settlement_id=None,
            wallet_id=wallet_id,
            amount=amount,
            currency=currency,
            transfer_reference=None,
            settlement_status=FUND_SETTLEMENT_STATUS_BLOCKED,
            balance_before=None,
            balance_after=None,
            simulated=True,
            non_executing=True,
        ),
        trace=FundSettlementTrace(
            settlement_attempted=settlement_attempted,
            blocked_reason=blocked_reason,
            upstream_trace_refs=upstream_trace_refs,
            settlement_notes={"blocked_reason": blocked_reason},
        ),
    )


def _build_settlement_id(
    *,
    wallet_id: str,
    amount: float,
    currency: str,
    method: str,
    transfer_reference: str,
) -> str:
    digest = hashlib.sha256(
        f"{wallet_id}|{amount:.8f}|{currency.upper()}|{method.upper()}|{transfer_reference}".encode("utf-8")
    ).hexdigest()[:16]
    return f"SETTLE-{digest.upper()}"


def _default_transfer_executor(wallet_id: str, amount: float, currency: str, settlement_method: str) -> str:
    return (
        f"TRANSFER::{wallet_id}::{amount:.8f}::{currency.upper()}::{settlement_method.upper()}"
    )


def _normalize_text(value: str) -> str:
    return value.strip().upper()
