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
        # Paper trading is open to every user, so funded == total users.
        # Kept in the payload for backwards compatibility with existing
        # operator dashboards.
        funded = users
        live = await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE role = 'admin'")
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
    straightforward. All five must be True before any admin user can route a
    real order to the Polymarket CLOB.
    """
    token = authorization.removeprefix("Bearer ").strip() if authorization else None
    _check(token)
    s = get_settings()
    pool = get_pool()
    async with pool.acquire() as conn:
        tier4_count = int(await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE role = 'admin'"
        ))
        live_mode_count = int(await conn.fetchval(
            "SELECT COUNT(*) FROM user_settings WHERE trading_mode = 'live'"
        ))
        live_mode_tier4_count = int(await conn.fetchval(
            "SELECT COUNT(*) FROM users u "
            "JOIN user_settings s ON s.user_id = u.id "
            "WHERE u.role = 'admin' AND s.trading_mode = 'live'"
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
        "admin_users_exist": tier4_count > 0,
        "live_mode_admin_users_exist": live_mode_tier4_count > 0,
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
            "admin_total": tier4_count,
            "live_mode_total": live_mode_count,
            "admin_and_live_mode": live_mode_tier4_count,
        },
        "positions": {
            "open_live": open_live,
            "open_paper": open_paper,
        },
        "activation_history": activation_history,
        "summary": (
            "✅ activation guards OPEN — live trading enabled"
            if operator_guards_open
            else "🔒 activation guards LOCKED — all trades route to paper"
        ),
    }


@router.post("/dry-run")
async def dry_run(request: dict, authorization: str | None = Header(default=None)):
    """Shadow-execute the full pipeline for a signal without submitting any order.

    Operator-only. Runs signal → risk gate → sizing and returns the decision
    that WOULD be made if execute() were called, with no DB mutations and
    no CLOB submission.  Use to validate that paper and live paths produce
    identical decisions for the same input.

    Request body keys (all required):
      user_id, market_id, side, proposed_size_usdc, price,
      market_liquidity, strategy_type, risk_profile
    """
    token = authorization.removeprefix("Bearer ").strip() if authorization else None
    _check(token)

    import uuid
    from decimal import Decimal
    from datetime import datetime, timezone
    from ..services.trade_engine.engine import TradeEngine, TradeSignal, ExecutionDryRun

    try:
        signal = TradeSignal(
            user_id=uuid.UUID(str(request.get("user_id", ""))),
            telegram_user_id=int(request.get("telegram_user_id", 0)),
            role=str(request.get("role", "user")),
            auto_trade_on=bool(request.get("auto_trade_on", True)),
            paused=bool(request.get("paused", False)),
            market_id=str(request.get("market_id", "")),
            market_question=request.get("market_question"),
            yes_token_id=request.get("yes_token_id"),
            no_token_id=request.get("no_token_id"),
            side=str(request.get("side", "yes")),
            proposed_size_usdc=Decimal(str(request.get("proposed_size_usdc", "10"))),
            price=float(request.get("price", 0.5)),
            market_liquidity=float(request.get("market_liquidity", 10000.0)),
            market_status=str(request.get("market_status", "active")),
            idempotency_key=str(request.get(
                "idempotency_key",
                f"dryrun-{uuid.uuid4()}",
            )),
            strategy_type=str(request.get("strategy_type", "signal")),
            risk_profile=str(request.get("risk_profile", "balanced")),
            trading_mode=str(request.get("trading_mode", "paper")),
            signal_ts=datetime.now(timezone.utc),
        )
    except Exception as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=f"invalid dry-run payload: {exc}") from exc

    result: ExecutionDryRun = await TradeEngine().dry_run_execute(signal)
    return {
        "market_id": result.market_id,
        "side": result.side,
        "size_usdc": str(result.size_usdc) if result.size_usdc is not None else None,
        "entry_price": result.entry_price,
        "risk_decision": result.risk_decision,
        "would_be_rejected": result.would_be_rejected,
        "rejection_reason": result.rejection_reason,
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


@router.get("/scan/last")
async def scan_last(authorization: str | None = Header(default=None)):
    """Return the most recent scan_runs row as JSON.

    Provides a complete observability snapshot of the last scan tick:
    markets seen, strategies loaded, candidates emitted, risk gate decisions,
    paper executions, and per-bucket skip/zero/rejection breakdowns.
    """
    token = authorization.removeprefix("Bearer ").strip() if authorization else None
    _check(token)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, started_at, finished_at,
                   users_evaluated, markets_seen, markets_eligible,
                   strategies_loaded, candidates_emitted,
                   risk_approved, risk_rejected,
                   paper_orders_created, positions_created, snapshots_written,
                   skip_breakdown, zero_reason_breakdown, rejection_breakdown,
                   mode, live_trading
            FROM scan_runs
            ORDER BY started_at DESC
            LIMIT 1
            """
        )
    if row is None:
        return {"scan_run": None, "note": "no scan runs recorded yet"}
    r = dict(row)
    return {
        "scan_run_id": str(r["id"]),
        "started_at": r["started_at"].isoformat() if r["started_at"] else None,
        "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None,
        "users_evaluated": r["users_evaluated"],
        "markets_seen": r["markets_seen"],
        "markets_eligible": r["markets_eligible"],
        "strategies_loaded": r["strategies_loaded"],
        "candidates_emitted": r["candidates_emitted"],
        "risk_approved": r["risk_approved"],
        "risk_rejected": r["risk_rejected"],
        "paper_orders_created": r["paper_orders_created"],
        "positions_created": r["positions_created"],
        "snapshots_written": r["snapshots_written"],
        "skip_breakdown": r["skip_breakdown"] or {},
        "zero_reason_breakdown": r["zero_reason_breakdown"] or {},
        "rejection_breakdown": r["rejection_breakdown"] or {},
        "mode": r["mode"],
        "live_trading": r["live_trading"],
    }


@router.get("/scan/list")
async def scan_list(
    limit: int = 20,
    authorization: str | None = Header(default=None),
):
    """Return the last N scan_runs rows as a list (timestamps + headline counts).

    Useful for spotting trends across scan ticks: are candidates emitting?
    Is the risk gate always rejecting? Are paper orders being created?
    """
    token = authorization.removeprefix("Bearer ").strip() if authorization else None
    _check(token)
    limit = max(1, min(limit, 100))
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, started_at, finished_at,
                   users_evaluated, markets_seen, strategies_loaded,
                   candidates_emitted, risk_approved, risk_rejected,
                   paper_orders_created, mode, live_trading
            FROM scan_runs
            ORDER BY started_at DESC
            LIMIT $1
            """,
            limit,
        )
    return {
        "count": len(rows),
        "scan_runs": [
            {
                "scan_run_id": str(r["id"]),
                "started_at": r["started_at"].isoformat() if r["started_at"] else None,
                "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None,
                "users_evaluated": r["users_evaluated"],
                "markets_seen": r["markets_seen"],
                "strategies_loaded": r["strategies_loaded"],
                "candidates_emitted": r["candidates_emitted"],
                "risk_approved": r["risk_approved"],
                "risk_rejected": r["risk_rejected"],
                "paper_orders_created": r["paper_orders_created"],
                "mode": r["mode"],
                "live_trading": r["live_trading"],
            }
            for r in rows
        ],
    }


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
