"""R12 Live-to-Paper Fallback.

Single entry point that flips a user from live mode to paper mode in
response to a non-recoverable trading fault. The fallback intentionally
does NOT close existing positions — already-open exposure must continue
to be unwindable through the close router. Only NEW signal scans are
deflected to paper after the flip.

Trigger conditions (wired by callers, not auto-detected here):

    [1] CLOB non-recoverable error after live submit retry exhaustion
    [2] Risk gate halts (kill_switch active OR drawdown breached)
    [3] Operator kill switch activated system-wide (cascading per-user
        flip handled by ``trigger_all_live_users``)
    [4] ENABLE_LIVE_TRADING flag unset at runtime

Recovery is NOT automatic. The user must re-run /live_checklist and
manually re-toggle auto-trade with text confirmation before live mode
re-engages.
"""
from __future__ import annotations

import html
import logging
from typing import Optional
from uuid import UUID

from ... import audit, notifications
from ...database import get_pool

logger = logging.getLogger(__name__)


# ---------------- Reason taxonomy -------------------------------------------

REASON_CLOB_NON_RECOVERABLE = "clob_non_recoverable_error"
REASON_RISK_HALT_KILL_SWITCH = "risk_halt_kill_switch"
REASON_RISK_HALT_DRAWDOWN = "risk_halt_drawdown"
REASON_KILL_SWITCH_SYSTEM = "operator_kill_switch_active"
REASON_LIVE_GUARD_UNSET = "enable_live_trading_unset"

VALID_REASONS: frozenset[str] = frozenset({
    REASON_CLOB_NON_RECOVERABLE,
    REASON_RISK_HALT_KILL_SWITCH,
    REASON_RISK_HALT_DRAWDOWN,
    REASON_KILL_SWITCH_SYSTEM,
    REASON_LIVE_GUARD_UNSET,
})

# Reason-specific user-facing copy. Operator-coded labels appear verbatim
# in the audit row; this map only governs Telegram presentation so a copy
# tweak does not retroactively rewrite history.
_REASON_USER_COPY: dict[str, str] = {
    REASON_CLOB_NON_RECOVERABLE:
        "Polymarket order pipeline returned a non-recoverable error.",
    REASON_RISK_HALT_KILL_SWITCH:
        "Operator kill switch is currently active.",
    REASON_RISK_HALT_DRAWDOWN:
        "Account drawdown crossed the safety threshold.",
    REASON_KILL_SWITCH_SYSTEM:
        "Operator activated the system-wide kill switch.",
    REASON_LIVE_GUARD_UNSET:
        "ENABLE_LIVE_TRADING was disabled by the operator.",
}


def _user_copy(reason: str) -> str:
    return _REASON_USER_COPY.get(reason, f"Reason: {reason}")


# ---------------- Single-user trigger ---------------------------------------


async def trigger(user_id: UUID, reason: str) -> dict:
    """Switch a single user's ``user_settings.trading_mode`` to ``paper``.

    Idempotent: if the user is already on paper, the call is a no-op and
    returns ``{"changed": False, ...}`` without producing audit / notify
    noise. Returns the prior mode so the caller can branch on whether a
    user-visible change actually occurred.

    Raises ``ValueError`` if ``reason`` is not in :data:`VALID_REASONS`
    so a typo can never silently downgrade a user.
    """
    if reason not in VALID_REASONS:
        raise ValueError(f"invalid fallback reason: {reason!r}")

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT s.trading_mode AS mode, u.telegram_user_id AS tg_id "
            "FROM user_settings s JOIN users u ON u.id = s.user_id "
            "WHERE s.user_id = $1",
            user_id,
        )
        if row is None:
            logger.warning(
                "live_to_paper_fallback: user_id=%s has no user_settings row",
                user_id,
            )
            return {"changed": False, "previous_mode": None}
        previous_mode = row["mode"]
        telegram_id = row["tg_id"]
        if previous_mode != "live":
            return {"changed": False, "previous_mode": previous_mode}
        await conn.execute(
            "UPDATE user_settings SET trading_mode='paper', updated_at=NOW() "
            "WHERE user_id=$1 AND trading_mode='live'",
            user_id,
        )

    try:
        await audit.write(
            actor_role="bot",
            action="live_to_paper_fallback",
            user_id=user_id,
            payload={"reason": reason, "previous_mode": previous_mode},
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "fallback audit write failed user=%s reason=%s err=%s",
            user_id, reason, exc,
        )

    if telegram_id is not None:
        try:
            await notifications.send(
                int(telegram_id),
                "⚠️ <b>Auto-trade switched to paper mode.</b>\n"
                f"{html.escape(_user_copy(reason))}\n"
                "No new live orders will be placed. Existing positions are "
                "unaffected — exits will continue to execute.\n\n"
                "Re-run /live_checklist and toggle auto-trade again to "
                "return to live mode.",
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "fallback notify failed user=%s tg=%s err=%s",
                user_id, telegram_id, exc,
            )

    return {"changed": True, "previous_mode": previous_mode}


# ---------------- System-wide cascade (kill switch lock) --------------------


async def trigger_all_live_users(reason: str) -> dict:
    """Flip every user currently in live mode to paper mode in one transaction.

    Used by the operator kill-switch ``lock`` path so a single SQL UPDATE
    drains the live cohort without per-user round trips. Each affected
    user gets one audit row and one Telegram notification — both happen
    after the DB flip so a notify failure cannot leave users in live mode.
    """
    if reason not in VALID_REASONS:
        raise ValueError(f"invalid fallback reason: {reason!r}")

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            affected = await conn.fetch(
                "UPDATE user_settings s SET trading_mode='paper', updated_at=NOW() "
                "FROM users u "
                "WHERE s.user_id = u.id AND s.trading_mode = 'live' "
                "RETURNING s.user_id, u.telegram_user_id",
            )
    affected_count = len(affected)
    if affected_count == 0:
        return {"changed": 0}

    for r in affected:
        try:
            await audit.write(
                actor_role="bot",
                action="live_to_paper_fallback",
                user_id=r["user_id"],
                payload={"reason": reason, "previous_mode": "live",
                         "cascade": True},
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "cascade audit write failed user=%s err=%s",
                r["user_id"], exc,
            )
        if r["telegram_user_id"] is not None:
            try:
                await notifications.send(
                    int(r["telegram_user_id"]),
                    "⚠️ <b>Auto-trade switched to paper mode.</b>\n"
                    f"{html.escape(_user_copy(reason))}\n"
                    "No new live orders will be placed. Existing positions "
                    "are unaffected.",
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "cascade notify failed user=%s err=%s",
                    r["user_id"], exc,
                )

    return {"changed": affected_count}


# ---------------- Convenience wrappers (used by call sites) -----------------


async def trigger_for_clob_error(user_id: UUID) -> dict:
    return await trigger(user_id, REASON_CLOB_NON_RECOVERABLE)


async def trigger_for_kill_switch_halt(user_id: UUID) -> dict:
    return await trigger(user_id, REASON_RISK_HALT_KILL_SWITCH)


async def trigger_for_drawdown_halt(user_id: UUID) -> dict:
    return await trigger(user_id, REASON_RISK_HALT_DRAWDOWN)


async def trigger_for_live_guard_unset(user_id: UUID) -> dict:
    return await trigger(user_id, REASON_LIVE_GUARD_UNSET)
