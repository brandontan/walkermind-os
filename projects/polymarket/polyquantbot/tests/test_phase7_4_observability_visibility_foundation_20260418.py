"""Phase 7.4 -- Observability / Visibility Foundation Tests.

Validates the deterministic visibility record builder implemented in
monitoring/observability_foundation.py.

Coverage:
  OBS-01   monitoring: visible when anomaly present (BLOCK decision)
  OBS-02   monitoring: visible when HALT anomaly (KILL_SWITCH_TRIGGERED)
  OBS-03   monitoring: visible when multiple anomalies (primary surfaced)
  OBS-04   monitoring: partial when ALLOW decision (no anomalies)
  OBS-05   monitoring: blocked when INVALID_CONTRACT_INPUT in anomaly set
  OBS-06   monitoring: trace_id propagated
  OBS-07   monitoring: all fields from evaluation_result propagated
  OBS-08   monitoring: visibility_note contains status token
  OBS-09   scheduler: visible when triggered
  OBS-10   scheduler: trigger_result_category propagated on triggered result
  OBS-11   scheduler: partial when skipped -- already_running
  OBS-12   scheduler: partial when skipped -- window_not_open
  OBS-13   scheduler: partial when skipped -- quota_reached
  OBS-14   scheduler: blocked when blocked -- schedule_disabled
  OBS-15   scheduler: blocked when blocked -- invalid_contract
  OBS-16   scheduler: trace_id propagated
  OBS-17   scheduler: visibility_note contains status token
  OBS-18   loop: visible when completed
  OBS-19   loop: visible when stopped_hold
  OBS-20   loop: visible when stopped_blocked
  OBS-21   loop: partial when exhausted (no triggers fired)
  OBS-22   loop: blocked when invalid_contract
  OBS-23   loop: trigger_fire_count computed correctly
  OBS-24   loop: iterations_run propagated
  OBS-25   loop: per-iteration visibility records built
  OBS-26   loop: iteration_visibility_records count matches iterations_run
  OBS-27   loop: per-iteration trace_id contains parent trace_id
  OBS-28   loop: visibility_note contains status token
  OBS-29   module-level record_monitoring_visibility entrypoint works
  OBS-30   module-level record_scheduler_visibility entrypoint works
  OBS-31   module-level record_loop_visibility entrypoint works
  OBS-32   determinism -- equal inputs produce equal outputs (monitoring)
  OBS-33   determinism -- equal inputs produce equal outputs (scheduler)
"""
from __future__ import annotations

from projects.polymarket.polyquantbot.api.public_activation_trigger_cli import (
    PublicActivationTriggerResult,
)
from projects.polymarket.polyquantbot.core.lightweight_activation_scheduler import (
    SCHEDULER_BLOCK_INVALID_CONTRACT,
    SCHEDULER_BLOCK_SCHEDULE_DISABLED,
    SCHEDULER_RESULT_BLOCKED,
    SCHEDULER_RESULT_SKIPPED,
    SCHEDULER_RESULT_TRIGGERED,
    SCHEDULER_SKIP_ALREADY_RUNNING,
    SCHEDULER_SKIP_QUOTA_REACHED,
    SCHEDULER_SKIP_WINDOW_NOT_OPEN,
    SchedulerInvocationPolicy,
    SchedulerInvocationResult,
    decide_and_invoke_scheduler,
)
from projects.polymarket.polyquantbot.core.runtime_auto_run_loop import (
    LOOP_RESULT_COMPLETED,
    LOOP_RESULT_EXHAUSTED,
    LOOP_RESULT_STOPPED_BLOCKED,
    LOOP_RESULT_STOPPED_HOLD,
    LOOP_STOP_INVALID_CONTRACT,
    LOOP_STOP_NO_TRIGGERS_FIRED,
    run_auto_loop,
)
from projects.polymarket.polyquantbot.monitoring.foundation import (
    MonitoringAnomalyCategory,
    MonitoringContractInput,
    MonitoringDecision,
    evaluate_monitoring_contract,
)
from projects.polymarket.polyquantbot.monitoring.observability_foundation import (
    LoopOutcomeVisibilityRecord,
    MonitoringEvaluationVisibilityRecord,
    ObservabilityVisibilityBoundary,
    SchedulerDecisionVisibilityRecord,
    VisibilityStatus,
    record_loop_visibility,
    record_monitoring_visibility,
    record_scheduler_visibility,
)
from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
    PublicActivationCyclePolicy,
    WALLET_CORRECTION_RESULT_ACCEPTED,
    WALLET_CORRECTION_RESULT_BLOCKED,
    WALLET_RECONCILIATION_OUTCOME_MATCH,
    WALLET_RECONCILIATION_OUTCOME_REVISION_MISMATCH,
    WALLET_RETRY_WORK_DECISION_SKIPPED,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean_monitoring_input(**overrides) -> MonitoringContractInput:  # type: ignore[no-untyped-def]
    defaults: dict = dict(
        policy_ref="policy-v1",
        eval_ref="eval-001",
        timestamp_ms=1_700_000_000_000,
        exposure_ratio=0.05,
        position_notional_usd=500.0,
        total_capital_usd=10_000.0,
        data_freshness_ms=200,
        quality_score=0.90,
        signal_dedup_ok=True,
        kill_switch_armed=False,
        kill_switch_triggered=False,
        monitoring_enabled=True,
        quality_guard_enabled=True,
        exposure_guard_enabled=True,
        max_exposure_ratio=0.10,
        max_data_freshness_ms=5_000,
        min_quality_score=0.60,
    )
    defaults.update(overrides)
    return MonitoringContractInput(**defaults)


def _triggered_scheduler_result(trigger_result_category: str = "completed") -> SchedulerInvocationResult:
    trigger = PublicActivationTriggerResult(
        trigger_result=trigger_result_category,
        cycle_result_category=trigger_result_category,
        cycle_stop_reason=None,
        cycle_completed=(trigger_result_category == "completed"),
        wallet_binding_id="wallet-obs-1",
        owner_user_id="user-obs-1",
        cycle_notes=[],
    )
    return SchedulerInvocationResult(
        scheduler_result=SCHEDULER_RESULT_TRIGGERED,
        skip_reason=None,
        block_reason=None,
        trigger_result=trigger,
        scheduler_notes=["triggering: all scheduling conditions met"],
    )


def _skipped_scheduler_result(skip_reason: str) -> SchedulerInvocationResult:
    return SchedulerInvocationResult(
        scheduler_result=SCHEDULER_RESULT_SKIPPED,
        skip_reason=skip_reason,
        block_reason=None,
        trigger_result=None,
        scheduler_notes=[f"skipped: {skip_reason}"],
    )


def _blocked_scheduler_result(block_reason: str) -> SchedulerInvocationResult:
    return SchedulerInvocationResult(
        scheduler_result=SCHEDULER_RESULT_BLOCKED,
        skip_reason=None,
        block_reason=block_reason,
        trigger_result=None,
        scheduler_notes=[f"blocked: {block_reason}"],
    )


def _trigger_policy(**kwargs) -> PublicActivationCyclePolicy:  # type: ignore[no-untyped-def]
    defaults: dict = {
        "wallet_binding_id": "wallet-obs-1",
        "owner_user_id": "user-obs-1",
        "requester_user_id": "user-obs-1",
        "wallet_active": True,
        "state_read_batch_ready": True,
        "reconciliation_outcome": WALLET_RECONCILIATION_OUTCOME_MATCH,
        "correction_result_category": WALLET_CORRECTION_RESULT_ACCEPTED,
        "retry_result_category": WALLET_RETRY_WORK_DECISION_SKIPPED,
    }
    defaults.update(kwargs)
    return PublicActivationCyclePolicy(**defaults)


def _scheduler_policy(**kwargs) -> SchedulerInvocationPolicy:  # type: ignore[no-untyped-def]
    defaults: dict = {
        "trigger_policy": _trigger_policy(),
        "schedule_enabled": True,
        "invocation_window_open": True,
        "invocation_quota_remaining": 10,
        "concurrent_invocation_active": False,
    }
    defaults.update(kwargs)
    return SchedulerInvocationPolicy(**defaults)


def _completed_scheduler_policy() -> SchedulerInvocationPolicy:
    return _scheduler_policy()


def _stopped_hold_scheduler_policy() -> SchedulerInvocationPolicy:
    return _scheduler_policy(
        trigger_policy=_trigger_policy(correction_result_category=WALLET_CORRECTION_RESULT_BLOCKED)
    )


def _stopped_blocked_scheduler_policy() -> SchedulerInvocationPolicy:
    return _scheduler_policy(
        trigger_policy=_trigger_policy(
            reconciliation_outcome=WALLET_RECONCILIATION_OUTCOME_REVISION_MISMATCH
        )
    )


def _scheduler_skipped_policy() -> SchedulerInvocationPolicy:
    return _scheduler_policy(invocation_window_open=False)


def _scheduler_blocked_policy() -> SchedulerInvocationPolicy:
    return _scheduler_policy(schedule_enabled=False)


_boundary = ObservabilityVisibilityBoundary()


# ---------------------------------------------------------------------------
# OBS-01  monitoring: visible when anomaly present (BLOCK decision)
# ---------------------------------------------------------------------------


def test_monitoring_visible_when_block_anomaly() -> None:
    result = evaluate_monitoring_contract(_clean_monitoring_input(exposure_ratio=0.15))
    record = _boundary.record_monitoring_evaluation("trace-001", result)
    assert record.visibility_status == VisibilityStatus.VISIBLE


# ---------------------------------------------------------------------------
# OBS-02  monitoring: visible when HALT anomaly (KILL_SWITCH_TRIGGERED)
# ---------------------------------------------------------------------------


def test_monitoring_visible_when_halt_anomaly() -> None:
    result = evaluate_monitoring_contract(
        _clean_monitoring_input(kill_switch_armed=True, kill_switch_triggered=True)
    )
    record = _boundary.record_monitoring_evaluation("trace-002", result)
    assert record.visibility_status == VisibilityStatus.VISIBLE
    assert record.decision == MonitoringDecision.HALT


# ---------------------------------------------------------------------------
# OBS-03  monitoring: visible when multiple anomalies (primary surfaced)
# ---------------------------------------------------------------------------


def test_monitoring_visible_with_multiple_anomalies_surfaces_primary() -> None:
    result = evaluate_monitoring_contract(
        _clean_monitoring_input(
            exposure_ratio=0.15,
            data_freshness_ms=10_000,
            quality_score=0.10,
        )
    )
    record = _boundary.record_monitoring_evaluation("trace-003", result)
    assert record.visibility_status == VisibilityStatus.VISIBLE
    assert len(record.all_anomalies) > 1
    assert record.primary_anomaly is not None


# ---------------------------------------------------------------------------
# OBS-04  monitoring: partial when ALLOW decision (no anomalies)
# ---------------------------------------------------------------------------


def test_monitoring_partial_when_allow() -> None:
    result = evaluate_monitoring_contract(_clean_monitoring_input())
    record = _boundary.record_monitoring_evaluation("trace-004", result)
    assert record.visibility_status == VisibilityStatus.PARTIAL
    assert record.decision == MonitoringDecision.ALLOW


# ---------------------------------------------------------------------------
# OBS-05  monitoring: blocked when INVALID_CONTRACT_INPUT in anomaly set
# ---------------------------------------------------------------------------


def test_monitoring_blocked_when_invalid_contract_input() -> None:
    result = evaluate_monitoring_contract(_clean_monitoring_input(policy_ref=""))
    assert MonitoringAnomalyCategory.INVALID_CONTRACT_INPUT in result.all_anomalies
    record = _boundary.record_monitoring_evaluation("trace-005", result)
    assert record.visibility_status == VisibilityStatus.BLOCKED


# ---------------------------------------------------------------------------
# OBS-06  monitoring: trace_id propagated
# ---------------------------------------------------------------------------


def test_monitoring_trace_id_propagated() -> None:
    result = evaluate_monitoring_contract(_clean_monitoring_input(exposure_ratio=0.15))
    record = _boundary.record_monitoring_evaluation("my-trace-id", result)
    assert record.trace_id == "my-trace-id"


# ---------------------------------------------------------------------------
# OBS-07  monitoring: all fields from evaluation_result propagated
# ---------------------------------------------------------------------------


def test_monitoring_evaluation_fields_propagated() -> None:
    inp = _clean_monitoring_input()
    result = evaluate_monitoring_contract(inp)
    record = _boundary.record_monitoring_evaluation("trace-007", result)
    assert record.policy_ref == inp.policy_ref
    assert record.eval_ref == inp.eval_ref
    assert record.timestamp_ms == inp.timestamp_ms
    assert record.decision == result.decision
    assert record.primary_anomaly == result.primary_anomaly
    assert record.all_anomalies == result.all_anomalies


# ---------------------------------------------------------------------------
# OBS-08  monitoring: visibility_note contains status token
# ---------------------------------------------------------------------------


def test_monitoring_visibility_note_contains_status_token_visible() -> None:
    result = evaluate_monitoring_contract(_clean_monitoring_input(exposure_ratio=0.15))
    record = _boundary.record_monitoring_evaluation("trace-008", result)
    assert "visible" in record.visibility_note


def test_monitoring_visibility_note_contains_status_token_partial() -> None:
    result = evaluate_monitoring_contract(_clean_monitoring_input())
    record = _boundary.record_monitoring_evaluation("trace-008b", result)
    assert "partial" in record.visibility_note


def test_monitoring_visibility_note_contains_status_token_blocked() -> None:
    result = evaluate_monitoring_contract(_clean_monitoring_input(policy_ref=""))
    record = _boundary.record_monitoring_evaluation("trace-008c", result)
    assert "blocked" in record.visibility_note


# ---------------------------------------------------------------------------
# OBS-09  scheduler: visible when triggered
# ---------------------------------------------------------------------------


def test_scheduler_visible_when_triggered() -> None:
    sr = _triggered_scheduler_result("completed")
    record = _boundary.record_scheduler_decision("trace-009", sr)
    assert record.visibility_status == VisibilityStatus.VISIBLE


# ---------------------------------------------------------------------------
# OBS-10  scheduler: trigger_result_category propagated on triggered result
# ---------------------------------------------------------------------------


def test_scheduler_trigger_result_category_propagated_completed() -> None:
    sr = _triggered_scheduler_result("completed")
    record = _boundary.record_scheduler_decision("trace-010", sr)
    assert record.trigger_result_category == "completed"


def test_scheduler_trigger_result_category_propagated_stopped_hold() -> None:
    sr = _triggered_scheduler_result("stopped_hold")
    record = _boundary.record_scheduler_decision("trace-010b", sr)
    assert record.trigger_result_category == "stopped_hold"


def test_scheduler_trigger_result_category_propagated_stopped_blocked() -> None:
    sr = _triggered_scheduler_result("stopped_blocked")
    record = _boundary.record_scheduler_decision("trace-010c", sr)
    assert record.trigger_result_category == "stopped_blocked"


# ---------------------------------------------------------------------------
# OBS-11  scheduler: partial when skipped -- already_running
# ---------------------------------------------------------------------------


def test_scheduler_partial_when_skipped_already_running() -> None:
    sr = _skipped_scheduler_result(SCHEDULER_SKIP_ALREADY_RUNNING)
    record = _boundary.record_scheduler_decision("trace-011", sr)
    assert record.visibility_status == VisibilityStatus.PARTIAL
    assert record.skip_reason == SCHEDULER_SKIP_ALREADY_RUNNING


# ---------------------------------------------------------------------------
# OBS-12  scheduler: partial when skipped -- window_not_open
# ---------------------------------------------------------------------------


def test_scheduler_partial_when_skipped_window_not_open() -> None:
    sr = _skipped_scheduler_result(SCHEDULER_SKIP_WINDOW_NOT_OPEN)
    record = _boundary.record_scheduler_decision("trace-012", sr)
    assert record.visibility_status == VisibilityStatus.PARTIAL


# ---------------------------------------------------------------------------
# OBS-13  scheduler: partial when skipped -- quota_reached
# ---------------------------------------------------------------------------


def test_scheduler_partial_when_skipped_quota_reached() -> None:
    sr = _skipped_scheduler_result(SCHEDULER_SKIP_QUOTA_REACHED)
    record = _boundary.record_scheduler_decision("trace-013", sr)
    assert record.visibility_status == VisibilityStatus.PARTIAL


# ---------------------------------------------------------------------------
# OBS-14  scheduler: blocked when blocked -- schedule_disabled
# ---------------------------------------------------------------------------


def test_scheduler_blocked_when_schedule_disabled() -> None:
    sr = _blocked_scheduler_result(SCHEDULER_BLOCK_SCHEDULE_DISABLED)
    record = _boundary.record_scheduler_decision("trace-014", sr)
    assert record.visibility_status == VisibilityStatus.BLOCKED
    assert record.block_reason == SCHEDULER_BLOCK_SCHEDULE_DISABLED


# ---------------------------------------------------------------------------
# OBS-15  scheduler: blocked when blocked -- invalid_contract
# ---------------------------------------------------------------------------


def test_scheduler_blocked_when_invalid_contract() -> None:
    sr = _blocked_scheduler_result(SCHEDULER_BLOCK_INVALID_CONTRACT)
    record = _boundary.record_scheduler_decision("trace-015", sr)
    assert record.visibility_status == VisibilityStatus.BLOCKED
    assert record.block_reason == SCHEDULER_BLOCK_INVALID_CONTRACT


# ---------------------------------------------------------------------------
# OBS-16  scheduler: trace_id propagated
# ---------------------------------------------------------------------------


def test_scheduler_trace_id_propagated() -> None:
    sr = _triggered_scheduler_result("completed")
    record = _boundary.record_scheduler_decision("sched-trace-id", sr)
    assert record.trace_id == "sched-trace-id"


# ---------------------------------------------------------------------------
# OBS-17  scheduler: visibility_note contains status token
# ---------------------------------------------------------------------------


def test_scheduler_visibility_note_contains_visible_token() -> None:
    sr = _triggered_scheduler_result("completed")
    record = _boundary.record_scheduler_decision("trace-017", sr)
    assert "visible" in record.visibility_note


def test_scheduler_visibility_note_contains_partial_token() -> None:
    sr = _skipped_scheduler_result(SCHEDULER_SKIP_WINDOW_NOT_OPEN)
    record = _boundary.record_scheduler_decision("trace-017b", sr)
    assert "partial" in record.visibility_note


def test_scheduler_visibility_note_contains_blocked_token() -> None:
    sr = _blocked_scheduler_result(SCHEDULER_BLOCK_SCHEDULE_DISABLED)
    record = _boundary.record_scheduler_decision("trace-017c", sr)
    assert "blocked" in record.visibility_note


# ---------------------------------------------------------------------------
# OBS-18  loop: visible when completed
# ---------------------------------------------------------------------------


def test_loop_visible_when_completed() -> None:
    loop_res = run_auto_loop(_completed_scheduler_policy(), max_iterations=2)
    assert loop_res.loop_result == LOOP_RESULT_COMPLETED
    record = _boundary.record_loop_outcome("trace-018", loop_res)
    assert record.visibility_status == VisibilityStatus.VISIBLE


# ---------------------------------------------------------------------------
# OBS-19  loop: visible when stopped_hold
# ---------------------------------------------------------------------------


def test_loop_visible_when_stopped_hold() -> None:
    loop_res = run_auto_loop(_stopped_hold_scheduler_policy(), max_iterations=3)
    assert loop_res.loop_result == LOOP_RESULT_STOPPED_HOLD
    record = _boundary.record_loop_outcome("trace-019", loop_res)
    assert record.visibility_status == VisibilityStatus.VISIBLE


# ---------------------------------------------------------------------------
# OBS-20  loop: visible when stopped_blocked
# ---------------------------------------------------------------------------


def test_loop_visible_when_stopped_blocked() -> None:
    loop_res = run_auto_loop(_stopped_blocked_scheduler_policy(), max_iterations=3)
    assert loop_res.loop_result == LOOP_RESULT_STOPPED_BLOCKED
    record = _boundary.record_loop_outcome("trace-020", loop_res)
    assert record.visibility_status == VisibilityStatus.VISIBLE


# ---------------------------------------------------------------------------
# OBS-21  loop: partial when exhausted (no triggers fired)
# ---------------------------------------------------------------------------


def test_loop_partial_when_exhausted_no_triggers() -> None:
    loop_res = run_auto_loop(_scheduler_skipped_policy(), max_iterations=3)
    assert loop_res.loop_result == LOOP_RESULT_EXHAUSTED
    assert loop_res.loop_stop_reason == LOOP_STOP_NO_TRIGGERS_FIRED
    record = _boundary.record_loop_outcome("trace-021", loop_res)
    assert record.visibility_status == VisibilityStatus.PARTIAL


# ---------------------------------------------------------------------------
# OBS-22  loop: blocked when invalid_contract
# ---------------------------------------------------------------------------


def test_loop_blocked_when_invalid_contract() -> None:
    loop_res = run_auto_loop(_completed_scheduler_policy(), max_iterations=0)
    assert loop_res.loop_stop_reason == LOOP_STOP_INVALID_CONTRACT
    record = _boundary.record_loop_outcome("trace-022", loop_res)
    assert record.visibility_status == VisibilityStatus.BLOCKED


# ---------------------------------------------------------------------------
# OBS-23  loop: trigger_fire_count computed correctly
# ---------------------------------------------------------------------------


def test_loop_trigger_fire_count_completed_two_iterations() -> None:
    loop_res = run_auto_loop(_completed_scheduler_policy(), max_iterations=2)
    record = _boundary.record_loop_outcome("trace-023", loop_res)
    assert record.trigger_fire_count == 2


def test_loop_trigger_fire_count_zero_when_all_skipped() -> None:
    loop_res = run_auto_loop(_scheduler_skipped_policy(), max_iterations=3)
    record = _boundary.record_loop_outcome("trace-023b", loop_res)
    assert record.trigger_fire_count == 0


def test_loop_trigger_fire_count_one_when_stopped_hold_at_first_iteration() -> None:
    loop_res = run_auto_loop(_stopped_hold_scheduler_policy(), max_iterations=5)
    record = _boundary.record_loop_outcome("trace-023c", loop_res)
    assert record.trigger_fire_count == 1


# ---------------------------------------------------------------------------
# OBS-24  loop: iterations_run propagated
# ---------------------------------------------------------------------------


def test_loop_iterations_run_propagated() -> None:
    loop_res = run_auto_loop(_completed_scheduler_policy(), max_iterations=3)
    record = _boundary.record_loop_outcome("trace-024", loop_res)
    assert record.iterations_run == loop_res.iterations_run


# ---------------------------------------------------------------------------
# OBS-25  loop: per-iteration visibility records built
# ---------------------------------------------------------------------------


def test_loop_per_iteration_visibility_records_have_scheduler_visibility() -> None:
    loop_res = run_auto_loop(_completed_scheduler_policy(), max_iterations=2)
    record = _boundary.record_loop_outcome("trace-025", loop_res)
    for iter_vis in record.iteration_visibility_records:
        assert isinstance(iter_vis.scheduler_visibility, SchedulerDecisionVisibilityRecord)


# ---------------------------------------------------------------------------
# OBS-26  loop: iteration_visibility_records count matches iterations_run
# ---------------------------------------------------------------------------


def test_loop_iteration_visibility_records_count_matches_iterations_run() -> None:
    loop_res = run_auto_loop(_completed_scheduler_policy(), max_iterations=3)
    record = _boundary.record_loop_outcome("trace-026", loop_res)
    assert len(record.iteration_visibility_records) == loop_res.iterations_run


def test_loop_iteration_visibility_records_empty_on_invalid_contract() -> None:
    loop_res = run_auto_loop(_completed_scheduler_policy(), max_iterations=0)
    record = _boundary.record_loop_outcome("trace-026b", loop_res)
    assert len(record.iteration_visibility_records) == 0


# ---------------------------------------------------------------------------
# OBS-27  loop: per-iteration trace_id contains parent trace_id
# ---------------------------------------------------------------------------


def test_loop_per_iteration_trace_id_contains_parent_trace_id() -> None:
    loop_res = run_auto_loop(_completed_scheduler_policy(), max_iterations=2)
    record = _boundary.record_loop_outcome("parent-trace", loop_res)
    for iter_vis in record.iteration_visibility_records:
        assert "parent-trace" in iter_vis.trace_id


def test_loop_per_iteration_trace_id_contains_iteration_index() -> None:
    loop_res = run_auto_loop(_completed_scheduler_policy(), max_iterations=2)
    record = _boundary.record_loop_outcome("loop-trace", loop_res)
    for iter_vis in record.iteration_visibility_records:
        assert f"iter={iter_vis.iteration_index}" in iter_vis.trace_id


# ---------------------------------------------------------------------------
# OBS-28  loop: visibility_note contains status token
# ---------------------------------------------------------------------------


def test_loop_visibility_note_contains_visible_token() -> None:
    loop_res = run_auto_loop(_completed_scheduler_policy(), max_iterations=1)
    record = _boundary.record_loop_outcome("trace-028", loop_res)
    assert "visible" in record.visibility_note


def test_loop_visibility_note_contains_partial_token() -> None:
    loop_res = run_auto_loop(_scheduler_skipped_policy(), max_iterations=2)
    record = _boundary.record_loop_outcome("trace-028b", loop_res)
    assert "partial" in record.visibility_note


def test_loop_visibility_note_contains_blocked_token() -> None:
    loop_res = run_auto_loop(_completed_scheduler_policy(), max_iterations=0)
    record = _boundary.record_loop_outcome("trace-028c", loop_res)
    assert "blocked" in record.visibility_note


# ---------------------------------------------------------------------------
# OBS-29  module-level record_monitoring_visibility entrypoint works
# ---------------------------------------------------------------------------


def test_module_level_record_monitoring_visibility_returns_correct_type() -> None:
    result = evaluate_monitoring_contract(_clean_monitoring_input())
    record = record_monitoring_visibility("trace-029", result)
    assert isinstance(record, MonitoringEvaluationVisibilityRecord)


# ---------------------------------------------------------------------------
# OBS-30  module-level record_scheduler_visibility entrypoint works
# ---------------------------------------------------------------------------


def test_module_level_record_scheduler_visibility_returns_correct_type() -> None:
    sr = _triggered_scheduler_result("completed")
    record = record_scheduler_visibility("trace-030", sr)
    assert isinstance(record, SchedulerDecisionVisibilityRecord)


# ---------------------------------------------------------------------------
# OBS-31  module-level record_loop_visibility entrypoint works
# ---------------------------------------------------------------------------


def test_module_level_record_loop_visibility_returns_correct_type() -> None:
    loop_res = run_auto_loop(_completed_scheduler_policy(), max_iterations=1)
    record = record_loop_visibility("trace-031", loop_res)
    assert isinstance(record, LoopOutcomeVisibilityRecord)


# ---------------------------------------------------------------------------
# OBS-32  determinism -- equal inputs produce equal outputs (monitoring)
# ---------------------------------------------------------------------------


def test_monitoring_determinism_equal_inputs_equal_outputs() -> None:
    result = evaluate_monitoring_contract(_clean_monitoring_input(exposure_ratio=0.15))
    r1 = _boundary.record_monitoring_evaluation("trace-det", result)
    r2 = _boundary.record_monitoring_evaluation("trace-det", result)
    assert r1 == r2


# ---------------------------------------------------------------------------
# OBS-33  determinism -- equal inputs produce equal outputs (scheduler)
# ---------------------------------------------------------------------------


def test_scheduler_determinism_equal_inputs_equal_outputs() -> None:
    sr = _triggered_scheduler_result("completed")
    r1 = _boundary.record_scheduler_decision("trace-det", sr)
    r2 = _boundary.record_scheduler_decision("trace-det", sr)
    assert r1 == r2
