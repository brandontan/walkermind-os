from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
from urllib import error, parse, request

from .monitoring_circuit_breaker import (
    MONITORING_DECISION_ALLOW,
    MONITORING_DECISION_BLOCK,
    MONITORING_DECISION_HALT,
    MonitoringCircuitBreaker,
    MonitoringContractInput,
)
from .execution_transport import ExecutionTransportResult

EXCHANGE_NETWORK_MODE_REAL = "REAL"
EXCHANGE_NETWORK_MODE_SIMULATED = "SIMULATED"

EXCHANGE_EXECUTION_BLOCK_INVALID_TRANSPORT_INPUT_CONTRACT = "invalid_transport_input_contract"
EXCHANGE_EXECUTION_BLOCK_INVALID_POLICY_INPUT_CONTRACT = "invalid_policy_input_contract"
EXCHANGE_EXECUTION_BLOCK_TRANSPORT_NOT_SUBMITTED = "transport_not_submitted"
EXCHANGE_EXECUTION_BLOCK_SIMULATED_TRANSPORT = "simulated_transport_block"
EXCHANGE_EXECUTION_BLOCK_NETWORK_DISABLED = "network_disabled"
EXCHANGE_EXECUTION_BLOCK_REAL_NETWORK_NOT_ALLOWED = "real_network_not_allowed"
EXCHANGE_EXECUTION_BLOCK_INVALID_ENDPOINT = "invalid_endpoint"
EXCHANGE_EXECUTION_BLOCK_INVALID_HTTP_METHOD = "invalid_http_method"
EXCHANGE_EXECUTION_BLOCK_SIGNING_REQUIRED_MISSING = "signing_required_missing"
EXCHANGE_EXECUTION_BLOCK_ENVIRONMENT_NOT_ALLOWED = "environment_not_allowed"
EXCHANGE_EXECUTION_BLOCK_MONITORING_EVALUATION_REQUIRED = "monitoring_evaluation_required"
EXCHANGE_EXECUTION_BLOCK_MONITORING_ANOMALY = "monitoring_anomaly_block"
EXCHANGE_EXECUTION_HALT_MONITORING_ANOMALY = "monitoring_anomaly_halt"

_ALLOWED_HTTP_METHODS = {"POST", "PUT"}


@dataclass(frozen=True)
class ExchangeExecutionTransportInput:
    transport_result: ExecutionTransportResult
    monitoring_input: MonitoringContractInput | None = None
    monitoring_circuit_breaker: MonitoringCircuitBreaker | None = None
    monitoring_required: bool = False
    upstream_trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExchangeExecutionPolicyInput:
    network_enabled: bool
    allow_real_network: bool
    endpoint_url: str
    http_method: str
    signing_required: bool
    signing_key_present: bool
    signing_scheme: str
    wallet_reference: str | None
    request_timeout_ms: int
    allow_testnet: bool
    environment: str
    allowed_environments: list[str]
    policy_trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExchangeExecutionResult:
    executed: bool
    success: bool
    blocked_reason: str | None
    execution_id: str | None
    request_payload: dict[str, Any] | None
    signed_payload: dict[str, Any] | None
    exchange_response: dict[str, Any] | None
    network_used: str
    signing_used: bool
    simulated: bool
    non_executing: bool


@dataclass(frozen=True)
class ExchangeExecutionTrace:
    execution_attempted: bool
    blocked_reason: str | None
    upstream_trace_refs: dict[str, Any] = field(default_factory=dict)
    exchange_notes: dict[str, Any] | None = None


@dataclass(frozen=True)
class ExchangeExecutionBuildResult:
    result: ExchangeExecutionResult | None
    trace: ExchangeExecutionTrace


class ExchangeIntegration:
    """Phase 5.3 network + signing boundary with strict deterministic gates."""

    def __init__(
        self,
        *,
        real_network_enabled: bool = False,
        requester: Callable[[str, str, dict[str, Any], int], dict[str, Any]] | None = None,
    ) -> None:
        self._real_network_enabled = real_network_enabled
        self._requester = requester or _default_http_requester

    def execute(
        self,
        transport_input: ExchangeExecutionTransportInput,
        policy_input: ExchangeExecutionPolicyInput,
    ) -> ExchangeExecutionResult | None:
        return self.execute_with_trace(
            transport_input=transport_input,
            policy_input=policy_input,
        ).result

    def execute_with_trace(
        self,
        *,
        transport_input: ExchangeExecutionTransportInput,
        policy_input: ExchangeExecutionPolicyInput,
    ) -> ExchangeExecutionBuildResult:
        if not isinstance(transport_input, ExchangeExecutionTransportInput):
            return _blocked_build_result(
                blocked_reason=EXCHANGE_EXECUTION_BLOCK_INVALID_TRANSPORT_INPUT_CONTRACT,
                execution_attempted=False,
                network_used=EXCHANGE_NETWORK_MODE_SIMULATED,
                upstream_trace_refs={
                    "contract_errors": {
                        "transport_input": {
                            "expected_type": "ExchangeExecutionTransportInput",
                            "actual_type": type(transport_input).__name__,
                        }
                    }
                },
            )

        if not isinstance(policy_input, ExchangeExecutionPolicyInput):
            return _blocked_build_result(
                blocked_reason=EXCHANGE_EXECUTION_BLOCK_INVALID_POLICY_INPUT_CONTRACT,
                execution_attempted=False,
                network_used=EXCHANGE_NETWORK_MODE_SIMULATED,
                upstream_trace_refs={
                    "transport_input": dict(transport_input.upstream_trace_refs),
                    "contract_errors": {
                        "policy_input": {
                            "expected_type": "ExchangeExecutionPolicyInput",
                            "actual_type": type(policy_input).__name__,
                        }
                    },
                },
            )

        upstream_trace_refs: dict[str, Any] = {
            "transport_input": dict(transport_input.upstream_trace_refs),
            "policy_input": dict(policy_input.policy_trace_refs),
        }

        transport_error = _validate_transport_input(transport_input)
        if transport_error is not None:
            return _blocked_build_result(
                blocked_reason=EXCHANGE_EXECUTION_BLOCK_INVALID_TRANSPORT_INPUT_CONTRACT,
                execution_attempted=False,
                network_used=EXCHANGE_NETWORK_MODE_SIMULATED,
                upstream_trace_refs={**upstream_trace_refs, "transport_error": transport_error},
            )

        policy_error = _validate_policy_input(policy_input)
        if policy_error is not None:
            return _blocked_build_result(
                blocked_reason=EXCHANGE_EXECUTION_BLOCK_INVALID_POLICY_INPUT_CONTRACT,
                execution_attempted=False,
                network_used=EXCHANGE_NETWORK_MODE_SIMULATED,
                upstream_trace_refs={**upstream_trace_refs, "policy_error": policy_error},
            )

        if transport_input.transport_result.submitted is not True:
            return _blocked_build_result(
                blocked_reason=EXCHANGE_EXECUTION_BLOCK_TRANSPORT_NOT_SUBMITTED,
                execution_attempted=False,
                network_used=EXCHANGE_NETWORK_MODE_SIMULATED,
                upstream_trace_refs=upstream_trace_refs,
            )

        if transport_input.transport_result.simulated is True:
            return _blocked_build_result(
                blocked_reason=EXCHANGE_EXECUTION_BLOCK_SIMULATED_TRANSPORT,
                execution_attempted=False,
                network_used=EXCHANGE_NETWORK_MODE_SIMULATED,
                upstream_trace_refs=upstream_trace_refs,
            )

        monitoring_result = None
        if transport_input.monitoring_required:
            if not isinstance(transport_input.monitoring_input, MonitoringContractInput):
                return _blocked_build_result(
                    blocked_reason=EXCHANGE_EXECUTION_BLOCK_MONITORING_EVALUATION_REQUIRED,
                    execution_attempted=False,
                    network_used=EXCHANGE_NETWORK_MODE_SIMULATED,
                    upstream_trace_refs={
                        **upstream_trace_refs,
                        "contract_errors": {
                            "monitoring_input": {
                                "expected_type": "MonitoringContractInput",
                                "actual_type": type(transport_input.monitoring_input).__name__,
                            }
                        },
                    },
                )
            if transport_input.monitoring_circuit_breaker is not None and not isinstance(
                transport_input.monitoring_circuit_breaker,
                MonitoringCircuitBreaker,
            ):
                return _blocked_build_result(
                    blocked_reason=EXCHANGE_EXECUTION_BLOCK_MONITORING_EVALUATION_REQUIRED,
                    execution_attempted=False,
                    network_used=EXCHANGE_NETWORK_MODE_SIMULATED,
                    upstream_trace_refs={
                        **upstream_trace_refs,
                        "contract_errors": {
                            "monitoring_circuit_breaker": {
                                "expected_type": "MonitoringCircuitBreaker",
                                "actual_type": type(transport_input.monitoring_circuit_breaker).__name__,
                            }
                        },
                    },
                )

            breaker = transport_input.monitoring_circuit_breaker or MonitoringCircuitBreaker()
            monitoring_result = breaker.evaluate(transport_input.monitoring_input)
            upstream_trace_refs["monitoring"] = {
                "decision": monitoring_result.decision,
                "primary_anomaly": monitoring_result.primary_anomaly,
                "anomalies": list(monitoring_result.anomalies),
                "eval_ref": monitoring_result.event.eval_ref,
            }
            if monitoring_result.decision == MONITORING_DECISION_HALT:
                return _blocked_build_result(
                    blocked_reason=EXCHANGE_EXECUTION_HALT_MONITORING_ANOMALY,
                    execution_attempted=False,
                    network_used=EXCHANGE_NETWORK_MODE_SIMULATED,
                    upstream_trace_refs=upstream_trace_refs,
                )
            if monitoring_result.decision == MONITORING_DECISION_BLOCK:
                return _blocked_build_result(
                    blocked_reason=EXCHANGE_EXECUTION_BLOCK_MONITORING_ANOMALY,
                    execution_attempted=False,
                    network_used=EXCHANGE_NETWORK_MODE_SIMULATED,
                    upstream_trace_refs=upstream_trace_refs,
                )

        if policy_input.network_enabled is not True:
            return _blocked_build_result(
                blocked_reason=EXCHANGE_EXECUTION_BLOCK_NETWORK_DISABLED,
                execution_attempted=False,
                network_used=EXCHANGE_NETWORK_MODE_SIMULATED,
                upstream_trace_refs=upstream_trace_refs,
            )

        if policy_input.allow_real_network is not True:
            return _blocked_build_result(
                blocked_reason=EXCHANGE_EXECUTION_BLOCK_REAL_NETWORK_NOT_ALLOWED,
                execution_attempted=False,
                network_used=EXCHANGE_NETWORK_MODE_SIMULATED,
                upstream_trace_refs=upstream_trace_refs,
            )

        if not _is_valid_endpoint(policy_input.endpoint_url):
            return _blocked_build_result(
                blocked_reason=EXCHANGE_EXECUTION_BLOCK_INVALID_ENDPOINT,
                execution_attempted=False,
                network_used=EXCHANGE_NETWORK_MODE_SIMULATED,
                upstream_trace_refs=upstream_trace_refs,
            )

        if _normalize_text(policy_input.http_method) not in _ALLOWED_HTTP_METHODS:
            return _blocked_build_result(
                blocked_reason=EXCHANGE_EXECUTION_BLOCK_INVALID_HTTP_METHOD,
                execution_attempted=False,
                network_used=EXCHANGE_NETWORK_MODE_SIMULATED,
                upstream_trace_refs=upstream_trace_refs,
            )

        if policy_input.signing_required and policy_input.signing_key_present is not True:
            return _blocked_build_result(
                blocked_reason=EXCHANGE_EXECUTION_BLOCK_SIGNING_REQUIRED_MISSING,
                execution_attempted=False,
                network_used=EXCHANGE_NETWORK_MODE_SIMULATED,
                upstream_trace_refs=upstream_trace_refs,
            )

        if _normalize_text(policy_input.environment) not in {
            _normalize_text(env) for env in policy_input.allowed_environments
        }:
            return _blocked_build_result(
                blocked_reason=EXCHANGE_EXECUTION_BLOCK_ENVIRONMENT_NOT_ALLOWED,
                execution_attempted=False,
                network_used=EXCHANGE_NETWORK_MODE_SIMULATED,
                upstream_trace_refs=upstream_trace_refs,
            )

        if not policy_input.allow_testnet and _is_testnet_target(policy_input):
            return _blocked_build_result(
                blocked_reason=EXCHANGE_EXECUTION_BLOCK_ENVIRONMENT_NOT_ALLOWED,
                execution_attempted=False,
                network_used=EXCHANGE_NETWORK_MODE_SIMULATED,
                upstream_trace_refs=upstream_trace_refs,
            )

        request_payload = _build_request_payload(transport_input, policy_input)
        signed_payload = _build_signed_payload(request_payload, policy_input)

        if not self._real_network_enabled:
            return ExchangeExecutionBuildResult(
                result=ExchangeExecutionResult(
                    executed=True,
                    success=True,
                    blocked_reason=None,
                    execution_id=_execution_id_from_payload(signed_payload),
                    request_payload=request_payload,
                    signed_payload=signed_payload,
                    exchange_response={"status": "SIMULATED_NETWORK_OK", "real_http": False},
                    network_used=EXCHANGE_NETWORK_MODE_SIMULATED,
                    signing_used=policy_input.signing_required,
                    simulated=True,
                    non_executing=True,
                ),
                trace=ExchangeExecutionTrace(
                    execution_attempted=True,
                    blocked_reason=None,
                    upstream_trace_refs=upstream_trace_refs,
                    exchange_notes={
                        "network_mode": EXCHANGE_NETWORK_MODE_SIMULATED,
                        "monitoring_decision": (
                            monitoring_result.decision
                            if monitoring_result is not None
                            else MONITORING_DECISION_ALLOW
                        ),
                    },
                ),
            )

        response = self._requester(
            policy_input.endpoint_url,
            _normalize_text(policy_input.http_method),
            signed_payload,
            policy_input.request_timeout_ms,
        )

        return ExchangeExecutionBuildResult(
            result=ExchangeExecutionResult(
                executed=True,
                success=True,
                blocked_reason=None,
                execution_id=_execution_id_from_payload(signed_payload),
                request_payload=request_payload,
                signed_payload=signed_payload,
                exchange_response=response,
                network_used=policy_input.endpoint_url,
                signing_used=policy_input.signing_required,
                simulated=False,
                non_executing=False,
            ),
            trace=ExchangeExecutionTrace(
                execution_attempted=True,
                blocked_reason=None,
                upstream_trace_refs=upstream_trace_refs,
                exchange_notes={
                    "network_mode": EXCHANGE_NETWORK_MODE_REAL,
                    "monitoring_decision": (
                        monitoring_result.decision
                        if monitoring_result is not None
                        else MONITORING_DECISION_ALLOW
                    ),
                },
            ),
        )


def _blocked_build_result(
    *,
    blocked_reason: str,
    execution_attempted: bool,
    network_used: str,
    upstream_trace_refs: dict[str, Any],
) -> ExchangeExecutionBuildResult:
    return ExchangeExecutionBuildResult(
        result=ExchangeExecutionResult(
            executed=False,
            success=False,
            blocked_reason=blocked_reason,
            execution_id=None,
            request_payload=None,
            signed_payload=None,
            exchange_response=None,
            network_used=network_used,
            signing_used=False,
            simulated=True,
            non_executing=True,
        ),
        trace=ExchangeExecutionTrace(
            execution_attempted=execution_attempted,
            blocked_reason=blocked_reason,
            upstream_trace_refs=upstream_trace_refs,
            exchange_notes={"blocked_reason": blocked_reason},
        ),
    )


def _validate_transport_input(transport_input: ExchangeExecutionTransportInput) -> dict[str, Any] | None:
    if not isinstance(transport_input.transport_result, ExecutionTransportResult):
        return {
            "field": "transport_result",
            "expected_type": "ExecutionTransportResult",
            "actual_type": type(transport_input.transport_result).__name__,
        }

    if not isinstance(transport_input.upstream_trace_refs, dict):
        return {
            "field": "upstream_trace_refs",
            "expected_type": "dict",
            "actual_type": type(transport_input.upstream_trace_refs).__name__,
        }
    if transport_input.monitoring_input is not None and not isinstance(
        transport_input.monitoring_input,
        MonitoringContractInput,
    ):
        return {
            "field": "monitoring_input",
            "expected_type": "MonitoringContractInput|None",
            "actual_type": type(transport_input.monitoring_input).__name__,
        }
    if transport_input.monitoring_circuit_breaker is not None and not isinstance(
        transport_input.monitoring_circuit_breaker,
        MonitoringCircuitBreaker,
    ):
        return {
            "field": "monitoring_circuit_breaker",
            "expected_type": "MonitoringCircuitBreaker|None",
            "actual_type": type(transport_input.monitoring_circuit_breaker).__name__,
        }
    if not isinstance(transport_input.monitoring_required, bool):
        return {
            "field": "monitoring_required",
            "expected_type": "bool",
            "actual_type": type(transport_input.monitoring_required).__name__,
        }

    return None


def _validate_policy_input(policy_input: ExchangeExecutionPolicyInput) -> dict[str, Any] | None:
    if not isinstance(policy_input.policy_trace_refs, dict):
        return {
            "field": "policy_trace_refs",
            "expected_type": "dict",
            "actual_type": type(policy_input.policy_trace_refs).__name__,
        }

    if not isinstance(policy_input.allowed_environments, list):
        return {
            "field": "allowed_environments",
            "expected_type": "list[str]",
            "actual_type": type(policy_input.allowed_environments).__name__,
        }

    if policy_input.request_timeout_ms <= 0:
        return {"field": "request_timeout_ms", "constraint": "must_be_positive"}

    return None


def _build_request_payload(
    transport_input: ExchangeExecutionTransportInput,
    policy_input: ExchangeExecutionPolicyInput,
) -> dict[str, Any]:
    transport_request = transport_input.transport_result.request_payload or {}
    return {
        "execution_id": transport_request.get("execution_id") or transport_request.get("client_order_id") or "EXE-5-3",
        "request": dict(transport_request),
        "wallet_reference": policy_input.wallet_reference,
        "environment": policy_input.environment,
    }


def _build_signed_payload(request_payload: dict[str, Any], policy_input: ExchangeExecutionPolicyInput) -> dict[str, Any]:
    if not policy_input.signing_required:
        return dict(request_payload)

    return {
        **request_payload,
        "signing": {
            "scheme": policy_input.signing_scheme,
            "signature_ref": "SIGNATURE_PLACEHOLDER",
        },
    }


def _execution_id_from_payload(payload: dict[str, Any]) -> str:
    return str(payload.get("execution_id") or "EXE-5-3")


def _normalize_text(value: str) -> str:
    return value.strip().upper()


def _is_valid_endpoint(endpoint_url: str) -> bool:
    parsed = parse.urlparse(endpoint_url)
    return bool(parsed.scheme in {"http", "https"} and parsed.netloc)


def _is_testnet_target(policy_input: ExchangeExecutionPolicyInput) -> bool:
    env = _normalize_text(policy_input.environment)
    hostname = parse.urlparse(policy_input.endpoint_url).hostname or ""
    host_upper = hostname.upper()
    return "TEST" in env or "TEST" in host_upper


def _default_http_requester(
    endpoint_url: str,
    method: str,
    payload: dict[str, Any],
    timeout_ms: int,
) -> dict[str, Any]:
    req = request.Request(
        endpoint_url,
        data=str(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method=method,
    )

    try:
        with request.urlopen(req, timeout=timeout_ms / 1000) as resp:
            body = resp.read().decode("utf-8")
            return {
                "http_status": getattr(resp, "status", 200),
                "body": body,
            }
    except error.HTTPError as exc:
        return {
            "http_status": exc.code,
            "error": "http_error",
            "reason": str(exc),
        }
    except error.URLError as exc:
        return {
            "http_status": None,
            "error": "network_error",
            "reason": str(exc.reason),
        }
