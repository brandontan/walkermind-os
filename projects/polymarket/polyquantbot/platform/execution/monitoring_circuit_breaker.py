from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Any

MONITORING_DECISION_ALLOW = "ALLOW"
MONITORING_DECISION_BLOCK = "BLOCK"
MONITORING_DECISION_HALT = "HALT"

ANOMALY_EXPOSURE_THRESHOLD_BREACH = "EXPOSURE_THRESHOLD_BREACH"
ANOMALY_EXPOSURE_INPUT_INCONSISTENT = "EXPOSURE_INPUT_INCONSISTENT"
ANOMALY_DATA_STALENESS_BREACH = "DATA_STALENESS_BREACH"
ANOMALY_QUALITY_SCORE_BREACH = "QUALITY_SCORE_BREACH"
ANOMALY_SIGNAL_DEDUP_FAILURE = "SIGNAL_DEDUP_FAILURE"
ANOMALY_KILL_SWITCH_TRIGGERED = "KILL_SWITCH_TRIGGERED"
ANOMALY_MONITORING_DISABLED = "MONITORING_DISABLED"
ANOMALY_INVALID_CONTRACT_INPUT = "INVALID_CONTRACT_INPUT"

_ANOMALY_PRECEDENCE: tuple[str, ...] = (
    ANOMALY_INVALID_CONTRACT_INPUT,
    ANOMALY_MONITORING_DISABLED,
    ANOMALY_KILL_SWITCH_TRIGGERED,
    ANOMALY_EXPOSURE_INPUT_INCONSISTENT,
    ANOMALY_EXPOSURE_THRESHOLD_BREACH,
    ANOMALY_DATA_STALENESS_BREACH,
    ANOMALY_QUALITY_SCORE_BREACH,
    ANOMALY_SIGNAL_DEDUP_FAILURE,
)


@dataclass(frozen=True)
class MonitoringContractInput:
    policy_ref: str
    eval_ref: str
    timestamp_ms: int
    exposure_ratio: float
    position_notional_usd: float
    total_capital_usd: float
    data_freshness_ms: int
    quality_score: float
    signal_dedup_ok: bool
    kill_switch_armed: bool
    kill_switch_triggered: bool
    monitoring_enabled: bool
    quality_guard_enabled: bool
    exposure_guard_enabled: bool
    max_exposure_ratio: float
    max_data_freshness_ms: int
    min_quality_score: float
    trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MonitoringCircuitBreakerEvent:
    policy_ref: str
    eval_ref: str
    timestamp_ms: int
    decision: str
    primary_anomaly: str | None
    anomalies: tuple[str, ...]
    trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MonitoringCircuitBreakerResult:
    decision: str
    primary_anomaly: str | None
    anomalies: tuple[str, ...]
    should_halt_execution: bool
    should_block_execution: bool
    event: MonitoringCircuitBreakerEvent


class MonitoringCircuitBreaker:
    """Phase 6.4 runtime anomaly evaluator for a narrow execution-control path."""

    def __init__(self) -> None:
        self._events: list[MonitoringCircuitBreakerEvent] = []

    def evaluate(self, contract_input: MonitoringContractInput) -> MonitoringCircuitBreakerResult:
        anomalies = self._collect_anomalies(contract_input)
        primary_anomaly = _first_precedence_anomaly(anomalies)
        decision = _decision_for(primary_anomaly)
        event = MonitoringCircuitBreakerEvent(
            policy_ref=getattr(contract_input, "policy_ref", "invalid_input"),
            eval_ref=getattr(contract_input, "eval_ref", "invalid_input"),
            timestamp_ms=getattr(contract_input, "timestamp_ms", 0),
            decision=decision,
            primary_anomaly=primary_anomaly,
            anomalies=anomalies,
            trace_refs=_trace_dict_or_empty(getattr(contract_input, "trace_refs", {})),
        )
        self._events.append(event)
        return MonitoringCircuitBreakerResult(
            decision=decision,
            primary_anomaly=primary_anomaly,
            anomalies=anomalies,
            should_halt_execution=decision == MONITORING_DECISION_HALT,
            should_block_execution=decision in {MONITORING_DECISION_BLOCK, MONITORING_DECISION_HALT},
            event=event,
        )

    def get_events(self) -> tuple[MonitoringCircuitBreakerEvent, ...]:
        return tuple(self._events)

    def _collect_anomalies(self, contract_input: MonitoringContractInput) -> tuple[str, ...]:
        if not isinstance(contract_input, MonitoringContractInput):
            return (ANOMALY_INVALID_CONTRACT_INPUT,)

        anomalies: set[str] = set()
        contract_errors = _validate_contract_input(contract_input)
        if contract_errors:
            anomalies.add(ANOMALY_INVALID_CONTRACT_INPUT)

        if contract_input.monitoring_enabled is not True:
            anomalies.add(ANOMALY_MONITORING_DISABLED)

        if contract_input.kill_switch_armed and contract_input.kill_switch_triggered:
            anomalies.add(ANOMALY_KILL_SWITCH_TRIGGERED)

        if contract_input.exposure_guard_enabled:
            if contract_input.total_capital_usd <= 0 or contract_input.position_notional_usd < 0:
                anomalies.add(ANOMALY_EXPOSURE_INPUT_INCONSISTENT)
            if contract_input.exposure_ratio > contract_input.max_exposure_ratio:
                anomalies.add(ANOMALY_EXPOSURE_THRESHOLD_BREACH)

        if contract_input.quality_guard_enabled:
            if contract_input.data_freshness_ms > contract_input.max_data_freshness_ms:
                anomalies.add(ANOMALY_DATA_STALENESS_BREACH)
            if contract_input.quality_score < contract_input.min_quality_score:
                anomalies.add(ANOMALY_QUALITY_SCORE_BREACH)
            if contract_input.signal_dedup_ok is not True:
                anomalies.add(ANOMALY_SIGNAL_DEDUP_FAILURE)

        return tuple(sorted(anomalies, key=_precedence_index))


def _validate_contract_input(contract_input: MonitoringContractInput) -> dict[str, str]:
    errors: dict[str, str] = {}

    if not isinstance(contract_input.policy_ref, str) or contract_input.policy_ref.strip() == "":
        errors["policy_ref"] = "must_be_non_empty_str"
    if not isinstance(contract_input.eval_ref, str) or contract_input.eval_ref.strip() == "":
        errors["eval_ref"] = "must_be_non_empty_str"
    if not isinstance(contract_input.timestamp_ms, int) or contract_input.timestamp_ms <= 0:
        errors["timestamp_ms"] = "must_be_positive_int"

    for name in ("exposure_ratio", "quality_score", "max_exposure_ratio", "min_quality_score"):
        value = getattr(contract_input, name)
        if not isinstance(value, (int, float)) or not isfinite(float(value)):
            errors[name] = "must_be_finite_number"

    if not isinstance(contract_input.exposure_ratio, (int, float)) or contract_input.exposure_ratio < 0:
        errors["exposure_ratio"] = "must_be_non_negative"
    if not isinstance(contract_input.max_exposure_ratio, (int, float)) or contract_input.max_exposure_ratio != 0.10:
        errors["max_exposure_ratio"] = "must_equal_0_10"

    if not isinstance(contract_input.data_freshness_ms, int) or contract_input.data_freshness_ms < 0:
        errors["data_freshness_ms"] = "must_be_non_negative_int"
    if not isinstance(contract_input.max_data_freshness_ms, int) or contract_input.max_data_freshness_ms < 0:
        errors["max_data_freshness_ms"] = "must_be_non_negative_int"

    if not isinstance(contract_input.quality_score, (int, float)) or not 0.0 <= float(contract_input.quality_score) <= 1.0:
        errors["quality_score"] = "must_be_between_0_and_1"
    if not isinstance(contract_input.min_quality_score, (int, float)) or not 0.0 <= float(contract_input.min_quality_score) <= 1.0:
        errors["min_quality_score"] = "must_be_between_0_and_1"

    bool_fields = (
        "signal_dedup_ok",
        "kill_switch_armed",
        "kill_switch_triggered",
        "monitoring_enabled",
        "quality_guard_enabled",
        "exposure_guard_enabled",
    )
    for field_name in bool_fields:
        if not isinstance(getattr(contract_input, field_name), bool):
            errors[field_name] = "must_be_bool"

    if not isinstance(contract_input.trace_refs, dict):
        errors["trace_refs"] = "must_be_dict"

    return errors


def _precedence_index(anomaly: str) -> int:
    try:
        return _ANOMALY_PRECEDENCE.index(anomaly)
    except ValueError:
        return len(_ANOMALY_PRECEDENCE)


def _first_precedence_anomaly(anomalies: tuple[str, ...]) -> str | None:
    return anomalies[0] if anomalies else None


def _decision_for(primary_anomaly: str | None) -> str:
    if primary_anomaly in {
        ANOMALY_INVALID_CONTRACT_INPUT,
        ANOMALY_KILL_SWITCH_TRIGGERED,
    }:
        return MONITORING_DECISION_HALT
    if primary_anomaly in {
        ANOMALY_MONITORING_DISABLED,
        ANOMALY_EXPOSURE_INPUT_INCONSISTENT,
        ANOMALY_EXPOSURE_THRESHOLD_BREACH,
        ANOMALY_DATA_STALENESS_BREACH,
        ANOMALY_QUALITY_SCORE_BREACH,
        ANOMALY_SIGNAL_DEDUP_FAILURE,
    }:
        return MONITORING_DECISION_BLOCK
    return MONITORING_DECISION_ALLOW


def _trace_dict_or_empty(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}
