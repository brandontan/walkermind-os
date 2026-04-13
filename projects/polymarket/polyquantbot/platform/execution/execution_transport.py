from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .execution_gateway import ExecutionGatewayResult
from .execution_mode_controller import MODE_LIVE
from .live_execution_authorizer import LiveExecutionAuthorizationDecision

EXECUTION_TRANSPORT_MODE_REAL = "REAL"
EXECUTION_TRANSPORT_MODE_SIMULATED = "SIMULATED"

EXECUTION_TRANSPORT_BLOCK_INVALID_AUTHORIZATION_INPUT_CONTRACT = "invalid_authorization_input_contract"
EXECUTION_TRANSPORT_BLOCK_INVALID_POLICY_INPUT_CONTRACT = "invalid_policy_input_contract"
EXECUTION_TRANSPORT_BLOCK_AUTHORIZATION_REQUIRED = "authorization_required"
EXECUTION_TRANSPORT_BLOCK_TRANSPORT_DISABLED = "transport_disabled"
EXECUTION_TRANSPORT_BLOCK_REAL_SUBMISSION_NOT_ALLOWED = "real_submission_not_allowed"
EXECUTION_TRANSPORT_BLOCK_INVALID_EXECUTION_MODE = "invalid_execution_mode"
EXECUTION_TRANSPORT_BLOCK_DRY_RUN_FORCED = "dry_run_forced"
EXECUTION_TRANSPORT_BLOCK_MULTIPLE_ORDERS_NOT_ALLOWED = "multiple_orders_not_allowed"
EXECUTION_TRANSPORT_BLOCK_IDEMPOTENCY_REQUIRED = "idempotency_required"
EXECUTION_TRANSPORT_BLOCK_AUDIT_LOG_MISSING = "audit_log_missing"
EXECUTION_TRANSPORT_BLOCK_OPERATOR_CONFIRMATION_MISSING = "operator_confirmation_missing"


@dataclass(frozen=True)
class ExecutionTransportAuthorizationInput:
    authorization: LiveExecutionAuthorizationDecision
    gateway_result: ExecutionGatewayResult
    source_trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionTransportPolicyInput:
    transport_enabled: bool
    execution_mode: str
    dry_run_force: bool
    allow_real_submission: bool
    single_submission_only: bool
    max_orders: int
    require_idempotency: bool
    idempotency_key_present: bool
    audit_log_required: bool
    audit_log_attached: bool
    operator_confirm_required: bool
    operator_confirm_present: bool
    policy_trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionTransportResult:
    submitted: bool
    success: bool
    blocked_reason: str | None
    execution_authorized: bool
    request_payload: dict[str, Any] | None
    exchange_response: dict[str, Any] | None
    transport_mode: str
    simulated: bool
    non_executing: bool


@dataclass(frozen=True)
class ExecutionTransportTrace:
    transport_attempted: bool
    blocked_reason: str | None
    upstream_trace_refs: dict[str, Any] = field(default_factory=dict)
    transport_notes: dict[str, Any] | None = None


@dataclass(frozen=True)
class ExecutionTransportBuildResult:
    result: ExecutionTransportResult | None
    trace: ExecutionTransportTrace


class ExecutionTransport:
    """Phase 5.2 single-path execution transport with explicit policy gates."""

    def submit(
        self,
        authorization_input: ExecutionTransportAuthorizationInput,
        policy_input: ExecutionTransportPolicyInput,
    ) -> ExecutionTransportResult | None:
        return self.submit_with_trace(
            authorization_input=authorization_input,
            policy_input=policy_input,
        ).result

    def submit_with_trace(
        self,
        *,
        authorization_input: ExecutionTransportAuthorizationInput,
        policy_input: ExecutionTransportPolicyInput,
    ) -> ExecutionTransportBuildResult:
        if not isinstance(authorization_input, ExecutionTransportAuthorizationInput):
            return _blocked_build_result(
                blocked_reason=EXECUTION_TRANSPORT_BLOCK_INVALID_AUTHORIZATION_INPUT_CONTRACT,
                execution_authorized=False,
                transport_mode=EXECUTION_TRANSPORT_MODE_SIMULATED,
                transport_attempted=False,
                upstream_trace_refs={
                    "contract_errors": {
                        "authorization_input": {
                            "expected_type": "ExecutionTransportAuthorizationInput",
                            "actual_type": type(authorization_input).__name__,
                        }
                    }
                },
                transport_notes={"contract_name": "authorization_input"},
            )

        if not isinstance(policy_input, ExecutionTransportPolicyInput):
            return _blocked_build_result(
                blocked_reason=EXECUTION_TRANSPORT_BLOCK_INVALID_POLICY_INPUT_CONTRACT,
                execution_authorized=bool(getattr(authorization_input.authorization, "execution_authorized", False)),
                transport_mode=EXECUTION_TRANSPORT_MODE_SIMULATED,
                transport_attempted=False,
                upstream_trace_refs={
                    "authorization_input": _trace_dict_or_empty(authorization_input.source_trace_refs),
                    "contract_errors": {
                        "policy_input": {
                            "expected_type": "ExecutionTransportPolicyInput",
                            "actual_type": type(policy_input).__name__,
                        }
                    },
                },
                transport_notes={"contract_name": "policy_input"},
            )

        upstream_trace_refs: dict[str, Any] = {
            "authorization_input": _trace_dict_or_empty(authorization_input.source_trace_refs),
            "policy_input": _trace_dict_or_empty(policy_input.policy_trace_refs),
        }

        upstream_error = _validate_authorization_input(authorization_input)
        if upstream_error is not None:
            return _blocked_build_result(
                blocked_reason=EXECUTION_TRANSPORT_BLOCK_INVALID_AUTHORIZATION_INPUT_CONTRACT,
                execution_authorized=False,
                transport_mode=EXECUTION_TRANSPORT_MODE_SIMULATED,
                transport_attempted=False,
                upstream_trace_refs={
                    **upstream_trace_refs,
                    "contract_errors": {"authorization_input": upstream_error},
                },
                transport_notes={"authorization_input_error": upstream_error},
            )

        policy_error = _validate_policy_input(policy_input)
        if policy_error is not None:
            return _blocked_build_result(
                blocked_reason=EXECUTION_TRANSPORT_BLOCK_INVALID_POLICY_INPUT_CONTRACT,
                execution_authorized=authorization_input.authorization.execution_authorized,
                transport_mode=EXECUTION_TRANSPORT_MODE_SIMULATED,
                transport_attempted=False,
                upstream_trace_refs={
                    **upstream_trace_refs,
                    "contract_errors": {"policy_input": policy_error},
                },
                transport_notes={"policy_input_error": policy_error},
            )

        if authorization_input.authorization.execution_authorized is not True:
            return _blocked_build_result(
                blocked_reason=EXECUTION_TRANSPORT_BLOCK_AUTHORIZATION_REQUIRED,
                execution_authorized=False,
                transport_mode=EXECUTION_TRANSPORT_MODE_SIMULATED,
                transport_attempted=False,
                upstream_trace_refs=upstream_trace_refs,
                transport_notes={
                    "authorization_blocked_reason": authorization_input.authorization.blocked_reason,
                },
            )

        if policy_input.transport_enabled is not True:
            return _blocked_build_result(
                blocked_reason=EXECUTION_TRANSPORT_BLOCK_TRANSPORT_DISABLED,
                execution_authorized=True,
                transport_mode=EXECUTION_TRANSPORT_MODE_SIMULATED,
                transport_attempted=False,
                upstream_trace_refs=upstream_trace_refs,
                transport_notes={"transport_enabled": policy_input.transport_enabled},
            )

        if policy_input.allow_real_submission is not True:
            return _blocked_build_result(
                blocked_reason=EXECUTION_TRANSPORT_BLOCK_REAL_SUBMISSION_NOT_ALLOWED,
                execution_authorized=True,
                transport_mode=EXECUTION_TRANSPORT_MODE_SIMULATED,
                transport_attempted=False,
                upstream_trace_refs=upstream_trace_refs,
                transport_notes={"allow_real_submission": policy_input.allow_real_submission},
            )

        if _normalize_text(policy_input.execution_mode) != MODE_LIVE:
            return _blocked_build_result(
                blocked_reason=EXECUTION_TRANSPORT_BLOCK_INVALID_EXECUTION_MODE,
                execution_authorized=True,
                transport_mode=EXECUTION_TRANSPORT_MODE_SIMULATED,
                transport_attempted=False,
                upstream_trace_refs=upstream_trace_refs,
                transport_notes={"execution_mode": policy_input.execution_mode},
            )

        if policy_input.single_submission_only is not True:
            return _blocked_build_result(
                blocked_reason=EXECUTION_TRANSPORT_BLOCK_MULTIPLE_ORDERS_NOT_ALLOWED,
                execution_authorized=True,
                transport_mode=EXECUTION_TRANSPORT_MODE_SIMULATED,
                transport_attempted=False,
                upstream_trace_refs=upstream_trace_refs,
                transport_notes={"single_submission_only": policy_input.single_submission_only},
            )

        if policy_input.max_orders > 1:
            return _blocked_build_result(
                blocked_reason=EXECUTION_TRANSPORT_BLOCK_MULTIPLE_ORDERS_NOT_ALLOWED,
                execution_authorized=True,
                transport_mode=EXECUTION_TRANSPORT_MODE_SIMULATED,
                transport_attempted=False,
                upstream_trace_refs=upstream_trace_refs,
                transport_notes={"max_orders": policy_input.max_orders},
            )

        if policy_input.require_idempotency and not policy_input.idempotency_key_present:
            return _blocked_build_result(
                blocked_reason=EXECUTION_TRANSPORT_BLOCK_IDEMPOTENCY_REQUIRED,
                execution_authorized=True,
                transport_mode=EXECUTION_TRANSPORT_MODE_SIMULATED,
                transport_attempted=False,
                upstream_trace_refs=upstream_trace_refs,
                transport_notes={"require_idempotency": policy_input.require_idempotency},
            )

        if policy_input.audit_log_required and not policy_input.audit_log_attached:
            return _blocked_build_result(
                blocked_reason=EXECUTION_TRANSPORT_BLOCK_AUDIT_LOG_MISSING,
                execution_authorized=True,
                transport_mode=EXECUTION_TRANSPORT_MODE_SIMULATED,
                transport_attempted=False,
                upstream_trace_refs=upstream_trace_refs,
                transport_notes={"audit_log_required": policy_input.audit_log_required},
            )

        if policy_input.operator_confirm_required and not policy_input.operator_confirm_present:
            return _blocked_build_result(
                blocked_reason=EXECUTION_TRANSPORT_BLOCK_OPERATOR_CONFIRMATION_MISSING,
                execution_authorized=True,
                transport_mode=EXECUTION_TRANSPORT_MODE_SIMULATED,
                transport_attempted=False,
                upstream_trace_refs=upstream_trace_refs,
                transport_notes={"operator_confirm_required": policy_input.operator_confirm_required},
            )

        request_payload = self._build_request_payload(authorization_input)

        if policy_input.dry_run_force:
            return ExecutionTransportBuildResult(
                result=ExecutionTransportResult(
                    submitted=True,
                    success=True,
                    blocked_reason=EXECUTION_TRANSPORT_BLOCK_DRY_RUN_FORCED,
                    execution_authorized=True,
                    request_payload=request_payload,
                    exchange_response={
                        "status": "SIMULATED_SUBMISSION_ACCEPTED",
                        "accepted": True,
                        "transport_mode": EXECUTION_TRANSPORT_MODE_SIMULATED,
                    },
                    transport_mode=EXECUTION_TRANSPORT_MODE_SIMULATED,
                    simulated=True,
                    non_executing=True,
                ),
                trace=ExecutionTransportTrace(
                    transport_attempted=True,
                    blocked_reason=EXECUTION_TRANSPORT_BLOCK_DRY_RUN_FORCED,
                    upstream_trace_refs=upstream_trace_refs,
                    transport_notes={"dry_run_force": True},
                ),
            )

        exchange_response = self._submit_to_exchange_interface_stub(request_payload)
        success = bool(exchange_response.get("accepted") is True)
        return ExecutionTransportBuildResult(
            result=ExecutionTransportResult(
                submitted=True,
                success=success,
                blocked_reason=None if success else EXECUTION_TRANSPORT_BLOCK_REAL_SUBMISSION_NOT_ALLOWED,
                execution_authorized=True,
                request_payload=request_payload,
                exchange_response=exchange_response,
                transport_mode=EXECUTION_TRANSPORT_MODE_REAL,
                simulated=False,
                non_executing=False,
            ),
            trace=ExecutionTransportTrace(
                transport_attempted=True,
                blocked_reason=None if success else EXECUTION_TRANSPORT_BLOCK_REAL_SUBMISSION_NOT_ALLOWED,
                upstream_trace_refs=upstream_trace_refs,
                transport_notes={"exchange_stub_called": True},
            ),
        )

    def _build_request_payload(
        self,
        authorization_input: ExecutionTransportAuthorizationInput,
    ) -> dict[str, Any]:
        return {
            "client_order_id": authorization_input.gateway_result.client_order_id,
            "execution_status": authorization_input.gateway_result.execution_status,
            "execution_authorized": authorization_input.authorization.execution_authorized,
            "authorization_scope": authorization_input.authorization.authorization_scope,
            "selected_mode": authorization_input.authorization.selected_mode,
        }

    def _submit_to_exchange_interface_stub(self, payload: dict[str, Any]) -> dict[str, Any]:
        accepted = _normalize_text(payload.get("client_order_id")) != ""
        return {
            "accepted": accepted,
            "status": "ORDER_SUBMITTED" if accepted else "ORDER_REJECTED",
            "transport_mode": EXECUTION_TRANSPORT_MODE_REAL,
            "client_order_id": payload.get("client_order_id"),
        }


def _validate_authorization_input(authorization_input: ExecutionTransportAuthorizationInput) -> str | None:
    if not isinstance(authorization_input.authorization, LiveExecutionAuthorizationDecision):
        return "authorization_decision_required"
    if not isinstance(authorization_input.gateway_result, ExecutionGatewayResult):
        return "gateway_result_required"
    if not isinstance(authorization_input.source_trace_refs, dict):
        return "source_trace_refs_must_be_dict"
    return None


def _validate_policy_input(policy_input: ExecutionTransportPolicyInput) -> str | None:
    bool_fields: dict[str, Any] = {
        "transport_enabled": policy_input.transport_enabled,
        "dry_run_force": policy_input.dry_run_force,
        "allow_real_submission": policy_input.allow_real_submission,
        "single_submission_only": policy_input.single_submission_only,
        "require_idempotency": policy_input.require_idempotency,
        "idempotency_key_present": policy_input.idempotency_key_present,
        "audit_log_required": policy_input.audit_log_required,
        "audit_log_attached": policy_input.audit_log_attached,
        "operator_confirm_required": policy_input.operator_confirm_required,
        "operator_confirm_present": policy_input.operator_confirm_present,
    }
    for name, value in bool_fields.items():
        if not isinstance(value, bool):
            return f"{name}_must_be_bool"

    if not isinstance(policy_input.execution_mode, str) or _normalize_text(policy_input.execution_mode) == "":
        return "execution_mode_required"
    if not isinstance(policy_input.max_orders, int):
        return "max_orders_must_be_int"
    if policy_input.max_orders < 1:
        return "max_orders_must_be_positive"
    if not isinstance(policy_input.policy_trace_refs, dict):
        return "policy_trace_refs_must_be_dict"
    return None


def _normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().upper()


def _trace_dict_or_empty(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _blocked_build_result(
    *,
    blocked_reason: str,
    execution_authorized: bool,
    transport_mode: str,
    transport_attempted: bool,
    upstream_trace_refs: dict[str, Any],
    transport_notes: dict[str, Any] | None,
) -> ExecutionTransportBuildResult:
    return ExecutionTransportBuildResult(
        result=ExecutionTransportResult(
            submitted=False,
            success=False,
            blocked_reason=blocked_reason,
            execution_authorized=execution_authorized,
            request_payload=None,
            exchange_response=None,
            transport_mode=transport_mode,
            simulated=True,
            non_executing=True,
        ),
        trace=ExecutionTransportTrace(
            transport_attempted=transport_attempted,
            blocked_reason=blocked_reason,
            upstream_trace_refs=upstream_trace_refs,
            transport_notes=transport_notes,
        ),
    )
