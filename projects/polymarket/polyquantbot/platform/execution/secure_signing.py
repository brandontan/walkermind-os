from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Callable

from .exchange_integration import ExchangeExecutionResult
from .monitoring_circuit_breaker import (
    MONITORING_DECISION_BLOCK,
    MONITORING_DECISION_HALT,
    MonitoringCircuitBreaker,
    MonitoringContractInput,
)

SIGNING_METHOD_REAL = "REAL_SIGNING"
SIGNING_METHOD_SIMULATED = "SIMULATED_SIGNING"

SIGNING_BLOCK_INVALID_EXCHANGE_INPUT_CONTRACT = "invalid_exchange_input_contract"
SIGNING_BLOCK_SIGNING_DISABLED = "signing_disabled"
SIGNING_BLOCK_REAL_SIGNING_NOT_ALLOWED = "real_signing_not_allowed"
SIGNING_BLOCK_INVALID_SIGNING_SCHEME = "invalid_signing_scheme"
SIGNING_BLOCK_KEY_REGISTRY_DISABLED = "key_registry_disabled"
SIGNING_BLOCK_KEY_NOT_REGISTERED = "key_not_registered"
SIGNING_BLOCK_KEY_ACCESS_DENIED = "key_access_denied"
SIGNING_BLOCK_AUDIT_MISSING = "audit_missing"
SIGNING_BLOCK_OPERATOR_APPROVAL_MISSING = "operator_approval_missing"
SIGNING_BLOCK_MONITORING_EVALUATION_REQUIRED = "monitoring_evaluation_required"
SIGNING_BLOCK_MONITORING_ANOMALY = "monitoring_anomaly_block"
SIGNING_HALT_MONITORING_ANOMALY = "monitoring_anomaly_halt"


@dataclass(frozen=True)
class SigningExecutionInput:
    exchange_result: ExchangeExecutionResult
    monitoring_input: MonitoringContractInput | None = None
    monitoring_circuit_breaker: MonitoringCircuitBreaker | None = None
    monitoring_required: bool = False
    upstream_trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SigningPolicyInput:
    signing_enabled: bool
    allow_real_signing: bool
    signing_scheme: str
    allowed_schemes: list[str]
    key_reference: str
    key_registry_enabled: bool
    key_registered: bool
    key_access_granted: bool
    allow_external_signer: bool
    external_signer_used: bool
    simulated_signing_force: bool
    audit_required: bool
    audit_attached: bool
    operator_approval_required: bool
    operator_approval_present: bool
    policy_trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SigningResult:
    signed: bool
    success: bool
    blocked_reason: str | None
    signature: str | None
    payload_hash: str | None
    signing_scheme: str
    key_reference: str | None
    signing_method: str
    simulated: bool
    non_executing: bool


@dataclass(frozen=True)
class SigningTrace:
    signing_attempted: bool
    blocked_reason: str | None
    upstream_trace_refs: dict[str, Any] = field(default_factory=dict)
    signing_notes: dict[str, Any] | None = None


@dataclass(frozen=True)
class SigningBuildResult:
    result: SigningResult | None
    trace: SigningTrace


class SecureSigningEngine:
    """Phase 5.4 signing boundary enforcing explicit policy gates."""

    def __init__(
        self,
        *,
        real_signing_enabled: bool = False,
        signer: Callable[[str, str, str], str] | None = None,
    ) -> None:
        self._real_signing_enabled = real_signing_enabled
        self._signer = signer or _default_signer

    def sign(
        self,
        signing_input: SigningExecutionInput,
        policy_input: SigningPolicyInput,
    ) -> SigningResult | None:
        return self.sign_with_trace(
            signing_input=signing_input,
            policy_input=policy_input,
        ).result

    def sign_with_trace(
        self,
        *,
        signing_input: SigningExecutionInput,
        policy_input: SigningPolicyInput,
    ) -> SigningBuildResult:
        if not isinstance(signing_input, SigningExecutionInput):
            return _blocked_build_result(
                blocked_reason=SIGNING_BLOCK_INVALID_EXCHANGE_INPUT_CONTRACT,
                signing_attempted=False,
                signing_scheme="UNKNOWN",
                key_reference=None,
                upstream_trace_refs={
                    "contract_errors": {
                        "signing_input": {
                            "expected_type": "SigningExecutionInput",
                            "actual_type": type(signing_input).__name__,
                        }
                    }
                },
            )

        if not isinstance(policy_input, SigningPolicyInput):
            return _blocked_build_result(
                blocked_reason=SIGNING_BLOCK_INVALID_EXCHANGE_INPUT_CONTRACT,
                signing_attempted=False,
                signing_scheme="UNKNOWN",
                key_reference=None,
                upstream_trace_refs={
                    "contract_errors": {
                        "policy_input": {
                            "expected_type": "SigningPolicyInput",
                            "actual_type": type(policy_input).__name__,
                        }
                    }
                },
            )

        upstream_trace_refs: dict[str, Any] = {
            "execution_input": dict(signing_input.upstream_trace_refs),
            "policy_input": dict(policy_input.policy_trace_refs),
        }

        validation_error = _validate_input_contracts(signing_input, policy_input)
        if validation_error is not None:
            return _blocked_build_result(
                blocked_reason=SIGNING_BLOCK_INVALID_EXCHANGE_INPUT_CONTRACT,
                signing_attempted=False,
                signing_scheme=policy_input.signing_scheme,
                key_reference=policy_input.key_reference,
                upstream_trace_refs={**upstream_trace_refs, "validation_error": validation_error},
            )

        if signing_input.monitoring_required:
            if not isinstance(signing_input.monitoring_input, MonitoringContractInput):
                return _blocked_build_result(
                    blocked_reason=SIGNING_BLOCK_MONITORING_EVALUATION_REQUIRED,
                    signing_attempted=False,
                    signing_scheme=policy_input.signing_scheme,
                    key_reference=policy_input.key_reference,
                    upstream_trace_refs={
                        **upstream_trace_refs,
                        "contract_errors": {
                            "monitoring_input": {
                                "expected_type": "MonitoringContractInput",
                                "actual_type": type(signing_input.monitoring_input).__name__,
                            }
                        },
                    },
                )
            if signing_input.monitoring_circuit_breaker is not None and not isinstance(
                signing_input.monitoring_circuit_breaker,
                MonitoringCircuitBreaker,
            ):
                return _blocked_build_result(
                    blocked_reason=SIGNING_BLOCK_MONITORING_EVALUATION_REQUIRED,
                    signing_attempted=False,
                    signing_scheme=policy_input.signing_scheme,
                    key_reference=policy_input.key_reference,
                    upstream_trace_refs={
                        **upstream_trace_refs,
                        "contract_errors": {
                            "monitoring_circuit_breaker": {
                                "expected_type": "MonitoringCircuitBreaker",
                                "actual_type": type(signing_input.monitoring_circuit_breaker).__name__,
                            }
                        },
                    },
                )

            breaker = signing_input.monitoring_circuit_breaker or MonitoringCircuitBreaker()
            monitoring_result = breaker.evaluate(signing_input.monitoring_input)
            upstream_trace_refs["monitoring"] = {
                "decision": monitoring_result.decision,
                "primary_anomaly": monitoring_result.primary_anomaly,
                "anomalies": list(monitoring_result.anomalies),
                "eval_ref": monitoring_result.event.eval_ref,
            }

            if monitoring_result.decision == MONITORING_DECISION_HALT:
                return _blocked_build_result(
                    blocked_reason=SIGNING_HALT_MONITORING_ANOMALY,
                    signing_attempted=False,
                    signing_scheme=policy_input.signing_scheme,
                    key_reference=policy_input.key_reference,
                    upstream_trace_refs=upstream_trace_refs,
                )
            if monitoring_result.decision == MONITORING_DECISION_BLOCK:
                return _blocked_build_result(
                    blocked_reason=SIGNING_BLOCK_MONITORING_ANOMALY,
                    signing_attempted=False,
                    signing_scheme=policy_input.signing_scheme,
                    key_reference=policy_input.key_reference,
                    upstream_trace_refs=upstream_trace_refs,
                )

        block_reason = _determine_blocked_reason(signing_input.exchange_result, policy_input)
        if block_reason is not None:
            return _blocked_build_result(
                blocked_reason=block_reason,
                signing_attempted=False,
                signing_scheme=policy_input.signing_scheme,
                key_reference=policy_input.key_reference,
                upstream_trace_refs=upstream_trace_refs,
            )

        payload_hash = _build_payload_hash(signing_input.exchange_result)

        if policy_input.simulated_signing_force or not self._real_signing_enabled:
            return SigningBuildResult(
                result=SigningResult(
                    signed=True,
                    success=True,
                    blocked_reason=None,
                    signature="SIMULATED_SIGNATURE",
                    payload_hash=payload_hash,
                    signing_scheme=policy_input.signing_scheme,
                    key_reference=policy_input.key_reference,
                    signing_method=SIGNING_METHOD_SIMULATED,
                    simulated=True,
                    non_executing=True,
                ),
                trace=SigningTrace(
                    signing_attempted=True,
                    blocked_reason=None,
                    upstream_trace_refs=upstream_trace_refs,
                    signing_notes={"signing_mode": SIGNING_METHOD_SIMULATED},
                ),
            )

        signature = self._signer(payload_hash, policy_input.signing_scheme, policy_input.key_reference)
        return SigningBuildResult(
            result=SigningResult(
                signed=True,
                success=True,
                blocked_reason=None,
                signature=signature,
                payload_hash=payload_hash,
                signing_scheme=policy_input.signing_scheme,
                key_reference=policy_input.key_reference,
                signing_method=SIGNING_METHOD_REAL,
                simulated=False,
                non_executing=False,
            ),
            trace=SigningTrace(
                signing_attempted=True,
                blocked_reason=None,
                upstream_trace_refs=upstream_trace_refs,
                signing_notes={
                    "signing_mode": SIGNING_METHOD_REAL,
                    "external_signer_used": policy_input.external_signer_used,
                },
            ),
        )


def _determine_blocked_reason(
    exchange_result: ExchangeExecutionResult,
    policy_input: SigningPolicyInput,
) -> str | None:
    if exchange_result.executed is not True or exchange_result.success is not True:
        return SIGNING_BLOCK_INVALID_EXCHANGE_INPUT_CONTRACT

    if exchange_result.simulated is True:
        return SIGNING_BLOCK_INVALID_EXCHANGE_INPUT_CONTRACT

    if policy_input.signing_enabled is not True:
        return SIGNING_BLOCK_SIGNING_DISABLED

    if policy_input.allow_real_signing is not True:
        return SIGNING_BLOCK_REAL_SIGNING_NOT_ALLOWED

    if _normalize_text(policy_input.signing_scheme) not in {
        _normalize_text(scheme) for scheme in policy_input.allowed_schemes
    }:
        return SIGNING_BLOCK_INVALID_SIGNING_SCHEME

    if policy_input.key_registry_enabled is not True:
        return SIGNING_BLOCK_KEY_REGISTRY_DISABLED

    if policy_input.key_registered is not True:
        return SIGNING_BLOCK_KEY_NOT_REGISTERED

    if policy_input.key_access_granted is not True:
        return SIGNING_BLOCK_KEY_ACCESS_DENIED

    if policy_input.audit_required and policy_input.audit_attached is not True:
        return SIGNING_BLOCK_AUDIT_MISSING

    if policy_input.operator_approval_required and policy_input.operator_approval_present is not True:
        return SIGNING_BLOCK_OPERATOR_APPROVAL_MISSING

    if policy_input.external_signer_used and policy_input.allow_external_signer is not True:
        return SIGNING_BLOCK_REAL_SIGNING_NOT_ALLOWED

    return None


def _blocked_build_result(
    *,
    blocked_reason: str,
    signing_attempted: bool,
    signing_scheme: str,
    key_reference: str | None,
    upstream_trace_refs: dict[str, Any],
) -> SigningBuildResult:
    return SigningBuildResult(
        result=SigningResult(
            signed=False,
            success=False,
            blocked_reason=blocked_reason,
            signature=None,
            payload_hash=None,
            signing_scheme=signing_scheme,
            key_reference=key_reference,
            signing_method=SIGNING_METHOD_SIMULATED,
            simulated=True,
            non_executing=True,
        ),
        trace=SigningTrace(
            signing_attempted=signing_attempted,
            blocked_reason=blocked_reason,
            upstream_trace_refs=upstream_trace_refs,
            signing_notes={"blocked_reason": blocked_reason},
        ),
    )


def _validate_input_contracts(
    signing_input: SigningExecutionInput,
    policy_input: SigningPolicyInput,
) -> dict[str, Any] | None:
    if not isinstance(signing_input.exchange_result, ExchangeExecutionResult):
        return {
            "field": "exchange_result",
            "expected_type": "ExchangeExecutionResult",
            "actual_type": type(signing_input.exchange_result).__name__,
        }

    if not isinstance(signing_input.upstream_trace_refs, dict):
        return {
            "field": "upstream_trace_refs",
            "expected_type": "dict",
            "actual_type": type(signing_input.upstream_trace_refs).__name__,
        }

    if not isinstance(policy_input.allowed_schemes, list):
        return {
            "field": "allowed_schemes",
            "expected_type": "list[str]",
            "actual_type": type(policy_input.allowed_schemes).__name__,
        }

    if not isinstance(policy_input.policy_trace_refs, dict):
        return {
            "field": "policy_trace_refs",
            "expected_type": "dict",
            "actual_type": type(policy_input.policy_trace_refs).__name__,
        }

    return None


def _build_payload_hash(exchange_result: ExchangeExecutionResult) -> str:
    payload: dict[str, Any] = exchange_result.signed_payload or exchange_result.request_payload or {}
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()


def _normalize_text(value: str) -> str:
    return value.strip().upper()


def _default_signer(payload_hash: str, signing_scheme: str, key_reference: str) -> str:
    signature_input = f"{signing_scheme}:{key_reference}:{payload_hash}"
    signature_hex = hashlib.sha256(signature_input.encode("utf-8")).hexdigest()
    return f"sig_{signature_hex}"
