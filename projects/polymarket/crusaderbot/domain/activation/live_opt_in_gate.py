"""Track F — Live Opt-In Gate: guard validation + mode-change audit.

Responsibilities:
- Read-only check of the 4 global activation guards required before the
  3-step confirmation flow is allowed to begin.
- Write immutable rows to ``mode_change_events`` on every trading-mode
  transition (USER_CONFIRMED, AUTO_FALLBACK, OPERATOR_OVERRIDE).

Neither function here sets any activation guard. Read-only only.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from uuid import UUID

from ...config import Settings, get_settings
from ...database import get_pool

logger = logging.getLogger(__name__)


# ── Guard names (mirroring config fields) ────────────────────────────────────

GUARD_ENABLE_LIVE_TRADING = "ENABLE_LIVE_TRADING"
GUARD_EXECUTION_PATH_VALIDATED = "EXECUTION_PATH_VALIDATED"
GUARD_CAPITAL_MODE_CONFIRMED = "CAPITAL_MODE_CONFIRMED"
GUARD_RISK_CONTROLS_VALIDATED = "RISK_CONTROLS_VALIDATED"

ALL_GUARDS: tuple[str, ...] = (
    GUARD_ENABLE_LIVE_TRADING,
    GUARD_EXECUTION_PATH_VALIDATED,
    GUARD_CAPITAL_MODE_CONFIRMED,
    GUARD_RISK_CONTROLS_VALIDATED,
)


class ModeChangeReason(str, Enum):
    USER_CONFIRMED = "USER_CONFIRMED"
    AUTO_FALLBACK = "AUTO_FALLBACK"
    OPERATOR_OVERRIDE = "OPERATOR_OVERRIDE"


@dataclass
class GuardCheckResult:
    all_set: bool
    missing: list[str] = field(default_factory=list)


# ── Guard check ───────────────────────────────────────────────────────────────


def check_activation_guards(
    settings: Optional[Settings] = None,
) -> GuardCheckResult:
    """Return whether all 4 pre-requisite guards are SET (True).

    Read-only. Never raises. Never sets any guard.
    """
    s = settings or get_settings()
    guard_values: dict[str, bool] = {
        GUARD_ENABLE_LIVE_TRADING:       bool(s.ENABLE_LIVE_TRADING),
        GUARD_EXECUTION_PATH_VALIDATED:  bool(s.EXECUTION_PATH_VALIDATED),
        GUARD_CAPITAL_MODE_CONFIRMED:    bool(s.CAPITAL_MODE_CONFIRMED),
        GUARD_RISK_CONTROLS_VALIDATED:   bool(s.RISK_CONTROLS_VALIDATED),
    }
    missing = [name for name in ALL_GUARDS if not guard_values[name]]
    return GuardCheckResult(all_set=not missing, missing=missing)


# ── Mode-change audit log ─────────────────────────────────────────────────────


async def write_mode_change_event(
    *,
    user_id: Optional[UUID],
    from_mode: str,
    to_mode: str,
    reason: ModeChangeReason,
) -> None:
    """INSERT one row into mode_change_events. Never raises."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO mode_change_events "
                "(user_id, from_mode, to_mode, reason) "
                "VALUES ($1, $2, $3, $4)",
                user_id, from_mode, to_mode, reason.value,
            )
    except Exception as exc:
        logger.error(
            "mode_change_event write failed user=%s from=%s to=%s reason=%s err=%s",
            user_id, from_mode, to_mode, reason.value, exc,
        )
