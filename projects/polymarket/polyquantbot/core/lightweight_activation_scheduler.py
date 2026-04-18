"""Phase 7.2 lightweight automation scheduler contract for the public activation trigger.

Single synchronous invocation cycle. No distributed workers, no async queue mesh,
no cron daemon. Scheduler result categories: triggered / skipped / blocked.
"""
from __future__ import annotations

from dataclasses import dataclass

from projects.polymarket.polyquantbot.api.public_activation_trigger_cli import (
    PublicActivationTriggerResult,
    invoke_public_activation_cycle_trigger,
)
from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
    PublicActivationCyclePolicy,
)

# Scheduler result categories
SCHEDULER_RESULT_TRIGGERED = "triggered"
SCHEDULER_RESULT_SKIPPED = "skipped"
SCHEDULER_RESULT_BLOCKED = "blocked"

# Skip reasons (soft decisions -- conditions not met)
SCHEDULER_SKIP_ALREADY_RUNNING = "already_running"
SCHEDULER_SKIP_WINDOW_NOT_OPEN = "window_not_open"
SCHEDULER_SKIP_QUOTA_REACHED = "quota_reached"

# Block reasons (hard stops)
SCHEDULER_BLOCK_SCHEDULE_DISABLED = "schedule_disabled"
SCHEDULER_BLOCK_INVALID_CONTRACT = "invalid_contract"


@dataclass(frozen=True)
class SchedulerInvocationPolicy:
    """Policy contract for one lightweight scheduler invocation cycle.

    schedule_enabled=False -> blocked (schedule_disabled).
    concurrent_invocation_active=True -> skipped (already_running).
    invocation_window_open=False -> skipped (window_not_open).
    invocation_quota_remaining=0 -> skipped (quota_reached).
    All conditions met -> trigger invoked via 7.1 surface.
    """

    trigger_policy: PublicActivationCyclePolicy
    schedule_enabled: bool
    invocation_window_open: bool
    invocation_quota_remaining: int
    concurrent_invocation_active: bool


@dataclass(frozen=True)
class SchedulerInvocationResult:
    """Result of one lightweight scheduler invocation decision."""

    scheduler_result: str
    skip_reason: str | None
    block_reason: str | None
    trigger_result: PublicActivationTriggerResult | None
    scheduler_notes: list[str]


class LightweightActivationSchedulerBoundary:
    """Phase 7.2 deterministic scheduler for the 7.1 public activation trigger.

    One synchronous invocation cycle at a time.
    No distributed workers, no async queue mesh, no cron daemon rollout.
    """

    def decide_and_invoke(self, policy: SchedulerInvocationPolicy) -> SchedulerInvocationResult:
        """Evaluate scheduling conditions; invoke 7.1 trigger only if all conditions are met.

        Decision priority (deterministic, evaluated in order):
        1. schedule_disabled  -> blocked
        2. already_running    -> skipped
        3. window_not_open    -> skipped
        4. quota_reached      -> skipped  (quota == 0)
        5. invalid_contract   -> blocked  (quota < 0)
        6. all conditions met -> triggered
        """
        notes: list[str] = []

        if not policy.schedule_enabled:
            notes.append("schedule_disabled: scheduler is not enabled")
            return SchedulerInvocationResult(
                scheduler_result=SCHEDULER_RESULT_BLOCKED,
                skip_reason=None,
                block_reason=SCHEDULER_BLOCK_SCHEDULE_DISABLED,
                trigger_result=None,
                scheduler_notes=notes,
            )

        if policy.concurrent_invocation_active:
            notes.append("already_running: concurrent invocation is active")
            return SchedulerInvocationResult(
                scheduler_result=SCHEDULER_RESULT_SKIPPED,
                skip_reason=SCHEDULER_SKIP_ALREADY_RUNNING,
                block_reason=None,
                trigger_result=None,
                scheduler_notes=notes,
            )

        if not policy.invocation_window_open:
            notes.append("window_not_open: invocation window is not open")
            return SchedulerInvocationResult(
                scheduler_result=SCHEDULER_RESULT_SKIPPED,
                skip_reason=SCHEDULER_SKIP_WINDOW_NOT_OPEN,
                block_reason=None,
                trigger_result=None,
                scheduler_notes=notes,
            )

        if policy.invocation_quota_remaining == 0:
            notes.append("quota_reached: invocation quota is exhausted")
            return SchedulerInvocationResult(
                scheduler_result=SCHEDULER_RESULT_SKIPPED,
                skip_reason=SCHEDULER_SKIP_QUOTA_REACHED,
                block_reason=None,
                trigger_result=None,
                scheduler_notes=notes,
            )

        if policy.invocation_quota_remaining < 0:
            notes.append("invalid_contract: invocation_quota_remaining must be >= 0")
            return SchedulerInvocationResult(
                scheduler_result=SCHEDULER_RESULT_BLOCKED,
                skip_reason=None,
                block_reason=SCHEDULER_BLOCK_INVALID_CONTRACT,
                trigger_result=None,
                scheduler_notes=notes,
            )

        notes.append("triggering: all scheduling conditions met")
        trigger_result = invoke_public_activation_cycle_trigger(policy.trigger_policy)
        notes.append(f"trigger_result={trigger_result.trigger_result}")
        return SchedulerInvocationResult(
            scheduler_result=SCHEDULER_RESULT_TRIGGERED,
            skip_reason=None,
            block_reason=None,
            trigger_result=trigger_result,
            scheduler_notes=notes,
        )


def decide_and_invoke_scheduler(policy: SchedulerInvocationPolicy) -> SchedulerInvocationResult:
    """Deterministic lightweight scheduler entrypoint for one synchronous invocation cycle."""
    return LightweightActivationSchedulerBoundary().decide_and_invoke(policy)
