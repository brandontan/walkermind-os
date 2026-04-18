"""Phase 7.1 thin CLI trigger surface for deterministic public activation cycle.

This module exposes one synchronous invocation path only: a CLI entrypoint that
builds a :class:`PublicActivationCyclePolicy`, runs the existing
``run_public_activation_cycle(...)`` contract, validates the returned contract,
and maps it to explicit invocation outcomes.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Sequence

from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
    PUBLIC_ACTIVATION_CYCLE_RESULT_COMPLETED,
    PUBLIC_ACTIVATION_CYCLE_RESULT_STOPPED_BLOCKED,
    PUBLIC_ACTIVATION_CYCLE_RESULT_STOPPED_HOLD,
    PublicActivationCyclePolicy,
    PublicActivationCycleResult,
    run_public_activation_cycle,
)

_TRIGGER_RESULT_COMPLETED = "completed"
_TRIGGER_RESULT_STOPPED_HOLD = "stopped_hold"
_TRIGGER_RESULT_STOPPED_BLOCKED = "stopped_blocked"


@dataclass(frozen=True)
class PublicActivationTriggerResult:
    """Thin trigger output mapped from cycle result categories."""

    trigger_result: str
    cycle_result_category: str
    cycle_stop_reason: str | None
    cycle_completed: bool
    wallet_binding_id: str
    owner_user_id: str
    cycle_notes: list[str]


def invoke_public_activation_cycle_trigger(
    policy: PublicActivationCyclePolicy,
) -> PublicActivationTriggerResult:
    """Run one deterministic public activation cycle through the CLI trigger surface."""
    _validate_trigger_policy_contract(policy)
    cycle_result = run_public_activation_cycle(policy)
    return _map_trigger_result(cycle_result)


def _validate_trigger_policy_contract(policy: PublicActivationCyclePolicy) -> None:
    if not policy.wallet_binding_id.strip():
        raise ValueError("invalid trigger policy: wallet_binding_id must be non-empty")
    if not policy.owner_user_id.strip():
        raise ValueError("invalid trigger policy: owner_user_id must be non-empty")
    if not policy.requester_user_id.strip():
        raise ValueError("invalid trigger policy: requester_user_id must be non-empty")


def _map_trigger_result(cycle_result: PublicActivationCycleResult) -> PublicActivationTriggerResult:
    mapped_result = {
        PUBLIC_ACTIVATION_CYCLE_RESULT_COMPLETED: _TRIGGER_RESULT_COMPLETED,
        PUBLIC_ACTIVATION_CYCLE_RESULT_STOPPED_HOLD: _TRIGGER_RESULT_STOPPED_HOLD,
        PUBLIC_ACTIVATION_CYCLE_RESULT_STOPPED_BLOCKED: _TRIGGER_RESULT_STOPPED_BLOCKED,
    }.get(cycle_result.cycle_result_category)
    if mapped_result is None:
        raise ValueError(
            "invalid cycle result contract: unsupported cycle_result_category="
            f"{cycle_result.cycle_result_category!r}"
        )

    if mapped_result == _TRIGGER_RESULT_COMPLETED and cycle_result.cycle_stop_reason is not None:
        raise ValueError(
            "invalid cycle result contract: completed result must not include cycle_stop_reason"
        )
    if mapped_result != _TRIGGER_RESULT_COMPLETED and cycle_result.cycle_stop_reason is None:
        raise ValueError(
            "invalid cycle result contract: stopped result must include cycle_stop_reason"
        )

    return PublicActivationTriggerResult(
        trigger_result=mapped_result,
        cycle_result_category=cycle_result.cycle_result_category,
        cycle_stop_reason=cycle_result.cycle_stop_reason,
        cycle_completed=cycle_result.cycle_completed,
        wallet_binding_id=cycle_result.wallet_binding_id,
        owner_user_id=cycle_result.owner_user_id,
        cycle_notes=list(cycle_result.cycle_notes),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="public-activation-trigger",
        description="Run one deterministic public activation cycle via the Phase 7.1 trigger surface.",
    )
    parser.add_argument("--wallet-binding-id", required=True)
    parser.add_argument("--owner-user-id", required=True)
    parser.add_argument("--requester-user-id", required=True)
    parser.add_argument("--wallet-active", required=True, choices=("true", "false"))
    parser.add_argument("--state-read-batch-ready", required=True, choices=("true", "false"))
    parser.add_argument("--reconciliation-outcome", required=True)
    parser.add_argument("--correction-result-category", required=True)
    parser.add_argument("--retry-result-category", required=True)
    return parser


def _to_bool(value: str) -> bool:
    return value == "true"


def _policy_from_args(args: argparse.Namespace) -> PublicActivationCyclePolicy:
    return PublicActivationCyclePolicy(
        wallet_binding_id=args.wallet_binding_id,
        owner_user_id=args.owner_user_id,
        requester_user_id=args.requester_user_id,
        wallet_active=_to_bool(args.wallet_active),
        state_read_batch_ready=_to_bool(args.state_read_batch_ready),
        reconciliation_outcome=args.reconciliation_outcome,
        correction_result_category=args.correction_result_category,
        retry_result_category=args.retry_result_category,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    trigger_result = invoke_public_activation_cycle_trigger(_policy_from_args(args))
    print(
        json.dumps(
            {
                "trigger_result": trigger_result.trigger_result,
                "cycle_result_category": trigger_result.cycle_result_category,
                "cycle_stop_reason": trigger_result.cycle_stop_reason,
                "cycle_completed": trigger_result.cycle_completed,
                "wallet_binding_id": trigger_result.wallet_binding_id,
                "owner_user_id": trigger_result.owner_user_id,
                "cycle_notes": trigger_result.cycle_notes,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
