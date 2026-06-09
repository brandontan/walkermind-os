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

import structlog

from ...config import get_settings
from ...database import get_pool
from ...domain.ops import kill_switch as ops_kill_switch

log = structlog.get_logger(__name__)


async def _set_system_flag(key: str, value: str) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO system_settings (key, value, updated_at) VALUES ($1, $2, NOW()) "
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
    # Mirror into the canonical forensic destination (`audit.log` schema table,
    # the single source every other subsystem writes via `audit.write`). Without
    # this, kill-switch events were siloed in the public `audit_log` table and
    # invisible to a unified forensic query. `audit.write` never raises, so the
    # mirror cannot break the kill path; the legacy `audit_log` row above is kept
    # for backward compatibility with existing kill-switch dashboards/queries.
    from ... import audit as _audit
    await _audit.write(
        actor_role="system",
        action=event.lower(),
        payload={"reason": reason, "triggered_by": triggered_by},
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


async def _broker_cancel_all_orders() -> dict:
    """Cancel EVERY resting order on the exchange via the CLOB broker.

    WARP-74 Chunk B — the DB-only ``_cancel_pending_orders`` above marks rows
    ``cancelled`` but leaves resting GTC orders LIVE on Polymarket. That is
    false safety: the operator hits STOP, the DB looks halted, yet exchange
    orders keep working and can still fill. This calls
    ``client.cancel_all_orders()`` (global) so the broker actually pulls every
    resting order.

    Paper / non-live is a no-op (MockClobClient places nothing on-chain, and we
    refuse to construct a real client when USE_REAL_CLOB is off). Best-effort:
    any failure is logged + returned but must NEVER block the rest of the kill
    sequence — a broker-cancel that fails still leaves the DB-cancel + gate halt
    in force, and the caller escalates to the operator.

    Returns a small result dict for the audit trail.
    """
    s = get_settings()
    if not bool(getattr(s, "USE_REAL_CLOB", False)):
        return {"attempted": False, "cancelled": False, "skipped_paper": True}

    from ...integrations.clob import get_clob_client

    client = None
    try:
        client = get_clob_client(s)
        result = await client.cancel_all_orders()
        log.info("kill_switch_exec: broker cancel_all_orders ok", result=str(result)[:300])
        return {"attempted": True, "cancelled": True, "broker_result": str(result)[:300]}
    except Exception as exc:  # noqa: BLE001 — must never block the kill sequence
        log.error("kill_switch_exec: broker cancel_all_orders FAILED", err=str(exc))
        return {"attempted": True, "cancelled": False, "error": str(exc)[:300]}
    finally:
        if client is not None:
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001
                log.warning("kill_switch_exec: broker client aclose failed")


async def execute_kill_switch(reason: str, triggered_by: str) -> None:
    """Single shutdown logic — called from all 3 activation paths.

    Convergence guarantee: every path calls this function.
    Audit log entry is written unconditionally.
    """
    log.critical("KILL SWITCH ACTIVATED", reason=reason, triggered_by=triggered_by)

    # 1. Activate via existing ops module (system_settings + kill_switch_history)
    try:
        await ops_kill_switch.set_active(action="pause", reason=reason)
    except Exception as exc:
        log.error("kill_switch_exec: set_active failed", err=str(exc))

    # 2. Broker-cancel EVERY resting order on the exchange (WARP-74 Chunk B).
    #    This is the real-world halt: it pulls live GTC orders off Polymarket so
    #    they cannot keep filling after STOP. Runs BEFORE the DB-cancel so the
    #    exchange stops working orders as early as possible. Best-effort — a
    #    failure is escalated to the operator below but never blocks the kill.
    broker_cancel = {"attempted": False, "cancelled": False}
    try:
        broker_cancel = await _broker_cancel_all_orders()
        log.info("kill_switch_exec: broker cancel result", **broker_cancel)
    except Exception as exc:
        log.error("kill_switch_exec: broker cancel raised (non-blocking)", err=str(exc))

    # 3. Cancel all pending orders in the DB (status bookkeeping)
    try:
        n = await _cancel_pending_orders()
        log.info("kill_switch_exec: cancelled pending orders", count=n)
    except Exception as exc:
        log.error("kill_switch_exec: pending order cancel failed", err=str(exc))

    # 4. Set system_settings record (kill_switch_active key)
    try:
        await _set_system_flag("kill_switch_active", "true")
    except Exception as exc:
        log.error("kill_switch_exec: system_settings write failed", err=str(exc))

    # 5. Audit log (mandatory — no silent activations). The broker-cancel
    #    outcome rides along so a failed exchange cancel is forensically visible.
    try:
        await _write_audit_log(
            event="KILL_SWITCH_ACTIVATED",
            triggered_by=triggered_by,
            reason=(
                f"{reason} | broker_cancel="
                f"{'ok' if broker_cancel.get('cancelled') else broker_cancel}"
            ),
        )
    except Exception as exc:
        log.error("kill_switch_exec: audit_log write failed", err=str(exc))

    # 6. Notify admin via Telegram (best-effort — failure must not block the kill).
    #    If the broker-cancel was ATTEMPTED but FAILED, the operator MUST know the
    #    DB looks halted while resting exchange orders may still be live.
    broker_warn = ""
    if broker_cancel.get("attempted") and not broker_cancel.get("cancelled"):
        broker_warn = (
            "\n⚠️ BROKER CANCEL FAILED — resting orders may still be LIVE on "
            "Polymarket. Cancel manually on the exchange NOW."
        )
    try:
        from ...notifications import notify_operator
        await notify_operator(
            f"🚨 KILL SWITCH ACTIVATED\nReason: {reason}\nBy: {triggered_by}"
            f"{broker_warn}"
        )
    except Exception as exc:
        log.error("kill_switch_exec: admin notify failed (non-blocking)", err=str(exc))


async def reset_kill_switch(triggered_by: str) -> None:
    """Reset the kill switch via Telegram admin command."""
    log.info("KILL SWITCH RESET", triggered_by=triggered_by)

    try:
        await ops_kill_switch.set_active(action="resume")
    except Exception as exc:
        log.error("kill_switch_exec: reset set_active failed", err=str(exc))

    try:
        await _set_system_flag("kill_switch_active", "false")
    except Exception as exc:
        log.error("kill_switch_exec: reset system_settings write failed", err=str(exc))

    try:
        await _write_audit_log(
            event="KILL_SWITCH_RESET",
            triggered_by=triggered_by,
        )
    except Exception as exc:
        log.error("kill_switch_exec: reset audit_log write failed", err=str(exc))
