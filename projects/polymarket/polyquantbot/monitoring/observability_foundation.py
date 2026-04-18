"""Phase 7.4 -- Observability / Visibility Foundation.

Narrow deterministic visibility layer over:
  - Phase 6.4.1 monitoring evaluation results  (MonitoringEvaluationResult)
  - Phase 7.2 scheduler invocation decisions   (SchedulerInvocationResult)
  - Phase 7.3 runtime auto-run loop outcomes   (RuntimeAutoRunLoopResult)

Visibility categories (deterministic, pure):
  visible  -- full trace fields available; anomaly or trigger outcome surfaced
  partial  -- record available; detail fields absent or non-anomalous
  blocked  -- evaluation poisoned (INVALID_CONTRACT_INPUT) or scheduler hard-blocked

Visibility status rules:
  MonitoringEvaluationVisibilityRecord:
    blocked  if INVALID_CONTRACT_INPUT in all_anomalies
    partial  if decision == ALLOW (no anomalies)
    visible  otherwise (anomalies present, contract valid)

  SchedulerDecisionVisibilityRecord:
    blocked  if scheduler_result == "blocked"
    partial  if scheduler_result == "skipped"
    visible  if scheduler_result == "triggered"

  LoopOutcomeVisibilityRecord:
    blocked  if loop_stop_reason == "invalid_contract"
    partial  if loop_result == "exhausted" (and not invalid_contract)
    visible  if loop_result in (completed / stopped_hold / stopped_blocked)

Pure functions -- no state, no side effects, no async, no alert transport.
No dashboards, no distributed monitoring mesh, no async workers,
no cron daemon rollout, no remediation automation, no live trading enablement.

Claim Level : NARROW INTEGRATION
Not in scope: alert delivery, dashboards, distributed monitoring mesh,
              async workers, cron daemon rollout, remediation automation,
              live trading enablement, broader production observability program.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from projects.polymarket.polyquantbot.monitoring.foundation import (
    MonitoringAnomalyCategory,
    MonitoringDecision,
    MonitoringEvaluationResult,
)
from projects.polymarket.polyquantbot.core.lightweight_activation_scheduler import (
    SCHEDULER_RESULT_BLOCKED,
    SCHEDULER_RESULT_TRIGGERED,
    SchedulerInvocationResult,
)
from projects.polymarket.polyquantbot.core.runtime_auto_run_loop import (
    LOOP_RESULT_COMPLETED,
    LOOP_RESULT_STOPPED_BLOCKED,
    LOOP_RESULT_STOPPED_HOLD,
    LOOP_STOP_INVALID_CONTRACT,
    RuntimeAutoRunLoopResult,
)


# ---------------------------------------------------------------------------
# Visibility status categories
# ---------------------------------------------------------------------------


class VisibilityStatus(str, Enum):
    """Deterministic visibility categories for Phase 7.4 observability records."""

    VISIBLE = "visible"    # full trace; anomaly or trigger outcome surfaced
    PARTIAL = "partial"    # record available; detail absent or non-anomalous
    BLOCKED = "blocked"    # evaluation poisoned or hard-blocked


# ---------------------------------------------------------------------------
# Per-surface visibility record types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MonitoringEvaluationVisibilityRecord:
    """Deterministic visibility record for a Phase 6.4.1 monitoring evaluation."""

    trace_id: str
    visibility_status: VisibilityStatus
    decision: MonitoringDecision
    primary_anomaly: Optional[MonitoringAnomalyCategory]
    all_anomalies: tuple[MonitoringAnomalyCategory, ...]
    policy_ref: str
    eval_ref: str
    timestamp_ms: int
    visibility_note: str


@dataclass(frozen=True)
class SchedulerDecisionVisibilityRecord:
    """Deterministic visibility record for a Phase 7.2 scheduler invocation decision."""

    trace_id: str
    visibility_status: VisibilityStatus
    scheduler_result: str
    skip_reason: Optional[str]
    block_reason: Optional[str]
    trigger_result_category: Optional[str]
    visibility_note: str


@dataclass(frozen=True)
class LoopIterationVisibilityRecord:
    """Per-iteration visibility record within a Phase 7.3 auto-run loop run."""

    trace_id: str
    iteration_index: int
    scheduler_visibility: SchedulerDecisionVisibilityRecord
    iteration_visibility_note: str


@dataclass(frozen=True)
class LoopOutcomeVisibilityRecord:
    """Deterministic aggregate visibility record for a Phase 7.3 auto-run loop outcome."""

    trace_id: str
    visibility_status: VisibilityStatus
    loop_result: str
    loop_stop_reason: Optional[str]
    iterations_run: int
    trigger_fire_count: int
    iteration_visibility_records: list[LoopIterationVisibilityRecord]
    visibility_note: str


# ---------------------------------------------------------------------------
# Boundary class -- pure visibility record builder
# ---------------------------------------------------------------------------


class ObservabilityVisibilityBoundary:
    """Phase 7.4 deterministic visibility record builder.

    Pure methods -- no state, no side effects, no async, no alert transport.
    Equal inputs always produce equal outputs.
    """

    def record_monitoring_evaluation(
        self,
        trace_id: str,
        evaluation_result: MonitoringEvaluationResult,
    ) -> MonitoringEvaluationVisibilityRecord:
        """Build a deterministic visibility record for one 6.4.1 evaluation result.

        Visibility rules:
          blocked  if INVALID_CONTRACT_INPUT is in all_anomalies
          partial  if decision == ALLOW (no anomalies to surface)
          visible  otherwise
        """
        if MonitoringAnomalyCategory.INVALID_CONTRACT_INPUT in evaluation_result.all_anomalies:
            status = VisibilityStatus.BLOCKED
            note = (
                f"monitoring_evaluation: blocked -- INVALID_CONTRACT_INPUT"
                f" eval_ref={evaluation_result.eval_ref}"
            )
        elif evaluation_result.decision == MonitoringDecision.ALLOW:
            status = VisibilityStatus.PARTIAL
            note = "monitoring_evaluation: partial -- ALLOW decision, no anomalies"
        else:
            status = VisibilityStatus.VISIBLE
            primary_val = (
                evaluation_result.primary_anomaly.value
                if evaluation_result.primary_anomaly is not None
                else "none"
            )
            note = (
                f"monitoring_evaluation: visible -- {evaluation_result.decision.value}"
                f" primary_anomaly={primary_val}"
            )

        return MonitoringEvaluationVisibilityRecord(
            trace_id=trace_id,
            visibility_status=status,
            decision=evaluation_result.decision,
            primary_anomaly=evaluation_result.primary_anomaly,
            all_anomalies=evaluation_result.all_anomalies,
            policy_ref=evaluation_result.policy_ref,
            eval_ref=evaluation_result.eval_ref,
            timestamp_ms=evaluation_result.timestamp_ms,
            visibility_note=note,
        )

    def record_scheduler_decision(
        self,
        trace_id: str,
        scheduler_result: SchedulerInvocationResult,
    ) -> SchedulerDecisionVisibilityRecord:
        """Build a deterministic visibility record for one 7.2 scheduler decision.

        Visibility rules:
          blocked  if scheduler_result == "blocked"
          partial  if scheduler_result == "skipped"
          visible  if scheduler_result == "triggered"
        """
        trigger_result_category: Optional[str] = None
        if (
            scheduler_result.scheduler_result == SCHEDULER_RESULT_TRIGGERED
            and scheduler_result.trigger_result is not None
        ):
            trigger_result_category = scheduler_result.trigger_result.trigger_result

        if scheduler_result.scheduler_result == SCHEDULER_RESULT_BLOCKED:
            status = VisibilityStatus.BLOCKED
            note = (
                f"scheduler_decision: blocked -- block_reason={scheduler_result.block_reason}"
            )
        elif scheduler_result.scheduler_result == SCHEDULER_RESULT_TRIGGERED:
            status = VisibilityStatus.VISIBLE
            note = (
                f"scheduler_decision: visible -- triggered"
                f" trigger_result={trigger_result_category}"
            )
        else:
            # skipped
            status = VisibilityStatus.PARTIAL
            note = (
                f"scheduler_decision: partial -- {scheduler_result.scheduler_result}"
                f" skip_reason={scheduler_result.skip_reason}"
            )

        return SchedulerDecisionVisibilityRecord(
            trace_id=trace_id,
            visibility_status=status,
            scheduler_result=scheduler_result.scheduler_result,
            skip_reason=scheduler_result.skip_reason,
            block_reason=scheduler_result.block_reason,
            trigger_result_category=trigger_result_category,
            visibility_note=note,
        )

    def record_loop_outcome(
        self,
        trace_id: str,
        loop_result: RuntimeAutoRunLoopResult,
    ) -> LoopOutcomeVisibilityRecord:
        """Build a deterministic visibility record for one 7.3 loop run outcome.

        Per-iteration visibility is built from each LoopIterationRecord.
        trigger_fire_count is computed from iteration records (scheduler_result == triggered).

        Visibility rules:
          blocked  if loop_stop_reason == "invalid_contract"
          partial  if loop_result == "exhausted" (and not invalid_contract)
          visible  if loop_result in (completed / stopped_hold / stopped_blocked)
        """
        trigger_fire_count = 0
        iter_visibility_records: list[LoopIterationVisibilityRecord] = []

        for iter_rec in loop_result.iteration_records:
            iter_trace_id = f"{trace_id}:iter={iter_rec.iteration_index}"
            sched_vis = self.record_scheduler_decision(iter_trace_id, iter_rec.scheduler_result)
            if iter_rec.scheduler_result.scheduler_result == SCHEDULER_RESULT_TRIGGERED:
                trigger_fire_count += 1
            iter_note = (
                f"iteration={iter_rec.iteration_index}:"
                f" scheduler_visibility={sched_vis.visibility_status.value}"
            )
            iter_visibility_records.append(
                LoopIterationVisibilityRecord(
                    trace_id=iter_trace_id,
                    iteration_index=iter_rec.iteration_index,
                    scheduler_visibility=sched_vis,
                    iteration_visibility_note=iter_note,
                )
            )

        if loop_result.loop_stop_reason == LOOP_STOP_INVALID_CONTRACT:
            status = VisibilityStatus.BLOCKED
            note = "loop_outcome: blocked -- invalid_contract iterations_run=0"
        elif loop_result.loop_result in (
            LOOP_RESULT_COMPLETED,
            LOOP_RESULT_STOPPED_HOLD,
            LOOP_RESULT_STOPPED_BLOCKED,
        ):
            status = VisibilityStatus.VISIBLE
            note = (
                f"loop_outcome: visible -- {loop_result.loop_result}"
                f" iterations_run={loop_result.iterations_run}"
                f" triggers_fired={trigger_fire_count}"
            )
        else:
            # exhausted (non-invalid-contract)
            status = VisibilityStatus.PARTIAL
            note = (
                f"loop_outcome: partial -- exhausted"
                f" stop_reason={loop_result.loop_stop_reason}"
                f" iterations_run={loop_result.iterations_run}"
            )

        return LoopOutcomeVisibilityRecord(
            trace_id=trace_id,
            visibility_status=status,
            loop_result=loop_result.loop_result,
            loop_stop_reason=loop_result.loop_stop_reason,
            iterations_run=loop_result.iterations_run,
            trigger_fire_count=trigger_fire_count,
            iteration_visibility_records=iter_visibility_records,
            visibility_note=note,
        )


# ---------------------------------------------------------------------------
# Module-level entrypoints
# ---------------------------------------------------------------------------


def record_monitoring_visibility(
    trace_id: str,
    evaluation_result: MonitoringEvaluationResult,
) -> MonitoringEvaluationVisibilityRecord:
    """Deterministic visibility record entrypoint for a 6.4.1 monitoring evaluation."""
    return ObservabilityVisibilityBoundary().record_monitoring_evaluation(
        trace_id, evaluation_result
    )


def record_scheduler_visibility(
    trace_id: str,
    scheduler_result: SchedulerInvocationResult,
) -> SchedulerDecisionVisibilityRecord:
    """Deterministic visibility record entrypoint for a 7.2 scheduler decision."""
    return ObservabilityVisibilityBoundary().record_scheduler_decision(
        trace_id, scheduler_result
    )


def record_loop_visibility(
    trace_id: str,
    loop_result: RuntimeAutoRunLoopResult,
) -> LoopOutcomeVisibilityRecord:
    """Deterministic visibility record entrypoint for a 7.3 auto-run loop outcome."""
    return ObservabilityVisibilityBoundary().record_loop_outcome(trace_id, loop_result)
