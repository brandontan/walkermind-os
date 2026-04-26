"""Settlement domain schemas — Priority 7 (sections 43-48).

All dataclasses are frozen.  Status constants use UPPER_SNAKE strings.
ID generators use lowercase prefixes matching the orchestration domain convention.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from projects.polymarket.polyquantbot.platform.execution.fund_settlement import FundSettlementResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def new_settlement_id() -> str:
    return "stl_" + uuid4().hex


def new_batch_id() -> str:
    return "bat_" + uuid4().hex


def new_recon_id() -> str:
    return "rcn_" + uuid4().hex


def new_event_id() -> str:
    return "evt_" + uuid4().hex


def new_intervention_id() -> str:
    return "adm_" + uuid4().hex


# ---------------------------------------------------------------------------
# Section 43 — Settlement Workflow status constants
# ---------------------------------------------------------------------------

SETTLEMENT_STATUS_PENDING    = "PENDING"
SETTLEMENT_STATUS_PROCESSING = "PROCESSING"
SETTLEMENT_STATUS_COMPLETED  = "COMPLETED"
SETTLEMENT_STATUS_FAILED     = "FAILED"
SETTLEMENT_STATUS_BLOCKED    = "BLOCKED"
SETTLEMENT_STATUS_SIMULATED  = "SIMULATED"
SETTLEMENT_STATUS_CANCELLED  = "CANCELLED"


@dataclass(frozen=True)
class SettlementWorkflowRequest:
    """Input to the settlement workflow engine.

    settlement_id is None on the first attempt; after the first call to
    FundSettlementEngine it is populated and carried forward unchanged as the
    canonical idempotency key.
    """

    wallet_id: str
    amount: float
    currency: str
    method: str
    mode: str
    workflow_id: str = field(default_factory=new_settlement_id)
    settlement_id: str | None = None
    correlation_id: str = field(default_factory=new_settlement_id)
    requested_at: datetime = field(default_factory=_utc_now)
    upstream_trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SettlementWorkflowResult:
    """Outcome of one settlement workflow execution attempt."""

    workflow_id: str
    status: str
    success: bool
    settlement_id: str | None = None
    blocked_reason: str | None = None
    simulated: bool = False
    fund_result: FundSettlementResult | None = None
    trace_refs: dict[str, Any] = field(default_factory=dict)
    completed_at: datetime | None = None


# ---------------------------------------------------------------------------
# Section 44 — Retry Engine constants and schemas
# ---------------------------------------------------------------------------

RETRY_OUTCOME_ACCEPTED  = "retry_accepted"
RETRY_OUTCOME_SKIPPED   = "retry_skipped"
RETRY_OUTCOME_EXHAUSTED = "retry_exhausted"
RETRY_OUTCOME_FATAL     = "retry_fatal"
RETRY_OUTCOME_BLOCKED   = "retry_blocked"

RETRY_MAX_BUDGET: int = 5


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = RETRY_MAX_BUDGET
    base_delay_s: float = 2.0
    max_delay_s: float = 300.0
    backoff_multiplier: float = 2.0


@dataclass(frozen=True)
class RetryAttemptRecord:
    attempt_number: int
    workflow_id: str
    outcome: str
    attempted_at: datetime = field(default_factory=_utc_now)
    settlement_id: str | None = None
    blocked_reason: str | None = None
    delay_before_next_s: float | None = None
    trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetryDecision:
    workflow_id: str
    outcome: str
    attempt_number: int
    is_fatal: bool
    is_exhausted: bool
    next_delay_s: float | None = None
    blocked_reason: str | None = None
    trace_refs: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Section 45 — Batch Processing constants and schemas
# ---------------------------------------------------------------------------

BATCH_MAX_SIZE: int = 20

BATCH_STATUS_OPEN       = "OPEN"
BATCH_STATUS_PROCESSING = "PROCESSING"
BATCH_STATUS_PARTIAL    = "PARTIAL"
BATCH_STATUS_COMPLETED  = "COMPLETED"
BATCH_STATUS_FAILED     = "FAILED"


@dataclass(frozen=True)
class SettlementBatchRequest:
    items: tuple[SettlementWorkflowRequest, ...]
    mode: str
    batch_id: str = field(default_factory=new_batch_id)
    correlation_id: str = field(default_factory=new_batch_id)
    queued_at: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True)
class BatchItemResult:
    workflow_id: str
    status: str
    success: bool
    settlement_id: str | None = None
    blocked_reason: str | None = None
    simulated: bool = False


@dataclass(frozen=True)
class SettlementBatchResult:
    batch_id: str
    batch_status: str
    total_items: int
    completed_count: int
    failed_count: int
    blocked_count: int
    partial: bool
    item_results: tuple[BatchItemResult, ...]
    mode: str = "paper"
    processed_at: datetime = field(default_factory=_utc_now)
    trace_refs: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Section 46 — Reconciliation constants and schemas
# ---------------------------------------------------------------------------

RECON_OUTCOME_MATCH      = "match"
RECON_OUTCOME_MISMATCH   = "mismatch"
RECON_OUTCOME_STUCK      = "stuck"
RECON_OUTCOME_MISSING    = "missing"
RECON_OUTCOME_ORPHAN     = "orphan"
RECON_OUTCOME_BLOCKED    = "blocked"

RECON_STUCK_THRESHOLD_S: float = 300.0

REPAIR_ACTION_RETRY       = "repair_retry"
REPAIR_ACTION_CANCEL      = "repair_cancel"
REPAIR_ACTION_FLAG_MANUAL = "repair_flag_manual"
REPAIR_ACTION_NO_ACTION   = "repair_no_action"


@dataclass(frozen=True)
class ReconciliationEntry:
    workflow_id: str
    internal_status: str
    internal_amount: float
    age_s: float
    settlement_id: str | None = None
    external_status: str | None = None
    external_amount: float | None = None
    trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReconciliationResult:
    workflow_id: str
    outcome: str
    repair_action: str
    is_stuck: bool
    internal_status: str
    settlement_id: str | None = None
    mismatch_reason: str | None = None
    external_status: str | None = None
    trace_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BatchReconciliationResult:
    total_checked: int
    match_count: int
    mismatch_count: int
    stuck_count: int
    missing_count: int
    orphan_count: int
    results: tuple[ReconciliationResult, ...]
    checked_at: datetime = field(default_factory=_utc_now)
    trace_refs: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Section 47 — Operator Console schemas
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SettlementStatusView:
    workflow_id: str
    status: str
    amount: float
    currency: str
    wallet_id: str
    mode: str
    retry_attempt_count: int
    created_at: datetime
    updated_at: datetime
    settlement_id: str | None = None
    last_blocked_reason: str | None = None


@dataclass(frozen=True)
class RetryStatusView:
    workflow_id: str
    current_attempt: int
    max_attempts: int
    last_outcome: str
    is_exhausted: bool
    is_fatal: bool
    next_retry_at: datetime | None = None


@dataclass(frozen=True)
class FailedBatchView:
    batch_id: str
    batch_status: str
    total_items: int
    failed_count: int
    queued_at: datetime
    failed_workflow_ids: tuple[str, ...]


@dataclass(frozen=True)
class AdminInterventionRequest:
    workflow_id: str
    action: str
    admin_user_id: str
    reason: str
    intervention_id: str = field(default_factory=new_intervention_id)
    correlation_id: str = field(default_factory=new_intervention_id)


@dataclass(frozen=True)
class AdminInterventionResult:
    workflow_id: str
    action: str
    success: bool
    previous_status: str
    new_status: str | None = None
    blocked_reason: str | None = None
    trace_refs: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Section 48 — Persistence event types and schemas
# ---------------------------------------------------------------------------

SETTLEMENT_EVENT_CREATED        = "settlement_created"
SETTLEMENT_EVENT_PROCESSING     = "settlement_processing"
SETTLEMENT_EVENT_COMPLETED      = "settlement_completed"
SETTLEMENT_EVENT_FAILED         = "settlement_failed"
SETTLEMENT_EVENT_RETRY_QUEUED   = "settlement_retry_queued"
SETTLEMENT_EVENT_RETRY_ATTEMPT  = "settlement_retry_attempt"
SETTLEMENT_EVENT_CANCELLED      = "settlement_cancelled"
SETTLEMENT_EVENT_RECONCILED     = "settlement_reconciled"
SETTLEMENT_EVENT_DRIFT_DETECTED = "settlement_drift_detected"


@dataclass(frozen=True)
class SettlementEvent:
    event_type: str
    workflow_id: str
    payload: dict[str, Any]
    event_id: str = field(default_factory=new_event_id)
    settlement_id: str | None = None
    occurred_at: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True)
class AlertClassification:
    is_critical: bool
    is_drift: bool
    alert_reason: str
    workflow_id: str
    settlement_id: str | None = None
