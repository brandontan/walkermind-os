from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .execution_mode_controller import MODE_FUTURE_LIVE, MODE_LIVE
from .live_execution_guardrails import LiveExecutionReadinessDecision
from .monitoring_circuit_breaker import (
    MONITORING_DECISION_BLOCK,
    MONITORING_DECISION_HALT,
    MonitoringCircuitBreaker,
    MonitoringContractInput,
)

LIVE_AUTH_BLOCK_INVALID_READINESS_INPUT_CONTRACT = "invalid_readiness_input_contract"
LIVE_AUTH_BLOCK_INVALID_POLICY_INPUT_CONTRACT = "invalid_policy_input_contract"
LIVE_AUTH_BLOCK_INVALID_READINESS_DECISION = "invalid_readiness_decision"
LIVE_AUTH_BLOCK_INVALID_POLICY_INPUT = "invalid_policy_input"
LIVE_AUTH_BLOCK_UPSTREAM_READINESS_NOT_ALLOWED = "upstream_readiness_not_allowed"
LIVE_AUTH_BLOCK_LIVE_READINESS_REQUIRED = "live_readiness_required"
LIVE_AUTH_BLOCK_LIVE_MODE_REQUIRED = "live_mode_required"
LIVE_AUTH_BLOCK_EXPLICIT_EXECUTION_ENABLE_REQUIRED = "explicit_execution_enable_required"
LIVE_AUTH_BLOCK_AUTHORIZATION_SCOPE_NOT_ALLOWED = "authorization_scope_not_allowed"
LIVE_AUTH_BLOCK_TARGET_MARKET_REQUIRED = "target_market_required"
LIVE_AUTH_BLOCK_WALLET_BINDING_MISSING = "wallet_binding_missing"
LIVE_AUTH_BLOCK_AUDIT_ATTACHMENT_MISSING = "audit_attachment_missing"
LIVE_AUTH_BLOCK_OPERATOR_APPROVAL_MISSING = "operator_approval_missing"
LIVE_AUTH_BLOCK_KILL_SWITCH_NOT_ARMED = "kill_switch_not_armed"
LIVE_AUTH_BLOCK_MONITORING_EVALUATION_REQUIRED = "monitoring_evaluation_required"
LIVE_AUTH_BLOCK_MONITORING_ANOMALY = "monitoring_anomaly_block"
LIVE_AUTH_HALT_MONITORING_ANOMALY = "monitoring_anomaly_halt"


@dataclass(frozen=True)
class LiveExecutionReadinessInput:
    readiness_decision: LiveExecutionReadinessDecision
    monitoring_input: MonitoringContractInput | None = None
    monitoring_circuit_breaker: MonitoringCircuitBreaker | None = None
    source_trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LiveExecutionAuthorizationPolicyInput:
    explicit_execution_enable: bool
    authorization_scope: str
    allowed_scopes: tuple[str, ...] | list[str]
    single_market_only: bool
    target_market_id: str | None
    wallet_binding_required: bool
    wallet_binding_present: bool
    audit_required: bool
    audit_attached: bool
    operator_approval_required: bool
    operator_approval_present: bool
    kill_switch_must_remain_armed: bool = True
    monitoring_required: bool = False
    policy_trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LiveExecutionAuthorizationDecision:
    execution_authorized: bool
    allowed: bool
    blocked_reason: str | None
    selected_mode: str
    authorization_scope: str
    kill_switch_armed: bool
    audit_required: bool
    audit_attached: bool
    simulated: bool
    non_executing: bool


@dataclass(frozen=True)
class LiveExecutionAuthorizationTrace:
    authorization_evaluated: bool
    blocked_reason: str | None
    upstream_trace_refs: dict[str, Any] = field(default_factory=dict)
    authorization_notes: dict[str, Any] | None = None


@dataclass(frozen=True)
class LiveExecutionAuthorizationBuildResult:
    decision: LiveExecutionAuthorizationDecision | None
    trace: LiveExecutionAuthorizationTrace


class LiveExecutionAuthorizer:
    """Phase 5.1 deterministic first-path live execution authorization layer."""

    def authorize(
        self,
        readiness_input: LiveExecutionReadinessInput,
        policy_input: LiveExecutionAuthorizationPolicyInput,
    ) -> LiveExecutionAuthorizationDecision | None:
        return self.authorize_with_trace(
            readiness_input=readiness_input,
            policy_input=policy_input,
        ).decision

    def authorize_with_trace(
        self,
        *,
        readiness_input: LiveExecutionReadinessInput,
        policy_input: LiveExecutionAuthorizationPolicyInput,
    ) -> LiveExecutionAuthorizationBuildResult:
        if not isinstance(readiness_input, LiveExecutionReadinessInput):
            return _blocked_result(
                selected_mode="",
                authorization_scope="",
                blocked_reason=LIVE_AUTH_BLOCK_INVALID_READINESS_INPUT_CONTRACT,
                kill_switch_armed=False,
                audit_required=False,
                audit_attached=False,
                authorization_evaluated=False,
                upstream_trace_refs={
                    "contract_errors": {
                        "readiness_input": {
                            "expected_type": "LiveExecutionReadinessInput",
                            "actual_type": type(readiness_input).__name__,
                        }
                    }
                },
                authorization_notes={"contract_name": "readiness_input"},
            )

        selected_mode = _normalize_text(readiness_input.readiness_decision.selected_mode)

        if not isinstance(policy_input, LiveExecutionAuthorizationPolicyInput):
            return _blocked_result(
                selected_mode=selected_mode,
                authorization_scope="",
                blocked_reason=LIVE_AUTH_BLOCK_INVALID_POLICY_INPUT_CONTRACT,
                kill_switch_armed=False,
                audit_required=False,
                audit_attached=False,
                authorization_evaluated=False,
                upstream_trace_refs={
                    "readiness_input": _trace_dict_or_empty(readiness_input.source_trace_refs),
                    "contract_errors": {
                        "policy_input": {
                            "expected_type": "LiveExecutionAuthorizationPolicyInput",
                            "actual_type": type(policy_input).__name__,
                        }
                    },
                },
                authorization_notes={"contract_name": "policy_input"},
            )

        authorization_scope = _normalize_text(policy_input.authorization_scope)
        upstream_trace_refs: dict[str, Any] = {
            "readiness_input": _trace_dict_or_empty(readiness_input.source_trace_refs),
            "policy_input": _trace_dict_or_empty(policy_input.policy_trace_refs),
        }

        readiness_error = _validate_readiness_decision(readiness_input.readiness_decision)
        if readiness_error is not None:
            return _blocked_result(
                selected_mode=selected_mode,
                authorization_scope=authorization_scope,
                blocked_reason=LIVE_AUTH_BLOCK_INVALID_READINESS_DECISION,
                kill_switch_armed=bool(readiness_input.readiness_decision.kill_switch_armed),
                audit_required=bool(policy_input.audit_required),
                audit_attached=bool(policy_input.audit_attached),
                authorization_evaluated=True,
                upstream_trace_refs={
                    **upstream_trace_refs,
                    "contract_errors": {"readiness_decision": readiness_error},
                },
                authorization_notes={"readiness_decision_error": readiness_error},
            )

        policy_error = _validate_policy_input(policy_input)
        if policy_error is not None:
            return _blocked_result(
                selected_mode=selected_mode,
                authorization_scope=authorization_scope,
                blocked_reason=LIVE_AUTH_BLOCK_INVALID_POLICY_INPUT,
                kill_switch_armed=bool(readiness_input.readiness_decision.kill_switch_armed),
                audit_required=bool(policy_input.audit_required),
                audit_attached=bool(policy_input.audit_attached),
                authorization_evaluated=True,
                upstream_trace_refs={
                    **upstream_trace_refs,
                    "contract_errors": {"policy_input": policy_error},
                },
                authorization_notes={"policy_input_error": policy_error},
            )

        if readiness_input.readiness_decision.allowed is not True:
            return _blocked_result(
                selected_mode=selected_mode,
                authorization_scope=authorization_scope,
                blocked_reason=LIVE_AUTH_BLOCK_UPSTREAM_READINESS_NOT_ALLOWED,
                kill_switch_armed=readiness_input.readiness_decision.kill_switch_armed,
                audit_required=policy_input.audit_required,
                audit_attached=policy_input.audit_attached,
                authorization_evaluated=True,
                upstream_trace_refs=upstream_trace_refs,
                authorization_notes={
                    "upstream_blocked_reason": readiness_input.readiness_decision.blocked_reason
                },
            )

        if readiness_input.readiness_decision.live_ready is not True:
            return _blocked_result(
                selected_mode=selected_mode,
                authorization_scope=authorization_scope,
                blocked_reason=LIVE_AUTH_BLOCK_LIVE_READINESS_REQUIRED,
                kill_switch_armed=readiness_input.readiness_decision.kill_switch_armed,
                audit_required=policy_input.audit_required,
                audit_attached=policy_input.audit_attached,
                authorization_evaluated=True,
                upstream_trace_refs=upstream_trace_refs,
                authorization_notes={"live_ready": readiness_input.readiness_decision.live_ready},
            )

        if selected_mode not in {MODE_LIVE, MODE_FUTURE_LIVE}:
            return _blocked_result(
                selected_mode=selected_mode,
                authorization_scope=authorization_scope,
                blocked_reason=LIVE_AUTH_BLOCK_LIVE_MODE_REQUIRED,
                kill_switch_armed=readiness_input.readiness_decision.kill_switch_armed,
                audit_required=policy_input.audit_required,
                audit_attached=policy_input.audit_attached,
                authorization_evaluated=True,
                upstream_trace_refs=upstream_trace_refs,
                authorization_notes={"selected_mode": selected_mode},
            )

        if policy_input.explicit_execution_enable is not True:
            return _blocked_result(
                selected_mode=selected_mode,
                authorization_scope=authorization_scope,
                blocked_reason=LIVE_AUTH_BLOCK_EXPLICIT_EXECUTION_ENABLE_REQUIRED,
                kill_switch_armed=readiness_input.readiness_decision.kill_switch_armed,
                audit_required=policy_input.audit_required,
                audit_attached=policy_input.audit_attached,
                authorization_evaluated=True,
                upstream_trace_refs=upstream_trace_refs,
                authorization_notes={"explicit_execution_enable": policy_input.explicit_execution_enable},
            )

        allowed_scopes = _normalize_allow_list(policy_input.allowed_scopes)
        if authorization_scope not in allowed_scopes:
            return _blocked_result(
                selected_mode=selected_mode,
                authorization_scope=authorization_scope,
                blocked_reason=LIVE_AUTH_BLOCK_AUTHORIZATION_SCOPE_NOT_ALLOWED,
                kill_switch_armed=readiness_input.readiness_decision.kill_switch_armed,
                audit_required=policy_input.audit_required,
                audit_attached=policy_input.audit_attached,
                authorization_evaluated=True,
                upstream_trace_refs=upstream_trace_refs,
                authorization_notes={"allowed_scopes": sorted(allowed_scopes)},
            )

        if policy_input.single_market_only and _normalize_text(policy_input.target_market_id) == "":
            return _blocked_result(
                selected_mode=selected_mode,
                authorization_scope=authorization_scope,
                blocked_reason=LIVE_AUTH_BLOCK_TARGET_MARKET_REQUIRED,
                kill_switch_armed=readiness_input.readiness_decision.kill_switch_armed,
                audit_required=policy_input.audit_required,
                audit_attached=policy_input.audit_attached,
                authorization_evaluated=True,
                upstream_trace_refs=upstream_trace_refs,
                authorization_notes={"single_market_only": policy_input.single_market_only},
            )

        if policy_input.wallet_binding_required and policy_input.wallet_binding_present is not True:
            return _blocked_result(
                selected_mode=selected_mode,
                authorization_scope=authorization_scope,
                blocked_reason=LIVE_AUTH_BLOCK_WALLET_BINDING_MISSING,
                kill_switch_armed=readiness_input.readiness_decision.kill_switch_armed,
                audit_required=policy_input.audit_required,
                audit_attached=policy_input.audit_attached,
                authorization_evaluated=True,
                upstream_trace_refs=upstream_trace_refs,
                authorization_notes={"wallet_binding_required": policy_input.wallet_binding_required},
            )

        if policy_input.audit_required and policy_input.audit_attached is not True:
            return _blocked_result(
                selected_mode=selected_mode,
                authorization_scope=authorization_scope,
                blocked_reason=LIVE_AUTH_BLOCK_AUDIT_ATTACHMENT_MISSING,
                kill_switch_armed=readiness_input.readiness_decision.kill_switch_armed,
                audit_required=policy_input.audit_required,
                audit_attached=policy_input.audit_attached,
                authorization_evaluated=True,
                upstream_trace_refs=upstream_trace_refs,
                authorization_notes={"audit_required": policy_input.audit_required},
            )

        if (
            policy_input.operator_approval_required
            and policy_input.operator_approval_present is not True
        ):
            return _blocked_result(
                selected_mode=selected_mode,
                authorization_scope=authorization_scope,
                blocked_reason=LIVE_AUTH_BLOCK_OPERATOR_APPROVAL_MISSING,
                kill_switch_armed=readiness_input.readiness_decision.kill_switch_armed,
                audit_required=policy_input.audit_required,
                audit_attached=policy_input.audit_attached,
                authorization_evaluated=True,
                upstream_trace_refs=upstream_trace_refs,
                authorization_notes={
                    "operator_approval_required": policy_input.operator_approval_required
                },
            )

        if (
            policy_input.kill_switch_must_remain_armed
            and readiness_input.readiness_decision.kill_switch_armed is not True
        ):
            return _blocked_result(
                selected_mode=selected_mode,
                authorization_scope=authorization_scope,
                blocked_reason=LIVE_AUTH_BLOCK_KILL_SWITCH_NOT_ARMED,
                kill_switch_armed=readiness_input.readiness_decision.kill_switch_armed,
                audit_required=policy_input.audit_required,
                audit_attached=policy_input.audit_attached,
                authorization_evaluated=True,
                upstream_trace_refs=upstream_trace_refs,
                authorization_notes={
                    "kill_switch_must_remain_armed": policy_input.kill_switch_must_remain_armed
                },
            )

        monitoring_result = None
        if policy_input.monitoring_required:
            if not isinstance(readiness_input.monitoring_input, MonitoringContractInput):
                return _blocked_result(
                    selected_mode=selected_mode,
                    authorization_scope=authorization_scope,
                    blocked_reason=LIVE_AUTH_BLOCK_MONITORING_EVALUATION_REQUIRED,
                    kill_switch_armed=readiness_input.readiness_decision.kill_switch_armed,
                    audit_required=policy_input.audit_required,
                    audit_attached=policy_input.audit_attached,
                    authorization_evaluated=True,
                    upstream_trace_refs=upstream_trace_refs,
                    authorization_notes={"monitoring_required": True},
                )
            breaker = readiness_input.monitoring_circuit_breaker
            if breaker is None:
                breaker = MonitoringCircuitBreaker()
            elif not isinstance(breaker, MonitoringCircuitBreaker):
                return _blocked_result(
                    selected_mode=selected_mode,
                    authorization_scope=authorization_scope,
                    blocked_reason=LIVE_AUTH_BLOCK_MONITORING_EVALUATION_REQUIRED,
                    kill_switch_armed=readiness_input.readiness_decision.kill_switch_armed,
                    audit_required=policy_input.audit_required,
                    audit_attached=policy_input.audit_attached,
                    authorization_evaluated=True,
                    upstream_trace_refs={
                        **upstream_trace_refs,
                        "contract_errors": {
                            "monitoring_circuit_breaker": {
                                "expected_type": "MonitoringCircuitBreaker",
                                "actual_type": type(readiness_input.monitoring_circuit_breaker).__name__,
                            }
                        },
                    },
                    authorization_notes={"contract_name": "monitoring_circuit_breaker"},
                )
            monitoring_result = breaker.evaluate(readiness_input.monitoring_input)
            upstream_trace_refs["monitoring"] = {
                "decision": monitoring_result.decision,
                "primary_anomaly": monitoring_result.primary_anomaly,
                "anomalies": list(monitoring_result.anomalies),
                "eval_ref": monitoring_result.event.eval_ref,
            }
            if monitoring_result.decision == MONITORING_DECISION_HALT:
                return _blocked_result(
                    selected_mode=selected_mode,
                    authorization_scope=authorization_scope,
                    blocked_reason=LIVE_AUTH_HALT_MONITORING_ANOMALY,
                    kill_switch_armed=readiness_input.readiness_decision.kill_switch_armed,
                    audit_required=policy_input.audit_required,
                    audit_attached=policy_input.audit_attached,
                    authorization_evaluated=True,
                    upstream_trace_refs=upstream_trace_refs,
                    authorization_notes={
                        "monitoring_decision": monitoring_result.decision,
                        "primary_anomaly": monitoring_result.primary_anomaly,
                    },
                )
            if monitoring_result.decision == MONITORING_DECISION_BLOCK:
                return _blocked_result(
                    selected_mode=selected_mode,
                    authorization_scope=authorization_scope,
                    blocked_reason=LIVE_AUTH_BLOCK_MONITORING_ANOMALY,
                    kill_switch_armed=readiness_input.readiness_decision.kill_switch_armed,
                    audit_required=policy_input.audit_required,
                    audit_attached=policy_input.audit_attached,
                    authorization_evaluated=True,
                    upstream_trace_refs=upstream_trace_refs,
                    authorization_notes={
                        "monitoring_decision": monitoring_result.decision,
                        "primary_anomaly": monitoring_result.primary_anomaly,
                    },
                )

        decision = LiveExecutionAuthorizationDecision(
            execution_authorized=True,
            allowed=True,
            blocked_reason=None,
            selected_mode=selected_mode,
            authorization_scope=authorization_scope,
            kill_switch_armed=True,
            audit_required=policy_input.audit_required,
            audit_attached=policy_input.audit_attached,
            simulated=False,
            non_executing=False,
        )
        trace = LiveExecutionAuthorizationTrace(
            authorization_evaluated=True,
            blocked_reason=None,
            upstream_trace_refs=upstream_trace_refs,
            authorization_notes={"authorization_scope": authorization_scope},
        )
        return LiveExecutionAuthorizationBuildResult(decision=decision, trace=trace)


def _validate_readiness_decision(
    readiness_decision: LiveExecutionReadinessDecision,
) -> dict[str, str] | None:
    errors: dict[str, str] = {}

    if not isinstance(readiness_decision, LiveExecutionReadinessDecision):
        return {
            "expected_type": "LiveExecutionReadinessDecision",
            "actual_type": type(readiness_decision).__name__,
        }

    if _normalize_text(readiness_decision.selected_mode) == "":
        errors["selected_mode"] = "must_be_non_empty_string"
    if not isinstance(readiness_decision.allowed, bool):
        errors["allowed"] = "must_be_bool"
    if not isinstance(readiness_decision.live_ready, bool):
        errors["live_ready"] = "must_be_bool"
    if not isinstance(readiness_decision.kill_switch_armed, bool):
        errors["kill_switch_armed"] = "must_be_bool"

    return errors or None


def _validate_policy_input(
    policy_input: LiveExecutionAuthorizationPolicyInput,
) -> dict[str, str] | None:
    errors: dict[str, str] = {}

    if not isinstance(policy_input.explicit_execution_enable, bool):
        errors["explicit_execution_enable"] = "must_be_bool"
    if _normalize_text(policy_input.authorization_scope) == "":
        errors["authorization_scope"] = "must_be_non_empty_string"

    allowed_scopes = _normalize_allow_list(policy_input.allowed_scopes)
    if len(allowed_scopes) == 0:
        errors["allowed_scopes"] = "must_be_non_empty_string_sequence"

    if not isinstance(policy_input.single_market_only, bool):
        errors["single_market_only"] = "must_be_bool"
    if policy_input.target_market_id is not None and not isinstance(policy_input.target_market_id, str):
        errors["target_market_id"] = "must_be_str_or_none"
    if not isinstance(policy_input.wallet_binding_required, bool):
        errors["wallet_binding_required"] = "must_be_bool"
    if not isinstance(policy_input.wallet_binding_present, bool):
        errors["wallet_binding_present"] = "must_be_bool"
    if not isinstance(policy_input.audit_required, bool):
        errors["audit_required"] = "must_be_bool"
    if not isinstance(policy_input.audit_attached, bool):
        errors["audit_attached"] = "must_be_bool"
    if not isinstance(policy_input.operator_approval_required, bool):
        errors["operator_approval_required"] = "must_be_bool"
    if not isinstance(policy_input.operator_approval_present, bool):
        errors["operator_approval_present"] = "must_be_bool"
    if not isinstance(policy_input.kill_switch_must_remain_armed, bool):
        errors["kill_switch_must_remain_armed"] = "must_be_bool"
    if not isinstance(policy_input.monitoring_required, bool):
        errors["monitoring_required"] = "must_be_bool"
    if not isinstance(policy_input.policy_trace_refs, dict):
        errors["policy_trace_refs"] = "must_be_dict"

    return errors or None


def _blocked_result(
    *,
    selected_mode: str,
    authorization_scope: str,
    blocked_reason: str,
    kill_switch_armed: bool,
    audit_required: bool,
    audit_attached: bool,
    authorization_evaluated: bool,
    upstream_trace_refs: dict[str, Any],
    authorization_notes: dict[str, Any] | None,
) -> LiveExecutionAuthorizationBuildResult:
    decision = LiveExecutionAuthorizationDecision(
        execution_authorized=False,
        allowed=False,
        blocked_reason=blocked_reason,
        selected_mode=selected_mode,
        authorization_scope=authorization_scope,
        kill_switch_armed=kill_switch_armed,
        audit_required=audit_required,
        audit_attached=audit_attached,
        simulated=True,
        non_executing=True,
    )
    trace = LiveExecutionAuthorizationTrace(
        authorization_evaluated=authorization_evaluated,
        blocked_reason=blocked_reason,
        upstream_trace_refs=upstream_trace_refs,
        authorization_notes=authorization_notes,
    )
    return LiveExecutionAuthorizationBuildResult(decision=decision, trace=trace)


def _normalize_allow_list(values: tuple[str, ...] | list[str]) -> set[str]:
    normalized: set[str] = set()
    if not isinstance(values, (tuple, list)):
        return normalized
    for item in values:
        if isinstance(item, str):
            value = item.strip()
            if value:
                normalized.add(value)
    return normalized


def _normalize_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _trace_dict_or_empty(trace_refs: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(trace_refs, dict):
        return {}
    return dict(trace_refs)
