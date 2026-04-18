from __future__ import annotations

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
    decide_and_invoke_scheduler,
)
from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
    PublicActivationCyclePolicy,
    WALLET_CORRECTION_RESULT_ACCEPTED,
    WALLET_RECONCILIATION_OUTCOME_MATCH,
    WALLET_RETRY_WORK_DECISION_SKIPPED,
)


def _trigger_policy(**kwargs) -> PublicActivationCyclePolicy:  # type: ignore[no-untyped-def]
    defaults: dict = {
        "wallet_binding_id": "wallet-1",
        "owner_user_id": "user-1",
        "requester_user_id": "user-1",
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
        "invocation_quota_remaining": 5,
        "concurrent_invocation_active": False,
    }
    defaults.update(kwargs)
    return SchedulerInvocationPolicy(**defaults)


def test_scheduler_returns_triggered_when_all_conditions_met() -> None:
    result = decide_and_invoke_scheduler(_scheduler_policy())
    assert result.scheduler_result == SCHEDULER_RESULT_TRIGGERED
    assert result.skip_reason is None
    assert result.block_reason is None
    assert result.trigger_result is not None
    assert result.trigger_result.trigger_result == "completed"


def test_scheduler_triggered_result_includes_notes() -> None:
    result = decide_and_invoke_scheduler(_scheduler_policy())
    assert any("triggering" in note for note in result.scheduler_notes)
    assert any("trigger_result" in note for note in result.scheduler_notes)


def test_scheduler_returns_blocked_when_schedule_disabled() -> None:
    result = decide_and_invoke_scheduler(_scheduler_policy(schedule_enabled=False))
    assert result.scheduler_result == SCHEDULER_RESULT_BLOCKED
    assert result.block_reason == SCHEDULER_BLOCK_SCHEDULE_DISABLED
    assert result.skip_reason is None
    assert result.trigger_result is None


def test_scheduler_blocked_has_schedule_disabled_note() -> None:
    result = decide_and_invoke_scheduler(_scheduler_policy(schedule_enabled=False))
    assert any("schedule_disabled" in note for note in result.scheduler_notes)


def test_scheduler_returns_skipped_when_concurrent_invocation_active() -> None:
    result = decide_and_invoke_scheduler(_scheduler_policy(concurrent_invocation_active=True))
    assert result.scheduler_result == SCHEDULER_RESULT_SKIPPED
    assert result.skip_reason == SCHEDULER_SKIP_ALREADY_RUNNING
    assert result.block_reason is None
    assert result.trigger_result is None


def test_scheduler_returns_skipped_when_window_not_open() -> None:
    result = decide_and_invoke_scheduler(_scheduler_policy(invocation_window_open=False))
    assert result.scheduler_result == SCHEDULER_RESULT_SKIPPED
    assert result.skip_reason == SCHEDULER_SKIP_WINDOW_NOT_OPEN
    assert result.block_reason is None
    assert result.trigger_result is None


def test_scheduler_returns_skipped_when_quota_exhausted() -> None:
    result = decide_and_invoke_scheduler(_scheduler_policy(invocation_quota_remaining=0))
    assert result.scheduler_result == SCHEDULER_RESULT_SKIPPED
    assert result.skip_reason == SCHEDULER_SKIP_QUOTA_REACHED
    assert result.block_reason is None
    assert result.trigger_result is None


def test_scheduler_blocked_takes_priority_over_concurrent_invocation() -> None:
    result = decide_and_invoke_scheduler(
        _scheduler_policy(schedule_enabled=False, concurrent_invocation_active=True)
    )
    assert result.scheduler_result == SCHEDULER_RESULT_BLOCKED
    assert result.block_reason == SCHEDULER_BLOCK_SCHEDULE_DISABLED


def test_scheduler_concurrent_skips_before_window_check() -> None:
    result = decide_and_invoke_scheduler(
        _scheduler_policy(concurrent_invocation_active=True, invocation_window_open=False)
    )
    assert result.scheduler_result == SCHEDULER_RESULT_SKIPPED
    assert result.skip_reason == SCHEDULER_SKIP_ALREADY_RUNNING


def test_scheduler_window_skips_before_quota_check() -> None:
    result = decide_and_invoke_scheduler(
        _scheduler_policy(invocation_window_open=False, invocation_quota_remaining=0)
    )
    assert result.scheduler_result == SCHEDULER_RESULT_SKIPPED
    assert result.skip_reason == SCHEDULER_SKIP_WINDOW_NOT_OPEN


def test_scheduler_returns_blocked_invalid_contract_for_negative_quota() -> None:
    result = decide_and_invoke_scheduler(_scheduler_policy(invocation_quota_remaining=-1))
    assert result.scheduler_result == SCHEDULER_RESULT_BLOCKED
    assert result.block_reason == SCHEDULER_BLOCK_INVALID_CONTRACT
    assert result.skip_reason is None
    assert result.trigger_result is None


def test_scheduler_invalid_contract_blocked_note_present() -> None:
    result = decide_and_invoke_scheduler(_scheduler_policy(invocation_quota_remaining=-1))
    assert any("invalid_contract" in note for note in result.scheduler_notes)


def test_scheduler_invalid_contract_priority_below_quota_reached() -> None:
    # quota == 0 must yield skipped(quota_reached), not blocked(invalid_contract)
    result = decide_and_invoke_scheduler(_scheduler_policy(invocation_quota_remaining=0))
    assert result.scheduler_result == SCHEDULER_RESULT_SKIPPED
    assert result.skip_reason == SCHEDULER_SKIP_QUOTA_REACHED


def test_scheduler_quota_of_one_is_accepted() -> None:
    result = decide_and_invoke_scheduler(_scheduler_policy(invocation_quota_remaining=1))
    assert result.scheduler_result == SCHEDULER_RESULT_TRIGGERED
