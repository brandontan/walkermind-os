"""Observability helpers for Telegram-triggered trade execution paths.

This module centralizes event constants and deterministic terminal-outcome
classification for the `/trade` command path.
"""
from __future__ import annotations

from dataclasses import dataclass

EVENT_STAGE: str = "stage"
EVENT_OUTCOME: str = "outcome"

STAGE_COMMAND: str = "command"
STAGE_EXECUTION: str = "execution"
STAGE_RISK: str = "risk"

OUTCOME_STARTED: str = "started"
OUTCOME_EXECUTED: str = "executed"
OUTCOME_FAILED: str = "failed"
OUTCOME_BLOCKED: str = "blocked"


@dataclass(frozen=True)
class ClassifiedOutcome:
    """Deterministic classification for a terminal `/trade` result."""

    outcome: str
    reason: str


def classify_result(*, success: bool, message: str) -> ClassifiedOutcome:
    """Classify a terminal command result into canonical observability outcomes.

    BLOCKED outcomes are explicitly identified and never fall through to the
    generic FAILED bucket.
    """

    normalized_message = str(message or "").strip().lower()
    if "blocked" in normalized_message:
        return ClassifiedOutcome(outcome=OUTCOME_BLOCKED, reason="blocked_message")
    if success:
        return ClassifiedOutcome(outcome=OUTCOME_EXECUTED, reason="success")
    return ClassifiedOutcome(outcome=OUTCOME_FAILED, reason="failure")
