"""Unified kill switch executor — Track D Risk Caps + Kill Switch.

Three activation paths all converge here:
  Path 1 — Telegram /kill command (bot/handlers/admin.py)
  Path 2 — DB flag checked by scanner on each tick (jobs/market_signal_scanner.py)
  Path 3 — Env var KILL_SWITCH=true checked on startup (main.py)

All paths call execute_kill_switch(reason, triggered_by). No duplicate logic.
Every activation writes an audit_log row — no silent activations.
Admin notification is best-effort (try/except) and must not block the kill.
"""
from __future__ import annotations

import logging

from ...database import get_pool
from ...domain.ops import kill_switch as ops_kill_switch

logger = logging.getLogger(__name__)


async def _set_system_flag(key: str, value: str) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO system_flags (key, value, updated_at) VALUES ($1, $2, NOW()) "
            "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()",
            key, value,
        )


async def _write_audit_log(
    event: str,
    triggered_by: str,
    reason: str | None = None,
) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO audit_log (event, reason, triggered_by, created_at) "
            "VALUES ($1, $2, $3, NOW())",
            event, reason, triggered_by,
        )


async def _cancel_pending_orders() -> int:
    """Mark all pending orders cancelled. Returns count affected."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE orders SET status='cancelled', updated_at=NOW() "
            "WHERE status='pending'"
        )
    try:
        return int(str(result).split()[-1])
    except Exception:
        return 0


async def execute_kill_switch(reason: str, triggered_by: str) -> None:
    """Single shutdown logic — called from all 3 activation paths.

    Convergence guarantee: every path calls this function.
    Audit log entry is written unconditionally.
    """
    logger.critical(
        "KILL SWITCH ACTIVATED: reason=%s triggered_by=%s", reason, triggered_by
    )

    # 1. Activate via existing ops module (system_settings + kill_switch_history)
    try:
        await ops_kill_switch.set_active(action="pause", reason=reason)
    except Exception as exc:
        logger.error("kill_switch_exec: set_active failed: %s", exc)

    # 2. Cancel all pending orders
    try:
        n = await _cancel_pending_orders()
        logger.info("kill_switch_exec: cancelled %d pending orders", n)
    except Exception as exc:
        logger.error("kill_switch_exec: pending order cancel failed: %s", exc)

    # 3. Set system_flags record (Track D flag table)
    try:
        await _set_system_flag("kill_switch_active", "true")
    except Exception as exc:
        logger.error("kill_switch_exec: system_flags write failed: %s", exc)

    # 4. Audit log (mandatory — no silent activations)
    try:
        await _write_audit_log(
            event="KILL_SWITCH_ACTIVATED",
            triggered_by=triggered_by,
            reason=reason,
        )
    except Exception as exc:
        logger.error("kill_switch_exec: audit_log write failed: %s", exc)

    # 5. Notify admin via Telegram (best-effort — failure must not block the kill)
    try:
        from ...notifications import notify_operator
        await notify_operator(
            f"🚨 KILL SWITCH ACTIVATED\nReason: {reason}\nBy: {triggered_by}"
        )
    except Exception as exc:
        logger.error("kill_switch_exec: admin notify failed (non-blocking): %s", exc)


async def reset_kill_switch(triggered_by: str) -> None:
    """Reset the kill switch via Telegram admin command."""
    logger.info("KILL SWITCH RESET: triggered_by=%s", triggered_by)

    try:
        await ops_kill_switch.set_active(action="resume")
    except Exception as exc:
        logger.error("kill_switch_exec: reset set_active failed: %s", exc)

    try:
        await _set_system_flag("kill_switch_active", "false")
    except Exception as exc:
        logger.error("kill_switch_exec: reset system_flags write failed: %s", exc)

    try:
        await _write_audit_log(
            event="KILL_SWITCH_RESET",
            triggered_by=triggered_by,
        )
    except Exception as exc:
        logger.error("kill_switch_exec: reset audit_log write failed: %s", exc)
