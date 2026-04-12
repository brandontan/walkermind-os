from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .legacy_core_facade import LegacyCoreFacade, LegacyCoreFacadeResolution, LegacyTradeValidationRequest
from .public_app_gateway import (
    PUBLIC_APP_GATEWAY_DISABLED,
    PUBLIC_APP_GATEWAY_LEGACY_ONLY,
    PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_PRIMARY,
    PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_SHADOW,
    PublicAppGatewayRoutingTrace,
)

READINESS_BLOCK_ROUTING_NOT_SAFE = "routing_not_safe"
READINESS_BLOCK_MISSING_EXECUTION_CONTEXT = "missing_execution_context"
READINESS_BLOCK_RISK_VALIDATION_BLOCKED = "risk_validation_blocked"
READINESS_BLOCK_ACTIVATION_NOT_ALLOWED = "activation_not_allowed_in_phase3_1"
READINESS_BLOCK_UNSUPPORTED_MODE = "unsupported_mode"
READINESS_READY_BUT_NON_ACTIVATING = "phase3_1_non_activating_boundary"

_SUPPORTED_SAFE_MODES = {
    PUBLIC_APP_GATEWAY_LEGACY_ONLY,
    PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_SHADOW,
    PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_PRIMARY,
}


@dataclass(frozen=True)
class ExecutionReadinessTrace:
    selected_routing_mode: str
    selected_path: str
    platform_participation: bool
    adapter_enforced: bool
    pre_execution_readiness_result: str
    final_activation_decision: bool


@dataclass(frozen=True)
class ExecutionReadinessResult:
    can_execute: bool
    block_reason: str
    readiness_checks: dict[str, Any]
    runtime_activation_allowed: bool
    trace: ExecutionReadinessTrace


class ExecutionSafeReadinessGate:
    """Phase 3.1 pre-execution boundary: assess readiness only and always block activation."""

    def __init__(self, *, facade: LegacyCoreFacade) -> None:
        self._facade = facade

    def evaluate(
        self,
        *,
        routing_trace: PublicAppGatewayRoutingTrace,
        facade_resolution: LegacyCoreFacadeResolution | None,
        signal_data: dict[str, Any],
        decision_data: dict[str, Any],
        risk_state: dict[str, Any],
        activation_requested: bool = False,
    ) -> ExecutionReadinessResult:
        checks: dict[str, Any] = {
            "routing_mode": routing_trace.selected_mode,
            "routing_path": routing_trace.selected_path,
            "platform_participated": routing_trace.platform_participated,
            "adapter_enforced": routing_trace.adapter_enforced,
            "runtime_activation_remained_disabled": routing_trace.runtime_activation_remained_disabled,
            "activation_requested": activation_requested,
        }

        if routing_trace.selected_mode not in _SUPPORTED_SAFE_MODES and routing_trace.selected_mode != PUBLIC_APP_GATEWAY_DISABLED:
            return self._blocked_result(
                routing_trace=routing_trace,
                checks=checks,
                reason=READINESS_BLOCK_UNSUPPORTED_MODE,
            )

        if routing_trace.selected_mode == PUBLIC_APP_GATEWAY_DISABLED:
            return self._blocked_result(
                routing_trace=routing_trace,
                checks=checks,
                reason=READINESS_BLOCK_ROUTING_NOT_SAFE,
            )

        if not routing_trace.adapter_enforced or not routing_trace.runtime_activation_remained_disabled:
            return self._blocked_result(
                routing_trace=routing_trace,
                checks=checks,
                reason=READINESS_BLOCK_ROUTING_NOT_SAFE,
            )

        facade = facade_resolution
        envelope = getattr(facade, "context_envelope", None) if facade else None
        execution_ctx = getattr(envelope, "execution_context", None) if envelope else None

        if execution_ctx is None:
            return self._blocked_result(
                routing_trace=routing_trace,
                checks=checks,
                reason=READINESS_BLOCK_MISSING_EXECUTION_CONTEXT,
            )

        execution_context = asdict(execution_ctx)

        validation_result = self._facade.validate_trade(
            LegacyTradeValidationRequest(
                signal_data=signal_data,
                decision_data=decision_data,
                risk_state=risk_state,
                execution_context=execution_context,
            )
        )
        checks["risk_validation_decision"] = validation_result.decision
        checks["risk_validation_reason"] = validation_result.reason
        checks["risk_validation_checks"] = validation_result.checks

        if validation_result.decision != "ALLOW":
            return self._blocked_result(
                routing_trace=routing_trace,
                checks=checks,
                reason=READINESS_BLOCK_RISK_VALIDATION_BLOCKED,
            )

        readiness_reason = (
            READINESS_BLOCK_ACTIVATION_NOT_ALLOWED if activation_requested else READINESS_READY_BUT_NON_ACTIVATING
        )
        return self._blocked_result(
            routing_trace=routing_trace,
            checks=checks,
            reason=readiness_reason,
        )

    def _blocked_result(
        self,
        *,
        routing_trace: PublicAppGatewayRoutingTrace,
        checks: dict[str, Any],
        reason: str,
    ) -> ExecutionReadinessResult:
        trace = ExecutionReadinessTrace(
            selected_routing_mode=routing_trace.selected_mode,
            selected_path=routing_trace.selected_path,
            platform_participation=routing_trace.platform_participated,
            adapter_enforced=routing_trace.adapter_enforced,
            pre_execution_readiness_result=reason,
            final_activation_decision=False,
        )
        return ExecutionReadinessResult(
            can_execute=False,
            block_reason=reason,
            readiness_checks=checks,
            runtime_activation_allowed=False,
            trace=trace,
        )
