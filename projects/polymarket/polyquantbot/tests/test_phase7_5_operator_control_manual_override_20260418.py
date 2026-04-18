"""Phase 7.5 -- Targeted tests for the operator control / manual override layer.

Covers:
  - OperatorSchedulerGate: all 4 decision paths + override precedence
  - OperatorLoopGate: all 4 decision paths + field propagation
  - OperatorControlledLoopBoundary: loop scenarios with scheduler and loop overrides
  - Determinism: equal inputs produce equal outputs
  - Note / field propagation: override_ref and tokens present in output
"""
from __future__ import annotations

from projects.polymarket.polyquantbot.core.lightweight_activation_scheduler import (
    SCHEDULER_RESULT_BLOCKED,
    SCHEDULER_RESULT_SKIPPED,
    SCHEDULER_RESULT_TRIGGERED,
    SchedulerInvocationPolicy,
)
from projects.polymarket.polyquantbot.core.operator_control import (
    OPERATOR_BLOCK_FORCE_BLOCK,
    OPERATOR_LOOP_STOP_FORCE_BLOCK,
    OPERATOR_LOOP_STOP_HOLD,
    OPERATOR_SKIP_HOLD,
    OperatorControlDecision,
    OperatorControlOverride,
    OperatorControlledLoopBoundary,
    OperatorLoopGate,
    OperatorSchedulerGate,
    apply_operator_loop_gate,
    apply_operator_scheduler_gate,
    run_operator_controlled_loop,
)
from projects.polymarket.polyquantbot.core.runtime_auto_run_loop import (
    LOOP_RESULT_COMPLETED,
    LOOP_RESULT_EXHAUSTED,
    LOOP_RESULT_STOPPED_BLOCKED,
    LOOP_RESULT_STOPPED_HOLD,
    LOOP_STOP_INVALID_CONTRACT,
    LOOP_STOP_NO_TRIGGERS_FIRED,
)
from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
    PublicActivationCyclePolicy,
    WALLET_CORRECTION_RESULT_ACCEPTED,
    WALLET_CORRECTION_RESULT_BLOCKED,
    WALLET_RECONCILIATION_OUTCOME_MATCH,
    WALLET_RECONCILIATION_OUTCOME_REVISION_MISMATCH,
    WALLET_RETRY_WORK_DECISION_SKIPPED,
)


# ─────────────────────────────────────────────────────────────────────────────
# Shared fixtures
# ─────────────────────────────────────────────────────────────────────────────


def _trigger_policy(**kwargs) -> PublicActivationCyclePolicy:  # type: ignore[no-untyped-def]
    defaults: dict = {
        "wallet_binding_id": "wallet-op-1",
        "owner_user_id": "user-op-1",
        "requester_user_id": "user-op-1",
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


def _override(
    decision: OperatorControlDecision,
    ref: str = "op-ref-1",
    note: str = "test override",
) -> OperatorControlOverride:
    return OperatorControlOverride(
        decision=decision,
        override_ref=ref,
        override_note=note,
    )


def _allow() -> OperatorControlOverride:
    return _override(OperatorControlDecision.ALLOW)


def _hold() -> OperatorControlOverride:
    return _override(OperatorControlDecision.HOLD)


def _force_block() -> OperatorControlOverride:
    return _override(OperatorControlDecision.FORCE_BLOCK)


def _force_run() -> OperatorControlOverride:
    return _override(OperatorControlDecision.FORCE_RUN)


# Stopped-hold trigger policy: correction blocked -> cycle returns stopped_hold
def _stopped_hold_policy() -> SchedulerInvocationPolicy:
    return _scheduler_policy(
        trigger_policy=_trigger_policy(
            correction_result_category=WALLET_CORRECTION_RESULT_BLOCKED,
        )
    )


# Stopped-blocked trigger policy: reconciliation mismatch -> cycle returns stopped_blocked
def _stopped_blocked_policy() -> SchedulerInvocationPolicy:
    return _scheduler_policy(
        trigger_policy=_trigger_policy(
            reconciliation_outcome=WALLET_RECONCILIATION_OUTCOME_REVISION_MISMATCH,
        )
    )


# ═════════════════════════════════════════════════════════════════════════════
# OperatorSchedulerGate -- all decision paths
# ═════════════════════════════════════════════════════════════════════════════


def test_scheduler_gate_allow_passes_through_to_scheduler_triggered() -> None:
    result = OperatorSchedulerGate().apply(_allow(), _scheduler_policy())
    assert result.scheduler_result == SCHEDULER_RESULT_TRIGGERED
    assert result.trigger_result is not None
    assert result.trigger_result.trigger_result == "completed"
    assert result.skip_reason is None
    assert result.block_reason is None


def test_scheduler_gate_allow_passes_through_blocked_when_schedule_disabled() -> None:
    result = OperatorSchedulerGate().apply(
        _allow(), _scheduler_policy(schedule_enabled=False)
    )
    assert result.scheduler_result == SCHEDULER_RESULT_BLOCKED
    assert result.block_reason == "schedule_disabled"


def test_scheduler_gate_allow_passes_through_skipped_when_already_running() -> None:
    result = OperatorSchedulerGate().apply(
        _allow(), _scheduler_policy(concurrent_invocation_active=True)
    )
    assert result.scheduler_result == SCHEDULER_RESULT_SKIPPED
    assert result.skip_reason == "already_running"


def test_scheduler_gate_hold_returns_skipped_operator_hold() -> None:
    result = OperatorSchedulerGate().apply(_hold(), _scheduler_policy())
    assert result.scheduler_result == SCHEDULER_RESULT_SKIPPED
    assert result.skip_reason == OPERATOR_SKIP_HOLD
    assert result.block_reason is None
    assert result.trigger_result is None


def test_scheduler_gate_hold_overrides_fully_open_scheduler_conditions() -> None:
    """hold wins even when all scheduler conditions would allow triggering."""
    result = OperatorSchedulerGate().apply(_hold(), _scheduler_policy())
    assert result.scheduler_result == SCHEDULER_RESULT_SKIPPED
    assert result.skip_reason == OPERATOR_SKIP_HOLD


def test_scheduler_gate_hold_note_contains_override_ref() -> None:
    override = _override(OperatorControlDecision.HOLD, ref="hold-ref-99")
    result = OperatorSchedulerGate().apply(override, _scheduler_policy())
    assert any("hold-ref-99" in n for n in result.scheduler_notes)


def test_scheduler_gate_force_block_returns_blocked_operator_force_block() -> None:
    result = OperatorSchedulerGate().apply(_force_block(), _scheduler_policy())
    assert result.scheduler_result == SCHEDULER_RESULT_BLOCKED
    assert result.block_reason == OPERATOR_BLOCK_FORCE_BLOCK
    assert result.skip_reason is None
    assert result.trigger_result is None


def test_scheduler_gate_force_block_overrides_fully_open_conditions() -> None:
    """force_block wins even when scheduler would trigger."""
    result = OperatorSchedulerGate().apply(_force_block(), _scheduler_policy())
    assert result.scheduler_result == SCHEDULER_RESULT_BLOCKED
    assert result.block_reason == OPERATOR_BLOCK_FORCE_BLOCK


def test_scheduler_gate_force_block_note_contains_override_ref() -> None:
    override = _override(OperatorControlDecision.FORCE_BLOCK, ref="fb-ref-42")
    result = OperatorSchedulerGate().apply(override, _scheduler_policy())
    assert any("fb-ref-42" in n for n in result.scheduler_notes)


def test_scheduler_gate_force_run_bypasses_schedule_disabled() -> None:
    """force_run triggers even when schedule_enabled=False."""
    result = OperatorSchedulerGate().apply(
        _force_run(), _scheduler_policy(schedule_enabled=False)
    )
    assert result.scheduler_result == SCHEDULER_RESULT_TRIGGERED
    assert result.trigger_result is not None


def test_scheduler_gate_force_run_bypasses_concurrent_invocation_active() -> None:
    result = OperatorSchedulerGate().apply(
        _force_run(), _scheduler_policy(concurrent_invocation_active=True)
    )
    assert result.scheduler_result == SCHEDULER_RESULT_TRIGGERED
    assert result.trigger_result is not None


def test_scheduler_gate_force_run_bypasses_window_not_open() -> None:
    result = OperatorSchedulerGate().apply(
        _force_run(), _scheduler_policy(invocation_window_open=False)
    )
    assert result.scheduler_result == SCHEDULER_RESULT_TRIGGERED
    assert result.trigger_result is not None


def test_scheduler_gate_force_run_bypasses_quota_reached() -> None:
    result = OperatorSchedulerGate().apply(
        _force_run(), _scheduler_policy(invocation_quota_remaining=0)
    )
    assert result.scheduler_result == SCHEDULER_RESULT_TRIGGERED
    assert result.trigger_result is not None


def test_scheduler_gate_force_run_trigger_result_propagated() -> None:
    result = OperatorSchedulerGate().apply(_force_run(), _scheduler_policy())
    assert result.trigger_result is not None
    assert result.trigger_result.trigger_result == "completed"
    assert any("force_run" in n for n in result.scheduler_notes)


def test_scheduler_gate_force_run_stopped_hold_trigger_result() -> None:
    result = OperatorSchedulerGate().apply(_force_run(), _stopped_hold_policy())
    assert result.scheduler_result == SCHEDULER_RESULT_TRIGGERED
    assert result.trigger_result is not None
    assert result.trigger_result.trigger_result == "stopped_hold"


# ═════════════════════════════════════════════════════════════════════════════
# OperatorSchedulerGate -- module-level entrypoint
# ═════════════════════════════════════════════════════════════════════════════


def test_apply_operator_scheduler_gate_delegates_correctly() -> None:
    result = apply_operator_scheduler_gate(_hold(), _scheduler_policy())
    assert result.scheduler_result == SCHEDULER_RESULT_SKIPPED
    assert result.skip_reason == OPERATOR_SKIP_HOLD


# ═════════════════════════════════════════════════════════════════════════════
# OperatorSchedulerGate -- determinism
# ═════════════════════════════════════════════════════════════════════════════


def test_scheduler_gate_determinism_hold() -> None:
    policy = _scheduler_policy()
    override = _override(OperatorControlDecision.HOLD, ref="det-1")
    r1 = OperatorSchedulerGate().apply(override, policy)
    r2 = OperatorSchedulerGate().apply(override, policy)
    assert r1 == r2


def test_scheduler_gate_determinism_force_block() -> None:
    policy = _scheduler_policy()
    override = _override(OperatorControlDecision.FORCE_BLOCK, ref="det-2")
    r1 = OperatorSchedulerGate().apply(override, policy)
    r2 = OperatorSchedulerGate().apply(override, policy)
    assert r1 == r2


# ═════════════════════════════════════════════════════════════════════════════
# OperatorLoopGate -- all decision paths
# ═════════════════════════════════════════════════════════════════════════════


def test_loop_gate_allow_proceeds_no_suppress() -> None:
    outcome = OperatorLoopGate().apply(_allow(), iteration_index=0)
    assert outcome.should_proceed is True
    assert outcome.suppress_trigger_stop is False
    assert outcome.forced_loop_result is None
    assert outcome.forced_stop_reason is None


def test_loop_gate_allow_at_any_iteration_index() -> None:
    for i in [0, 1, 5, 99]:
        outcome = OperatorLoopGate().apply(_allow(), iteration_index=i)
        assert outcome.should_proceed is True
        assert outcome.suppress_trigger_stop is False


def test_loop_gate_hold_does_not_proceed() -> None:
    outcome = OperatorLoopGate().apply(_hold(), iteration_index=0)
    assert outcome.should_proceed is False
    assert outcome.suppress_trigger_stop is False


def test_loop_gate_hold_forced_result_is_stopped_hold() -> None:
    outcome = OperatorLoopGate().apply(_hold(), iteration_index=3)
    assert outcome.forced_loop_result == LOOP_RESULT_STOPPED_HOLD
    assert outcome.forced_stop_reason == OPERATOR_LOOP_STOP_HOLD


def test_loop_gate_force_block_does_not_proceed() -> None:
    outcome = OperatorLoopGate().apply(_force_block(), iteration_index=0)
    assert outcome.should_proceed is False
    assert outcome.suppress_trigger_stop is False


def test_loop_gate_force_block_forced_result_is_stopped_blocked() -> None:
    outcome = OperatorLoopGate().apply(_force_block(), iteration_index=2)
    assert outcome.forced_loop_result == LOOP_RESULT_STOPPED_BLOCKED
    assert outcome.forced_stop_reason == OPERATOR_LOOP_STOP_FORCE_BLOCK


def test_loop_gate_force_run_proceeds_with_suppress() -> None:
    outcome = OperatorLoopGate().apply(_force_run(), iteration_index=0)
    assert outcome.should_proceed is True
    assert outcome.suppress_trigger_stop is True
    assert outcome.forced_loop_result is None
    assert outcome.forced_stop_reason is None


def test_loop_gate_override_ref_propagated() -> None:
    override = _override(OperatorControlDecision.HOLD, ref="loop-ref-77")
    outcome = OperatorLoopGate().apply(override, iteration_index=0)
    assert outcome.override_ref == "loop-ref-77"
    assert outcome.override_note == "test override"


# ═════════════════════════════════════════════════════════════════════════════
# OperatorLoopGate -- module-level entrypoint + determinism
# ═════════════════════════════════════════════════════════════════════════════


def test_apply_operator_loop_gate_delegates_correctly() -> None:
    outcome = apply_operator_loop_gate(_hold(), iteration_index=0)
    assert outcome.should_proceed is False
    assert outcome.forced_loop_result == LOOP_RESULT_STOPPED_HOLD


def test_loop_gate_determinism() -> None:
    override = _override(OperatorControlDecision.FORCE_BLOCK, ref="det-loop")
    o1 = OperatorLoopGate().apply(override, iteration_index=0)
    o2 = OperatorLoopGate().apply(override, iteration_index=0)
    assert o1 == o2


# ═════════════════════════════════════════════════════════════════════════════
# OperatorControlledLoopBoundary -- contract edge cases
# ═════════════════════════════════════════════════════════════════════════════


def test_controlled_loop_invalid_contract_zero_max_iterations() -> None:
    result = OperatorControlledLoopBoundary().run_loop(
        _scheduler_policy(), max_iterations=0,
        scheduler_override=_allow(), loop_override=_allow(),
    )
    assert result.loop_result == LOOP_RESULT_EXHAUSTED
    assert result.loop_stop_reason == LOOP_STOP_INVALID_CONTRACT
    assert result.iterations_run == 0
    assert result.iteration_records == []


def test_controlled_loop_invalid_contract_negative_max_iterations() -> None:
    result = OperatorControlledLoopBoundary().run_loop(
        _scheduler_policy(), max_iterations=-3,
        scheduler_override=_allow(), loop_override=_allow(),
    )
    assert result.loop_result == LOOP_RESULT_EXHAUSTED
    assert result.loop_stop_reason == LOOP_STOP_INVALID_CONTRACT
    assert result.iterations_run == 0


# ═════════════════════════════════════════════════════════════════════════════
# OperatorControlledLoopBoundary -- all-allow (mirrors 7.3 behaviour)
# ═════════════════════════════════════════════════════════════════════════════


def test_controlled_loop_all_allow_completed_result() -> None:
    result = OperatorControlledLoopBoundary().run_loop(
        _scheduler_policy(), max_iterations=2,
        scheduler_override=_allow(), loop_override=_allow(),
    )
    assert result.loop_result == LOOP_RESULT_COMPLETED
    assert result.iterations_run == 2
    assert len(result.iteration_records) == 2


def test_controlled_loop_all_allow_stops_on_stopped_hold_trigger() -> None:
    result = OperatorControlledLoopBoundary().run_loop(
        _stopped_hold_policy(), max_iterations=5,
        scheduler_override=_allow(), loop_override=_allow(),
    )
    assert result.loop_result == LOOP_RESULT_STOPPED_HOLD
    assert result.iterations_run == 1


def test_controlled_loop_all_allow_stops_on_stopped_blocked_trigger() -> None:
    result = OperatorControlledLoopBoundary().run_loop(
        _stopped_blocked_policy(), max_iterations=5,
        scheduler_override=_allow(), loop_override=_allow(),
    )
    assert result.loop_result == LOOP_RESULT_STOPPED_BLOCKED
    assert result.iterations_run == 1


# ═════════════════════════════════════════════════════════════════════════════
# OperatorControlledLoopBoundary -- loop_override hold / force_block
# ═════════════════════════════════════════════════════════════════════════════


def test_controlled_loop_loop_hold_stops_before_first_iteration() -> None:
    result = OperatorControlledLoopBoundary().run_loop(
        _scheduler_policy(), max_iterations=5,
        scheduler_override=_allow(), loop_override=_hold(),
    )
    assert result.loop_result == LOOP_RESULT_STOPPED_HOLD
    assert result.loop_stop_reason == OPERATOR_LOOP_STOP_HOLD
    assert result.iterations_run == 0
    assert result.iteration_records == []


def test_controlled_loop_loop_force_block_stops_before_first_iteration() -> None:
    result = OperatorControlledLoopBoundary().run_loop(
        _scheduler_policy(), max_iterations=5,
        scheduler_override=_allow(), loop_override=_force_block(),
    )
    assert result.loop_result == LOOP_RESULT_STOPPED_BLOCKED
    assert result.loop_stop_reason == OPERATOR_LOOP_STOP_FORCE_BLOCK
    assert result.iterations_run == 0
    assert result.iteration_records == []


def test_controlled_loop_loop_hold_note_contains_override_ref() -> None:
    override = _override(OperatorControlDecision.HOLD, ref="loop-stop-ref")
    result = OperatorControlledLoopBoundary().run_loop(
        _scheduler_policy(), max_iterations=5,
        scheduler_override=_allow(), loop_override=override,
    )
    assert any("loop-stop-ref" in n for n in result.loop_notes)


# ═════════════════════════════════════════════════════════════════════════════
# OperatorControlledLoopBoundary -- scheduler_override hold / force_block
# ═════════════════════════════════════════════════════════════════════════════


def test_controlled_loop_scheduler_hold_exhausts_loop_no_triggers() -> None:
    """Scheduler override=hold -> all iterations skipped -> exhausted."""
    result = OperatorControlledLoopBoundary().run_loop(
        _scheduler_policy(), max_iterations=3,
        scheduler_override=_hold(), loop_override=_allow(),
    )
    assert result.loop_result == LOOP_RESULT_EXHAUSTED
    assert result.loop_stop_reason == LOOP_STOP_NO_TRIGGERS_FIRED
    assert result.iterations_run == 3
    for rec in result.iteration_records:
        assert rec.scheduler_result.scheduler_result == SCHEDULER_RESULT_SKIPPED
        assert rec.scheduler_result.skip_reason == OPERATOR_SKIP_HOLD


def test_controlled_loop_scheduler_force_block_exhausts_loop_no_triggers() -> None:
    """Scheduler override=force_block -> all iterations blocked -> exhausted."""
    result = OperatorControlledLoopBoundary().run_loop(
        _scheduler_policy(), max_iterations=3,
        scheduler_override=_force_block(), loop_override=_allow(),
    )
    assert result.loop_result == LOOP_RESULT_EXHAUSTED
    assert result.iterations_run == 3
    for rec in result.iteration_records:
        assert rec.scheduler_result.scheduler_result == SCHEDULER_RESULT_BLOCKED
        assert rec.scheduler_result.block_reason == OPERATOR_BLOCK_FORCE_BLOCK


# ═════════════════════════════════════════════════════════════════════════════
# OperatorControlledLoopBoundary -- scheduler_override force_run
# ═════════════════════════════════════════════════════════════════════════════


def test_controlled_loop_scheduler_force_run_fires_all_iterations() -> None:
    """force_run scheduler override forces all iterations to trigger."""
    result = OperatorControlledLoopBoundary().run_loop(
        _scheduler_policy(schedule_enabled=False), max_iterations=3,
        scheduler_override=_force_run(), loop_override=_allow(),
    )
    assert result.loop_result == LOOP_RESULT_COMPLETED
    assert result.iterations_run == 3
    for rec in result.iteration_records:
        assert rec.scheduler_result.scheduler_result == SCHEDULER_RESULT_TRIGGERED


def test_controlled_loop_scheduler_force_run_still_stops_on_trigger_stopped_hold() -> None:
    """force_run scheduler: trigger can return stopped_hold -> loop stops (loop=allow)."""
    result = OperatorControlledLoopBoundary().run_loop(
        _stopped_hold_policy(), max_iterations=5,
        scheduler_override=_force_run(), loop_override=_allow(),
    )
    assert result.loop_result == LOOP_RESULT_STOPPED_HOLD
    assert result.iterations_run == 1


# ═════════════════════════════════════════════════════════════════════════════
# OperatorControlledLoopBoundary -- loop_override force_run (suppress trigger stop)
# ═════════════════════════════════════════════════════════════════════════════


def test_controlled_loop_loop_force_run_suppresses_stopped_blocked_trigger() -> None:
    """loop_override=force_run suppresses trigger-based stopped_blocked stop."""
    result = OperatorControlledLoopBoundary().run_loop(
        _stopped_blocked_policy(), max_iterations=3,
        scheduler_override=_allow(), loop_override=_force_run(),
    )
    # trigger returns stopped_blocked every iteration, but loop continues to completion
    assert result.loop_result == LOOP_RESULT_COMPLETED
    assert result.iterations_run == 3


def test_controlled_loop_loop_force_run_suppresses_stopped_hold_trigger() -> None:
    """loop_override=force_run suppresses trigger-based stopped_hold stop."""
    result = OperatorControlledLoopBoundary().run_loop(
        _stopped_hold_policy(), max_iterations=3,
        scheduler_override=_allow(), loop_override=_force_run(),
    )
    assert result.loop_result == LOOP_RESULT_COMPLETED
    assert result.iterations_run == 3


def test_controlled_loop_both_force_run_all_trigger_no_stop() -> None:
    """Both gates=force_run: all iterations trigger, no stops, loop completes."""
    result = OperatorControlledLoopBoundary().run_loop(
        _stopped_blocked_policy(), max_iterations=4,
        scheduler_override=_force_run(), loop_override=_force_run(),
    )
    assert result.loop_result == LOOP_RESULT_COMPLETED
    assert result.iterations_run == 4
    for rec in result.iteration_records:
        assert rec.scheduler_result.scheduler_result == SCHEDULER_RESULT_TRIGGERED


# ═════════════════════════════════════════════════════════════════════════════
# OperatorControlledLoopBoundary -- iteration records structure
# ═════════════════════════════════════════════════════════════════════════════


def test_controlled_loop_iteration_records_have_correct_indices() -> None:
    result = OperatorControlledLoopBoundary().run_loop(
        _scheduler_policy(), max_iterations=3,
        scheduler_override=_allow(), loop_override=_allow(),
    )
    for i, rec in enumerate(result.iteration_records):
        assert rec.iteration_index == i


def test_controlled_loop_scheduler_force_block_records_have_block_reason() -> None:
    result = OperatorControlledLoopBoundary().run_loop(
        _scheduler_policy(), max_iterations=2,
        scheduler_override=_force_block(), loop_override=_allow(),
    )
    for rec in result.iteration_records:
        assert rec.scheduler_result.block_reason == OPERATOR_BLOCK_FORCE_BLOCK


# ═════════════════════════════════════════════════════════════════════════════
# Module-level entrypoint -- run_operator_controlled_loop
# ═════════════════════════════════════════════════════════════════════════════


def test_run_operator_controlled_loop_entrypoint_delegates() -> None:
    result = run_operator_controlled_loop(
        _scheduler_policy(), max_iterations=1,
        scheduler_override=_allow(), loop_override=_allow(),
    )
    assert result.loop_result == LOOP_RESULT_COMPLETED
    assert result.iterations_run == 1


def test_run_operator_controlled_loop_entrypoint_hold_stops_loop() -> None:
    result = run_operator_controlled_loop(
        _scheduler_policy(), max_iterations=5,
        scheduler_override=_allow(), loop_override=_hold(),
    )
    assert result.loop_result == LOOP_RESULT_STOPPED_HOLD
    assert result.iterations_run == 0


# ═════════════════════════════════════════════════════════════════════════════
# Determinism -- controlled loop
# ═════════════════════════════════════════════════════════════════════════════


def test_controlled_loop_determinism_allow_allow() -> None:
    policy = _scheduler_policy()
    r1 = OperatorControlledLoopBoundary().run_loop(
        policy, max_iterations=2, scheduler_override=_allow(), loop_override=_allow()
    )
    r2 = OperatorControlledLoopBoundary().run_loop(
        policy, max_iterations=2, scheduler_override=_allow(), loop_override=_allow()
    )
    assert r1.loop_result == r2.loop_result
    assert r1.iterations_run == r2.iterations_run


def test_controlled_loop_determinism_hold_force_block() -> None:
    policy = _scheduler_policy()
    r1 = OperatorControlledLoopBoundary().run_loop(
        policy, max_iterations=3, scheduler_override=_hold(), loop_override=_force_block()
    )
    r2 = OperatorControlledLoopBoundary().run_loop(
        policy, max_iterations=3, scheduler_override=_hold(), loop_override=_force_block()
    )
    assert r1 == r2
