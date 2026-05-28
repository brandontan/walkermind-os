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


# ── Live opt-in shared constants (single source of truth for BOTH surfaces) ──
# WebTrader (full control) and the Telegram bot (simple control) MUST agree on
# these values so the per-user live opt-in behaves identically everywhere.

# Exact phrase the WebTrader "full" flow requires the user to type. The Telegram
# "simple" flow uses a shorter CONFIRM word but writes the SAME settings + cap.
LIVE_ENABLE_CONFIRM_PHRASE = "ENABLE LIVE TRADING FOR MY ACCOUNT"

# Per-user live capital cap bounds. The cap is the maximum USDC of *aggregate*
# open live exposure the risk gate (gate.py step 15) will allow for this user.
# cap = 0 means "not opted in" — every live trade is rejected (live_not_opted_in).
LIVE_CAP_MIN_USDC: float = 0.0       # exclusive — cap must be > 0 to trade live
LIVE_CAP_MAX_USDC: float = 10_000.0  # inclusive system ceiling — no user exceeds


class LiveCapError(ValueError):
    """Raised when a proposed live capital cap is invalid (out of bounds /
    unparseable). Message is human-readable and safe to show the user."""


def validate_live_capital_cap(raw: object) -> float:
    """Parse + bounds-check a user-supplied live capital cap.

    Accepts raw user input (str or number), strips common currency decoration
    ($ , _) and enforces ``LIVE_CAP_MIN_USDC < cap <= LIVE_CAP_MAX_USDC``.
    Raises ``LiveCapError`` with a human-readable message on any failure so the
    caller can surface it directly. Single source of truth shared by the
    WebTrader endpoint and the Telegram /enable_live flow.
    """
    if isinstance(raw, str):
        cleaned: object = raw.strip().lstrip("$").replace(",", "").replace("_", "")
    else:
        cleaned = raw
    try:
        cap = float(cleaned)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise LiveCapError(
            "Enter a number between 1 and 10000 (USDC), e.g. 500"
        )
    if cap != cap or cap in (float("inf"), float("-inf")):  # NaN / inf guard
        raise LiveCapError("Enter a real number between 1 and 10000 (USDC)")
    if not (LIVE_CAP_MIN_USDC < cap <= LIVE_CAP_MAX_USDC):
        raise LiveCapError(
            f"Capital cap must be greater than 0 and at most "
            f"{LIVE_CAP_MAX_USDC:,.0f} USDC"
        )
    return round(cap, 6)


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
) -> bool:
    """INSERT one row into mode_change_events.

    Returns True on success, False if the audit write failed. Never raises: a
    failed audit write must not block the user's mode change, but the caller
    SHOULD surface a soft warning so the gap is visible rather than silent
    (CLAUDE.md HARD RULE: no silent failures).
    """
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO mode_change_events "
                "(user_id, from_mode, to_mode, reason) "
                "VALUES ($1, $2, $3, $4)",
                user_id, from_mode, to_mode, reason.value,
            )
        return True
    except Exception as exc:
        logger.error(
            "mode_change_event write failed user=%s from=%s to=%s reason=%s err=%s",
            user_id, from_mode, to_mode, reason.value, exc,
        )
        return False
