from __future__ import annotations

from projects.polymarket.polyquantbot.core.lightweight_activation_scheduler import (
    SchedulerInvocationPolicy,
)
from projects.polymarket.polyquantbot.core.runtime_auto_run_loop import (
    LOOP_RESULT_COMPLETED,
    LOOP_RESULT_EXHAUSTED,
    LOOP_RESULT_STOPPED_BLOCKED,
    LOOP_RESULT_STOPPED_HOLD,
    LOOP_STOP_INVALID_CONTRACT,
    LOOP_STOP_NO_TRIGGERS_FIRED,
    LOOP_STOP_TRIGGER_RETURNED_STOPPED_BLOCKED,
    LOOP_STOP_TRIGGER_RETURNED_STOPPED_HOLD,
    run_auto_loop,
)
from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
    PublicActivationCyclePolicy,
    WALLET_CORRECTION_RESULT_ACCEPTED,
    WALLET_CORRECTION_RESULT_BLOCKED,
    WALLET_RECONCILIATION_OUTCOME_MATCH,
    WALLET_RECONCILIATION_OUTCOME_REVISION_MISMATCH,
    WALLET_RETRY_WORK_DECISION_SKIPPED,
)


def _trigger_policy(**kwargs) -> PublicActivationCyclePolicy:  # type: ignore[no-untyped-def]
    defaults: dict = {
        "wallet_binding_id": "wallet-loop-1",
        "owner_user_id": "user-loop-1",
        "requester_user_id": "user-loop-1",
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


def _completed_policy() -> SchedulerInvocationPolicy:
    """Policy that triggers a completed cycle on every iteration."""
    return _scheduler_policy()


def _stopped_hold_policy() -> SchedulerInvocationPolicy:
    """Policy that triggers a stopped_hold cycle on every iteration."""
    return _scheduler_policy(
        trigger_policy=_trigger_policy(
            correction_result_category=WALLET_CORRECTION_RESULT_BLOCKED
        )
    )


def _stopped_blocked_policy() -> SchedulerInvocationPolicy:
    """Policy that triggers a stopped_blocked cycle on every iteration."""
    return _scheduler_policy(
        trigger_policy=_trigger_policy(
            reconciliation_outcome=WALLET_RECONCILIATION_OUTCOME_REVISION_MISMATCH
        )
    )


def _scheduler_skipped_policy() -> SchedulerInvocationPolicy:
    """Policy where the scheduler skips every iteration (window not open)."""
    return _scheduler_policy(invocation_window_open=False)


def _scheduler_blocked_policy() -> SchedulerInvocationPolicy:
    """Policy where the scheduler blocks every iteration (disabled)."""
    return _scheduler_policy(schedule_enabled=False)


# --- completed path ---

def test_loop_returns_completed_when_all_iterations_trigger_completed() -> None:
    result = run_auto_loop(_completed_policy(), max_iterations=3)
    assert result.loop_result == LOOP_RESULT_COMPLETED


def test_loop_completed_has_none_stop_reason() -> None:
    result = run_auto_loop(_completed_policy(), max_iterations=2)
    assert result.loop_stop_reason is None


def test_loop_completed_runs_all_requested_iterations() -> None:
    result = run_auto_loop(_completed_policy(), max_iterations=3)
    assert result.iterations_run == 3


def test_loop_completed_records_match_iterations_run() -> None:
    result = run_auto_loop(_completed_policy(), max_iterations=2)
    assert len(result.iteration_records) == 2


def test_loop_completed_notes_include_completion_summary() -> None:
    result = run_auto_loop(_completed_policy(), max_iterations=1)
    assert any("completed" in note for note in result.loop_notes)


# --- exhausted path: no triggers fired (scheduler skips) ---

def test_loop_returns_exhausted_when_scheduler_skips_all_iterations() -> None:
    result = run_auto_loop(_scheduler_skipped_policy(), max_iterations=3)
    assert result.loop_result == LOOP_RESULT_EXHAUSTED


def test_loop_exhausted_skip_has_no_triggers_fired_stop_reason() -> None:
    result = run_auto_loop(_scheduler_skipped_policy(), max_iterations=3)
    assert result.loop_stop_reason == LOOP_STOP_NO_TRIGGERS_FIRED


def test_loop_exhausted_skip_runs_all_iterations() -> None:
    result = run_auto_loop(_scheduler_skipped_policy(), max_iterations=4)
    assert result.iterations_run == 4


def test_loop_returns_exhausted_when_scheduler_blocks_all_iterations() -> None:
    result = run_auto_loop(_scheduler_blocked_policy(), max_iterations=3)
    assert result.loop_result == LOOP_RESULT_EXHAUSTED
    assert result.loop_stop_reason == LOOP_STOP_NO_TRIGGERS_FIRED


def test_loop_exhausted_records_all_iterations() -> None:
    result = run_auto_loop(_scheduler_skipped_policy(), max_iterations=4)
    assert len(result.iteration_records) == 4


def test_loop_exhausted_notes_include_exhaustion_info() -> None:
    result = run_auto_loop(_scheduler_skipped_policy(), max_iterations=2)
    assert any("exhausted" in note for note in result.loop_notes)


# --- stopped_hold path ---

def test_loop_returns_stopped_hold_when_trigger_returns_stopped_hold() -> None:
    result = run_auto_loop(_stopped_hold_policy(), max_iterations=5)
    assert result.loop_result == LOOP_RESULT_STOPPED_HOLD


def test_loop_stopped_hold_has_correct_stop_reason() -> None:
    result = run_auto_loop(_stopped_hold_policy(), max_iterations=5)
    assert result.loop_stop_reason == LOOP_STOP_TRIGGER_RETURNED_STOPPED_HOLD


def test_loop_stopped_hold_halts_after_first_triggered_iteration() -> None:
    result = run_auto_loop(_stopped_hold_policy(), max_iterations=5)
    assert result.iterations_run == 1


def test_loop_stopped_hold_records_only_one_iteration() -> None:
    result = run_auto_loop(_stopped_hold_policy(), max_iterations=5)
    assert len(result.iteration_records) == 1


def test_loop_stopped_hold_notes_include_stop_info() -> None:
    result = run_auto_loop(_stopped_hold_policy(), max_iterations=5)
    assert any("stopped_hold" in note for note in result.loop_notes)


# --- stopped_blocked path ---

def test_loop_returns_stopped_blocked_when_trigger_returns_stopped_blocked() -> None:
    result = run_auto_loop(_stopped_blocked_policy(), max_iterations=5)
    assert result.loop_result == LOOP_RESULT_STOPPED_BLOCKED


def test_loop_stopped_blocked_has_correct_stop_reason() -> None:
    result = run_auto_loop(_stopped_blocked_policy(), max_iterations=5)
    assert result.loop_stop_reason == LOOP_STOP_TRIGGER_RETURNED_STOPPED_BLOCKED


def test_loop_stopped_blocked_halts_after_first_triggered_iteration() -> None:
    result = run_auto_loop(_stopped_blocked_policy(), max_iterations=5)
    assert result.iterations_run == 1


def test_loop_stopped_blocked_records_only_one_iteration() -> None:
    result = run_auto_loop(_stopped_blocked_policy(), max_iterations=5)
    assert len(result.iteration_records) == 1


def test_loop_stopped_blocked_notes_include_stop_info() -> None:
    result = run_auto_loop(_stopped_blocked_policy(), max_iterations=5)
    assert any("stopped_blocked" in note for note in result.loop_notes)


# --- invalid contract: max_iterations <= 0 ---

def test_loop_returns_exhausted_for_max_iterations_zero() -> None:
    result = run_auto_loop(_completed_policy(), max_iterations=0)
    assert result.loop_result == LOOP_RESULT_EXHAUSTED
    assert result.loop_stop_reason == LOOP_STOP_INVALID_CONTRACT


def test_loop_invalid_contract_zero_has_zero_iterations_run() -> None:
    result = run_auto_loop(_completed_policy(), max_iterations=0)
    assert result.iterations_run == 0


def test_loop_invalid_contract_zero_has_empty_records() -> None:
    result = run_auto_loop(_completed_policy(), max_iterations=0)
    assert result.iteration_records == []


def test_loop_returns_exhausted_for_max_iterations_negative() -> None:
    result = run_auto_loop(_completed_policy(), max_iterations=-1)
    assert result.loop_result == LOOP_RESULT_EXHAUSTED
    assert result.loop_stop_reason == LOOP_STOP_INVALID_CONTRACT
    assert result.iterations_run == 0


def test_loop_invalid_contract_notes_include_reason() -> None:
    result = run_auto_loop(_completed_policy(), max_iterations=0)
    assert any("invalid_contract" in note for note in result.loop_notes)


# --- iteration records integrity ---

def test_loop_iteration_records_indices_are_sequential() -> None:
    result = run_auto_loop(_completed_policy(), max_iterations=4)
    indices = [r.iteration_index for r in result.iteration_records]
    assert indices == list(range(4))


def test_loop_iteration_records_include_scheduler_results() -> None:
    result = run_auto_loop(_completed_policy(), max_iterations=2)
    for record in result.iteration_records:
        assert record.scheduler_result is not None


def test_loop_iteration_notes_include_iteration_index() -> None:
    result = run_auto_loop(_completed_policy(), max_iterations=2)
    for record in result.iteration_records:
        assert f"iteration={record.iteration_index}" in record.iteration_note


# --- stop_reason contract ---

def test_loop_stop_reason_is_none_for_completed() -> None:
    result = run_auto_loop(_completed_policy(), max_iterations=1)
    assert result.loop_result == LOOP_RESULT_COMPLETED
    assert result.loop_stop_reason is None


def test_loop_stop_reason_set_for_exhausted_no_triggers() -> None:
    result = run_auto_loop(_scheduler_skipped_policy(), max_iterations=1)
    assert result.loop_stop_reason == LOOP_STOP_NO_TRIGGERS_FIRED


def test_loop_stop_reason_set_for_stopped_hold() -> None:
    result = run_auto_loop(_stopped_hold_policy(), max_iterations=1)
    assert result.loop_stop_reason == LOOP_STOP_TRIGGER_RETURNED_STOPPED_HOLD


def test_loop_stop_reason_set_for_stopped_blocked() -> None:
    result = run_auto_loop(_stopped_blocked_policy(), max_iterations=1)
    assert result.loop_stop_reason == LOOP_STOP_TRIGGER_RETURNED_STOPPED_BLOCKED


# --- single-iteration boundary ---

def test_loop_single_iteration_completed() -> None:
    result = run_auto_loop(_completed_policy(), max_iterations=1)
    assert result.loop_result == LOOP_RESULT_COMPLETED
    assert result.iterations_run == 1
    assert len(result.iteration_records) == 1


def test_loop_single_iteration_exhausted() -> None:
    result = run_auto_loop(_scheduler_skipped_policy(), max_iterations=1)
    assert result.loop_result == LOOP_RESULT_EXHAUSTED
    assert result.iterations_run == 1
    assert len(result.iteration_records) == 1
