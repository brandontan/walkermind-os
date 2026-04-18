"""Phase 7.5 -- Operator Control / Manual Override.

Narrow deterministic operator control layer over:
  - Phase 7.2 lightweight automation scheduler (OperatorSchedulerGate)
  - Phase 7.3 runtime auto-run loop continuation (OperatorLoopGate)

Override decisions:
  allow       -- pass through to normal automation; no override applied
  hold        -- soft pause; scheduler treated as skipped / loop halted with stopped_hold
  force_block -- hard block; scheduler treated as blocked / loop halted with stopped_blocked
  force_run   -- bypass scheduler conditions; trigger invoked directly /
                 loop iteration proceeds with trigger-stop suppressed

Injection points:
  1. BEFORE 7.2 scheduler decision  -> OperatorSchedulerGate.apply(override, policy)
  2. BEFORE 7.3 loop continuation    -> OperatorLoopGate.apply(override, iteration_index)

Override always wins deterministically.  When decision != allow, the normal
automation result is NEVER consulted -- the override result is returned immediately.

Compatibility:
  - Results are standard SchedulerInvocationResult / RuntimeAutoRunLoopResult types.
  - Phase 6.4.1 monitoring and Phase 7.4 observability contracts are preserved unchanged.

Pure functions -- no state, no IO, no persistence, no async.
No UI, no API expansion, no distributed control.

Claim Level : NARROW INTEGRATION
Not in scope: alert delivery, UI controls, API surface expansion, distributed
              control plane, state storage, async workers, cron daemon rollout.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from projects.polymarket.polyquantbot.api.public_activation_trigger_cli import (
    invoke_public_activation_cycle_trigger,
)
from projects.polymarket.polyquantbot.core.lightweight_activation_scheduler import (
    SCHEDULER_RESULT_BLOCKED,
    SCHEDULER_RESULT_SKIPPED,
    SCHEDULER_RESULT_TRIGGERED,
    LightweightActivationSchedulerBoundary,
    SchedulerInvocationPolicy,
    SchedulerInvocationResult,
)
from projects.polymarket.polyquantbot.core.runtime_auto_run_loop import (
    LOOP_RESULT_COMPLETED,
    LOOP_RESULT_EXHAUSTED,
    LOOP_RESULT_STOPPED_BLOCKED,
    LOOP_RESULT_STOPPED_HOLD,
    LOOP_STOP_INVALID_CONTRACT,
    LOOP_STOP_NO_TRIGGERS_FIRED,
    LoopIterationRecord,
    RuntimeAutoRunLoopResult,
)

# Trigger result sentinel values (from 7.3 private surface -- redeclared here
# to avoid importing private names; kept in sync with 7.3 behaviour).
_TRIGGER_VAL_STOPPED_HOLD = "stopped_hold"
_TRIGGER_VAL_STOPPED_BLOCKED = "stopped_blocked"

# ─────────────────────────────────────────────────────────────────────────────
# Operator skip / block reason constants
# ─────────────────────────────────────────────────────────────────────────────

OPERATOR_SKIP_HOLD = "operator_hold"
OPERATOR_BLOCK_FORCE_BLOCK = "operator_force_block"
OPERATOR_LOOP_STOP_HOLD = "operator_loop_hold"
OPERATOR_LOOP_STOP_FORCE_BLOCK = "operator_loop_force_block"


# ─────────────────────────────────────────────────────────────────────────────
# Override types
# ─────────────────────────────────────────────────────────────────────────────


class OperatorControlDecision(str, Enum):
    """Deterministic operator control decision categories.

    allow       -- automation proceeds normally; no override applied.
    hold        -- soft pause; scheduler skipped / loop stops with stopped_hold.
    force_block -- hard block; scheduler blocked / loop stops with stopped_blocked.
    force_run   -- force invocation; bypass scheduler conditions / suppress loop
                   trigger-based early termination for this iteration.
    """

    ALLOW = "allow"
    HOLD = "hold"
    FORCE_BLOCK = "force_block"
    FORCE_RUN = "force_run"


@dataclass(frozen=True)
class OperatorControlOverride:
    """Operator control override for one invocation cycle or loop iteration.

    decision     : the operator decision (allow / hold / force_block / force_run)
    override_ref : traceability reference for this override (non-empty string)
    override_note: operator-provided justification for audit trail
    """

    decision: OperatorControlDecision
    override_ref: str
    override_note: str


# ─────────────────────────────────────────────────────────────────────────────
# Loop continuation outcome type
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OperatorLoopContinuationOutcome:
    """Outcome of the operator loop gate check before one loop iteration.

    should_proceed       -- True: continue with this iteration.  False: stop loop now.
    suppress_trigger_stop-- True: trigger-result-based early termination suppressed
                           for this iteration (only set when decision == force_run).
    forced_loop_result   -- loop_result string if should_proceed is False, else None.
    forced_stop_reason   -- loop_stop_reason string if should_proceed is False, else None.
    override_ref         -- propagated from the OperatorControlOverride.
    override_note        -- propagated from the OperatorControlOverride.
    """

    should_proceed: bool
    suppress_trigger_stop: bool
    forced_loop_result: Optional[str]
    forced_stop_reason: Optional[str]
    override_ref: str
    override_note: str


# ─────────────────────────────────────────────────────────────────────────────
# Injection Point 1 — before 7.2 scheduler decision
# ─────────────────────────────────────────────────────────────────────────────


class OperatorSchedulerGate:
    """Deterministic operator override gate injected BEFORE the 7.2 scheduler decision.

    Pure class -- no state, no side effects.
    Equal inputs always produce equal outputs.

    Decision rules (evaluated in order; override always wins when != allow):
      allow       -> delegate to LightweightActivationSchedulerBoundary.decide_and_invoke
      hold        -> return skipped(skip_reason=operator_hold)         immediately
      force_block -> return blocked(block_reason=operator_force_block) immediately
      force_run   -> invoke trigger directly (bypass all scheduler conditions)
    """

    def apply(
        self,
        override: OperatorControlOverride,
        policy: SchedulerInvocationPolicy,
    ) -> SchedulerInvocationResult:
        """Apply operator override before the scheduler decision.

        Args:
            override: The operator control override for this invocation.
            policy:   The scheduler invocation policy (consumed only when allow or force_run).

        Returns:
            SchedulerInvocationResult -- standard result compatible with 7.3/7.4.
        """
        decision = override.decision

        if decision == OperatorControlDecision.ALLOW:
            return LightweightActivationSchedulerBoundary().decide_and_invoke(policy)

        if decision == OperatorControlDecision.HOLD:
            return SchedulerInvocationResult(
                scheduler_result=SCHEDULER_RESULT_SKIPPED,
                skip_reason=OPERATOR_SKIP_HOLD,
                block_reason=None,
                trigger_result=None,
                scheduler_notes=[
                    f"operator_hold: override_ref={override.override_ref}",
                    f"override_note={override.override_note}",
                ],
            )

        if decision == OperatorControlDecision.FORCE_BLOCK:
            return SchedulerInvocationResult(
                scheduler_result=SCHEDULER_RESULT_BLOCKED,
                skip_reason=None,
                block_reason=OPERATOR_BLOCK_FORCE_BLOCK,
                trigger_result=None,
                scheduler_notes=[
                    f"operator_force_block: override_ref={override.override_ref}",
                    f"override_note={override.override_note}",
                ],
            )

        # force_run: bypass all scheduler conditions, invoke trigger directly
        trigger_result = invoke_public_activation_cycle_trigger(policy.trigger_policy)
        return SchedulerInvocationResult(
            scheduler_result=SCHEDULER_RESULT_TRIGGERED,
            skip_reason=None,
            block_reason=None,
            trigger_result=trigger_result,
            scheduler_notes=[
                f"operator_force_run: override_ref={override.override_ref}",
                f"override_note={override.override_note}",
                f"trigger_result={trigger_result.trigger_result}",
            ],
        )


# ─────────────────────────────────────────────────────────────────────────────
# Injection Point 2 — before 7.3 loop continuation
# ─────────────────────────────────────────────────────────────────────────────


class OperatorLoopGate:
    """Deterministic operator override gate injected BEFORE each 7.3 loop iteration.

    Pure class -- no state, no side effects.
    Equal inputs always produce equal outputs.

    Decision rules:
      allow       -> proceed=True,  suppress_trigger_stop=False
      hold        -> proceed=False, forced_loop_result=stopped_hold,
                     forced_stop_reason=operator_loop_hold
      force_block -> proceed=False, forced_loop_result=stopped_blocked,
                     forced_stop_reason=operator_loop_force_block
      force_run   -> proceed=True,  suppress_trigger_stop=True
                     (iteration runs; trigger-result-based early stop suppressed)
    """

    def apply(
        self,
        override: OperatorControlOverride,
        iteration_index: int,
    ) -> OperatorLoopContinuationOutcome:
        """Apply operator override before a loop iteration proceeds.

        Args:
            override:        The operator control override for this iteration.
            iteration_index: Zero-based index of the current loop iteration.

        Returns:
            OperatorLoopContinuationOutcome describing whether to proceed
            and whether to suppress trigger-based loop termination.
        """
        decision = override.decision

        if decision == OperatorControlDecision.ALLOW:
            return OperatorLoopContinuationOutcome(
                should_proceed=True,
                suppress_trigger_stop=False,
                forced_loop_result=None,
                forced_stop_reason=None,
                override_ref=override.override_ref,
                override_note=override.override_note,
            )

        if decision == OperatorControlDecision.HOLD:
            return OperatorLoopContinuationOutcome(
                should_proceed=False,
                suppress_trigger_stop=False,
                forced_loop_result=LOOP_RESULT_STOPPED_HOLD,
                forced_stop_reason=OPERATOR_LOOP_STOP_HOLD,
                override_ref=override.override_ref,
                override_note=override.override_note,
            )

        if decision == OperatorControlDecision.FORCE_BLOCK:
            return OperatorLoopContinuationOutcome(
                should_proceed=False,
                suppress_trigger_stop=False,
                forced_loop_result=LOOP_RESULT_STOPPED_BLOCKED,
                forced_stop_reason=OPERATOR_LOOP_STOP_FORCE_BLOCK,
                override_ref=override.override_ref,
                override_note=override.override_note,
            )

        # force_run: proceed and suppress trigger-based early termination
        return OperatorLoopContinuationOutcome(
            should_proceed=True,
            suppress_trigger_stop=True,
            forced_loop_result=None,
            forced_stop_reason=None,
            override_ref=override.override_ref,
            override_note=override.override_note,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Controlled loop — both gates applied per iteration
# ─────────────────────────────────────────────────────────────────────────────


class OperatorControlledLoopBoundary:
    """Phase 7.5 operator-controlled bounded loop over the 7.2 scheduler.

    Extends 7.3 RuntimeAutoRunLoopBoundary with two operator override gates:
      Gate 1 (loop gate)      -- before each iteration: allow / hold / force_block / force_run
      Gate 2 (scheduler gate) -- before each scheduler call: allow / hold / force_block / force_run

    Override always wins deterministically.
    Returns standard RuntimeAutoRunLoopResult compatible with 7.4 observability.

    Pure class -- no state, no side effects, no async.
    """

    def run_loop(
        self,
        scheduler_policy: SchedulerInvocationPolicy,
        max_iterations: int,
        scheduler_override: OperatorControlOverride,
        loop_override: OperatorControlOverride,
    ) -> RuntimeAutoRunLoopResult:
        """Run up to max_iterations scheduler cycles with operator override gates.

        Iteration structure (per iteration i):
          1. Loop gate check (loop_override):
               hold / force_block -> return immediately (iteration NOT executed)
               allow / force_run  -> continue to scheduler gate
          2. Scheduler gate (scheduler_override):
               invokes scheduler or override (allow / hold / force_block / force_run)
          3. Trigger-result check (suppressed when loop_override.decision == force_run):
               stopped_blocked -> loop stops (unless suppressed)
               stopped_hold    -> loop stops (unless suppressed)

        Post-loop terminal conditions (same as 7.3):
          triggers_fired == 0 -> exhausted (no_triggers_fired)
          otherwise           -> completed

        Contract:
          max_iterations <= 0 -> exhausted, invalid_contract, iterations_run=0

        Args:
            scheduler_policy:   Policy for the 7.2 scheduler (trigger policy + conditions).
            max_iterations:     Upper bound on loop iterations. Must be > 0.
            scheduler_override: Operator override applied before each scheduler call.
            loop_override:      Operator override applied before each loop iteration.

        Returns:
            RuntimeAutoRunLoopResult -- standard type compatible with 7.4 observability.
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

        sched_gate = OperatorSchedulerGate()
        loop_gate = OperatorLoopGate()
        triggers_fired = 0

        for i in range(max_iterations):
            # ── Gate 1: loop continuation override ───────────────────────────
            loop_cont = loop_gate.apply(loop_override, i)
            if not loop_cont.should_proceed:
                notes.append(
                    f"loop stopping at iteration={i}: operator"
                    f" {loop_override.decision.value}"
                    f" override_ref={loop_override.override_ref}"
                )
                return RuntimeAutoRunLoopResult(
                    loop_result=loop_cont.forced_loop_result,  # type: ignore[arg-type]
                    loop_stop_reason=loop_cont.forced_stop_reason,
                    iterations_run=i,
                    iteration_records=records,
                    loop_notes=notes,
                )

            # ── Gate 2: scheduler override ────────────────────────────────────
            scheduler_result = sched_gate.apply(scheduler_override, scheduler_policy)

            # ── Process scheduler result (mirrors 7.3 logic) ─────────────────
            trigger_val: Optional[str] = None
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

            # ── Trigger-based early termination (suppressed for force_run) ───
            if not loop_cont.suppress_trigger_stop:
                if trigger_val == _TRIGGER_VAL_STOPPED_BLOCKED:
                    notes.append(
                        f"loop stopping at iteration={i}: trigger returned stopped_blocked"
                    )
                    return RuntimeAutoRunLoopResult(
                        loop_result=LOOP_RESULT_STOPPED_BLOCKED,
                        loop_stop_reason="trigger_returned_stopped_blocked",
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
                        loop_stop_reason="trigger_returned_stopped_hold",
                        iterations_run=i + 1,
                        iteration_records=records,
                        loop_notes=notes,
                    )

        # ── Post-loop terminal result ─────────────────────────────────────────
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


# ─────────────────────────────────────────────────────────────────────────────
# Module-level entrypoints
# ─────────────────────────────────────────────────────────────────────────────


def apply_operator_scheduler_gate(
    override: OperatorControlOverride,
    policy: SchedulerInvocationPolicy,
) -> SchedulerInvocationResult:
    """Deterministic operator override gate before the 7.2 scheduler decision."""
    return OperatorSchedulerGate().apply(override, policy)


def apply_operator_loop_gate(
    override: OperatorControlOverride,
    iteration_index: int,
) -> OperatorLoopContinuationOutcome:
    """Deterministic operator override gate before a 7.3 loop iteration proceeds."""
    return OperatorLoopGate().apply(override, iteration_index)


def run_operator_controlled_loop(
    scheduler_policy: SchedulerInvocationPolicy,
    max_iterations: int,
    scheduler_override: OperatorControlOverride,
    loop_override: OperatorControlOverride,
) -> RuntimeAutoRunLoopResult:
    """Deterministic operator-controlled bounded loop entrypoint."""
    return OperatorControlledLoopBoundary().run_loop(
        scheduler_policy, max_iterations, scheduler_override, loop_override
    )
