"""Phase 7.3 runtime auto-run loop foundation over the 7.2 lightweight scheduler.

Bounded deterministic loop executing repeated synchronous scheduler cycles.
No distributed schedulers, no async worker mesh, no cron daemon.
Loop result categories: completed / stopped_hold / stopped_blocked / exhausted.
"""
from __future__ import annotations

from dataclasses import dataclass

from projects.polymarket.polyquantbot.core.lightweight_activation_scheduler import (
    SCHEDULER_RESULT_TRIGGERED,
    SchedulerInvocationPolicy,
    SchedulerInvocationResult,
    decide_and_invoke_scheduler,
)

# Trigger result values from the 7.1 surface that drive early loop termination
_TRIGGER_VAL_STOPPED_HOLD = "stopped_hold"
_TRIGGER_VAL_STOPPED_BLOCKED = "stopped_blocked"

# Loop result categories
LOOP_RESULT_COMPLETED = "completed"
LOOP_RESULT_STOPPED_HOLD = "stopped_hold"
LOOP_RESULT_STOPPED_BLOCKED = "stopped_blocked"
LOOP_RESULT_EXHAUSTED = "exhausted"

# Loop stop reasons
LOOP_STOP_NO_TRIGGERS_FIRED = "no_triggers_fired"
LOOP_STOP_TRIGGER_RETURNED_STOPPED_HOLD = "trigger_returned_stopped_hold"
LOOP_STOP_TRIGGER_RETURNED_STOPPED_BLOCKED = "trigger_returned_stopped_blocked"
LOOP_STOP_INVALID_CONTRACT = "invalid_contract"


@dataclass(frozen=True)
class LoopIterationRecord:
    """Record of one scheduler invocation cycle within the auto-run loop."""

    iteration_index: int
    scheduler_result: SchedulerInvocationResult
    iteration_note: str


@dataclass(frozen=True)
class RuntimeAutoRunLoopResult:
    """Result of a bounded runtime auto-run loop execution."""

    loop_result: str
    loop_stop_reason: str | None
    iterations_run: int
    iteration_records: list[LoopIterationRecord]
    loop_notes: list[str]


class RuntimeAutoRunLoopBoundary:
    """Phase 7.3 deterministic bounded loop over the 7.2 scheduler boundary.

    Executes repeated synchronous scheduler cycles up to max_iterations.
    Stops deterministically on stopped_hold or stopped_blocked trigger results.
    No distributed workers, no async queue mesh, no cron daemon rollout.
    """

    def run_loop(
        self,
        scheduler_policy: SchedulerInvocationPolicy,
        max_iterations: int,
    ) -> RuntimeAutoRunLoopResult:
        """Run up to max_iterations scheduler cycles; return a deterministic loop result.

        Stop conditions (evaluated per iteration, in priority order):
        1. Triggered cycle returns stopped_blocked -> loop_result=stopped_blocked (immediate halt)
        2. Triggered cycle returns stopped_hold    -> loop_result=stopped_hold    (immediate halt)

        Terminal conditions (after all iterations complete):
        3. No triggers fired                       -> loop_result=exhausted
        4. All triggers completed                  -> loop_result=completed

        Contract:
        - max_iterations <= 0 -> loop_result=exhausted, loop_stop_reason=invalid_contract,
          iterations_run=0, no exception raised
        """
        notes: list[str] = []
        records: list[LoopIterationRecord] = []

        if max_iterations <= 0:
            notes.append(
                f"invalid_contract: max_iterations={max_iterations} must be > 0"
            )
            return RuntimeAutoRunLoopResult(
                loop_result=LOOP_RESULT_EXHAUSTED,
                loop_stop_reason=LOOP_STOP_INVALID_CONTRACT,
                iterations_run=0,
                iteration_records=[],
                loop_notes=notes,
            )

        triggers_fired = 0

        for i in range(max_iterations):
            scheduler_result = decide_and_invoke_scheduler(scheduler_policy)

            trigger_val: str | None = None
            if scheduler_result.scheduler_result == SCHEDULER_RESULT_TRIGGERED:
                triggers_fired += 1
                trigger_val = scheduler_result.trigger_result.trigger_result  # type: ignore[union-attr]
                note = f"iteration={i}: triggered, trigger_result={trigger_val}"
            else:
                note = (
                    f"iteration={i}: {scheduler_result.scheduler_result}"
                    f", skip_reason={scheduler_result.skip_reason}"
                    f", block_reason={scheduler_result.block_reason}"
                )

            records.append(
                LoopIterationRecord(
                    iteration_index=i,
                    scheduler_result=scheduler_result,
                    iteration_note=note,
                )
            )

            if trigger_val == _TRIGGER_VAL_STOPPED_BLOCKED:
                notes.append(
                    f"loop stopping at iteration={i}: trigger returned stopped_blocked"
                )
                return RuntimeAutoRunLoopResult(
                    loop_result=LOOP_RESULT_STOPPED_BLOCKED,
                    loop_stop_reason=LOOP_STOP_TRIGGER_RETURNED_STOPPED_BLOCKED,
                    iterations_run=i + 1,
                    iteration_records=records,
                    loop_notes=notes,
                )

            if trigger_val == _TRIGGER_VAL_STOPPED_HOLD:
                notes.append(
                    f"loop stopping at iteration={i}: trigger returned stopped_hold"
                )
                return RuntimeAutoRunLoopResult(
                    loop_result=LOOP_RESULT_STOPPED_HOLD,
                    loop_stop_reason=LOOP_STOP_TRIGGER_RETURNED_STOPPED_HOLD,
                    iterations_run=i + 1,
                    iteration_records=records,
                    loop_notes=notes,
                )

        if triggers_fired == 0:
            notes.append(
                f"loop exhausted after {max_iterations} iteration(s): no triggers fired"
            )
            return RuntimeAutoRunLoopResult(
                loop_result=LOOP_RESULT_EXHAUSTED,
                loop_stop_reason=LOOP_STOP_NO_TRIGGERS_FIRED,
                iterations_run=max_iterations,
                iteration_records=records,
                loop_notes=notes,
            )

        notes.append(
            f"loop completed after {max_iterations} iteration(s):"
            f" {triggers_fired} trigger(s) fired"
        )
        return RuntimeAutoRunLoopResult(
            loop_result=LOOP_RESULT_COMPLETED,
            loop_stop_reason=None,
            iterations_run=max_iterations,
            iteration_records=records,
            loop_notes=notes,
        )


def run_auto_loop(
    scheduler_policy: SchedulerInvocationPolicy,
    max_iterations: int,
) -> RuntimeAutoRunLoopResult:
    """Deterministic bounded runtime auto-run loop entrypoint over the 7.2 scheduler boundary."""
    return RuntimeAutoRunLoopBoundary().run_loop(scheduler_policy, max_iterations)
