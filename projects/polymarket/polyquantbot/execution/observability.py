from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Any

import structlog

log = structlog.get_logger(__name__)

STAGE_ENTRY = "ENTRY"
STAGE_VALIDATION = "VALIDATION"
STAGE_RISK = "RISK"
STAGE_EXECUTION = "EXECUTION"
STAGE_RESULT = "RESULT"

OUTCOME_SUCCESS = "SUCCESS"
OUTCOME_FAILED = "FAILED"
OUTCOME_BLOCKED = "BLOCKED"
OUTCOME_TIMEOUT = "TIMEOUT"
OUTCOME_DUPLICATE_PREVENTED = "DUPLICATE_PREVENTED"
OUTCOME_INVALID_INPUT = "INVALID_INPUT"

_RECENT_OUTCOMES: deque[str] = deque(maxlen=50)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit_stage(
    *,
    trace_id: str,
    stage: str,
    component: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = {
        "trace_id": trace_id,
        "stage": stage,
        "component": component,
        "timestamp": _utc_now_iso(),
        "payload": payload or {},
    }
    log.info("execution_stage_trace", **event)
    return event


def emit_outcome(
    *,
    trace_id: str,
    outcome: str,
    component: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = {
        "trace_id": trace_id,
        "outcome": outcome,
        "component": component,
        "timestamp": _utc_now_iso(),
        "payload": payload or {},
    }
    _RECENT_OUTCOMES.append(outcome)
    log.info("execution_outcome", **event)
    _emit_anomaly_signals(trace_id=trace_id, component=component)
    return event


def emit_error(
    *,
    trace_id: str,
    execution_stage: str,
    component: str,
    error: Exception,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = {
        "trace_id": trace_id,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "execution_stage": execution_stage,
        "component": component,
        "timestamp": _utc_now_iso(),
        "payload": payload or {},
    }
    log.error("execution_failure", **event, exc_info=True)
    return event


def classify_result(*, success: bool, message: str) -> str:
    normalized = message.lower()
    if "duplicate_blocked" in normalized:
        return OUTCOME_DUPLICATE_PREVENTED
    if "usage:" in normalized or "must be" in normalized or "invalid" in normalized:
        return OUTCOME_INVALID_INPUT
    if "timeout" in normalized:
        return OUTCOME_TIMEOUT
    if success:
        return OUTCOME_SUCCESS
    return OUTCOME_FAILED


def _emit_anomaly_signals(*, trace_id: str, component: str) -> None:
    recent = list(_RECENT_OUTCOMES)
    if len(recent) < 5:
        return

    repeated_failures = recent[-5:].count(OUTCOME_FAILED)
    timeout_count = recent[-10:].count(OUTCOME_TIMEOUT)
    duplicate_count = recent[-10:].count(OUTCOME_DUPLICATE_PREVENTED)

    if repeated_failures >= 3:
        log.warning(
            "execution_anomaly_signal",
            trace_id=trace_id,
            component=component,
            anomaly_type="repeated_failures",
            window="last_5",
            count=repeated_failures,
            timestamp=_utc_now_iso(),
        )
    if timeout_count >= 3:
        log.warning(
            "execution_anomaly_signal",
            trace_id=trace_id,
            component=component,
            anomaly_type="abnormal_timeout_frequency",
            window="last_10",
            count=timeout_count,
            timestamp=_utc_now_iso(),
        )
    if duplicate_count >= 4:
        log.warning(
            "execution_anomaly_signal",
            trace_id=trace_id,
            component=component,
            anomaly_type="duplicate_spike",
            window="last_10",
            count=duplicate_count,
            timestamp=_utc_now_iso(),
        )
