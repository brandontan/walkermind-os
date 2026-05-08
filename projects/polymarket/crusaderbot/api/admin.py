"""Operator REST endpoints — bearer-protected by ADMIN_API_TOKEN.

Disabled when ADMIN_API_TOKEN is unset. Telegram /admin commands remain the
primary operator surface; this REST layer is for monitoring scripts and
emergency tooling. Never use OPERATOR_CHAT_ID as an auth secret — it is
discoverable from Telegram metadata.
"""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Header, HTTPException

from ..config import get_settings
from ..database import get_pool, is_kill_switch_active, set_kill_switch
from ..monitoring import sentry as monitoring_sentry
from .. import scheduler

router = APIRouter(prefix="/admin")


def _check(token: str | None) -> None:
    expected = get_settings().ADMIN_API_TOKEN
    if not expected:
        raise HTTPException(status_code=503,
                            detail="admin API disabled (ADMIN_API_TOKEN unset)")
    if not token or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="forbidden")


@router.get("/status")
async def status(authorization: str | None = Header(default=None)):
    token = authorization.removeprefix("Bearer ").strip() if authorization else None
    _check(token)
    pool = get_pool()
    async with pool.acquire() as conn:
        users = await conn.fetchval("SELECT COUNT(*) FROM users")
        funded = await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE access_tier>=3")
        live = await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE access_tier>=4")
        open_paper = await conn.fetchval(
            "SELECT COUNT(*) FROM positions WHERE status='open' AND mode='paper'")
        open_live = await conn.fetchval(
            "SELECT COUNT(*) FROM positions WHERE status='open' AND mode='live'")
    s = get_settings()
    return {
        "kill_switch": await is_kill_switch_active(),
        "users": users, "funded": funded, "live": live,
        "open_positions": {"paper": open_paper, "live": open_live},
        "guards": {
            "ENABLE_LIVE_TRADING": s.ENABLE_LIVE_TRADING,
            "EXECUTION_PATH_VALIDATED": s.EXECUTION_PATH_VALIDATED,
            "CAPITAL_MODE_CONFIRMED": s.CAPITAL_MODE_CONFIRMED,
            "AUTO_REDEEM_ENABLED": s.AUTO_REDEEM_ENABLED,
        },
    }


@router.get("/live-gate")
async def live_gate_status(authorization: str | None = Header(default=None)):
    """Report real-time status of all five live-trading activation gates.

    Returns a machine-readable and human-readable summary of whether each gate
    is open or locked, which makes operator validation and CI monitoring
    straightforward. All five must be True before any Tier 4 user can route a
    real order to the Polymarket CLOB.
    """
    token = authorization.removeprefix("Bearer ").strip() if authorization else None
    _check(token)
    s = get_settings()
    pool = get_pool()
    async with pool.acquire() as conn:
        tier4_count = int(await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE access_tier >= 4"
        ))
        live_mode_count = int(await conn.fetchval(
            "SELECT COUNT(*) FROM user_settings WHERE trading_mode = 'live'"
        ))
        live_mode_tier4_count = int(await conn.fetchval(
            "SELECT COUNT(*) FROM users u "
            "JOIN user_settings s ON s.user_id = u.id "
            "WHERE u.access_tier >= 4 AND s.trading_mode = 'live'"
        ))
        open_live = int(await conn.fetchval(
            "SELECT COUNT(*) FROM positions WHERE status='open' AND mode='live'"
        ))
        open_paper = int(await conn.fetchval(
            "SELECT COUNT(*) FROM positions WHERE status='open' AND mode='paper'"
        ))

    gates = {
        "ENABLE_LIVE_TRADING": s.ENABLE_LIVE_TRADING,
        "EXECUTION_PATH_VALIDATED": s.EXECUTION_PATH_VALIDATED,
        "CAPITAL_MODE_CONFIRMED": s.CAPITAL_MODE_CONFIRMED,
        "tier4_users_exist": tier4_count > 0,
        "live_mode_tier4_users_exist": live_mode_tier4_count > 0,
    }
    operator_guards_open = (
        s.ENABLE_LIVE_TRADING
        and s.EXECUTION_PATH_VALIDATED
        and s.CAPITAL_MODE_CONFIRMED
    )
    # Fetch the last 5 live_gate_opened audit events so callers can verify
    # when the operator guards were last confirmed enabled at startup.
    async with pool.acquire() as conn:
        audit_rows = await conn.fetch(
            "SELECT ts, payload FROM audit.log "
            "WHERE action = 'live_gate_opened' "
            "ORDER BY ts DESC LIMIT 5"
        )
    activation_history = [
        {"activated_at": str(r["ts"]), "payload": r["payload"]}
        for r in audit_rows
    ]

    return {
        "operator_guards_open": operator_guards_open,
        "live_routing_possible": operator_guards_open and live_mode_tier4_count > 0,
        "gates": gates,
        "users": {
            "tier4_total": tier4_count,
            "live_mode_total": live_mode_count,
            "tier4_and_live_mode": live_mode_tier4_count,
        },
        "positions": {
            "open_live": open_live,
            "open_paper": open_paper,
        },
        "activation_history": activation_history,
        "summary": (
            "✅ operator guards OPEN — Tier 4 users who set live mode will trade live"
            if operator_guards_open
            else "🔒 operator guards LOCKED — all trades route to paper regardless of user mode"
        ),
    }


@router.post("/kill")
async def kill(active: bool, reason: str | None = None,
               authorization: str | None = Header(default=None)):
    token = authorization.removeprefix("Bearer ").strip() if authorization else None
    _check(token)
    await set_kill_switch(active, reason, changed_by=None)
    return {"kill_switch": await is_kill_switch_active()}


@router.post("/force-redeem")
async def force_redeem(authorization: str | None = Header(default=None)):
    token = authorization.removeprefix("Bearer ").strip() if authorization else None
    _check(token)
    await scheduler.redeem_hourly()
    return {"ok": True}


@router.post("/sentry-test")
async def sentry_test(authorization: str | None = Header(default=None)):
    """Fire a synthetic Sentry event to verify production wiring.

    Returns ``{"ok": True, "event_id": "<id>"}`` when the SDK is initialised
    and capture succeeded; ``{"ok": False, ...}`` (200) otherwise so the
    operator runbook can distinguish "DSN not set" from "endpoint forbidden".
    Bearer-protected: same gate as the other ``/admin`` routes.
    """
    token = authorization.removeprefix("Bearer ").strip() if authorization else None
    _check(token)
    if not monitoring_sentry.is_initialised():
        return {
            "ok": False,
            "reason": "sentry_not_initialised",
            "hint": "set SENTRY_DSN as a Fly.io secret and redeploy",
        }
    event_id = monitoring_sentry.capture_test_event(
        "CrusaderBot /admin/sentry-test verification event"
    )
    if not event_id:
        return {"ok": False, "reason": "capture_returned_none"}
    return {"ok": True, "event_id": event_id}
