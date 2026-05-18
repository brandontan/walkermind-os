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
            "✅ activation guards OPEN — live trading enabled"
            if operator_guards_open
            else "🔒 activation guards LOCKED — all trades route to paper"
        ),
    }


@router.post("/dry-run")
async def dry_run(request: dict, authorization: str | None = Header(default=None)):
    """Shadow-execute the full pipeline for a signal without submitting any order.

    Operator-only. Runs signal → risk gate → sizing and returns the decision
    that WOULD be made if execute() were called.  Fully read-only: no DB
    mutations, no idempotency key consumption, no CLOB submission.

    Required fields: user_id, market_id, side, proposed_size_usdc, price,
                     market_liquidity, strategy_type, risk_profile
    Optional fields: signal_ts (ISO-8601), telegram_user_id, access_tier,
                     auto_trade_on, paused, market_question, yes_token_id,
                     no_token_id, market_status, idempotency_key,
                     trading_mode, edge_bps, tp_pct, sl_pct
    """
    token = authorization.removeprefix("Bearer ").strip() if authorization else None
    _check(token)

    import uuid
    from decimal import Decimal
    from datetime import datetime, timezone
    from fastapi import HTTPException
    from ..services.trade_engine.engine import TradeEngine, TradeSignal, ExecutionDryRun

    # Enforce required fields explicitly — do not silently use defaults that
    # would produce a result based on arbitrary placeholder values.
    _REQUIRED = ("user_id", "market_id", "side", "proposed_size_usdc",
                 "price", "market_liquidity", "strategy_type", "risk_profile")
    missing = [k for k in _REQUIRED if k not in request or request[k] is None]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"dry-run missing required fields: {missing}",
        )

    # Optional signal_ts: accept ISO-8601 string so operators can replay
    # historical signals and exercise the staleness gate (step 9) correctly.
    _raw_ts = request.get("signal_ts")
    if _raw_ts is not None:
        try:
            _signal_ts: datetime | None = datetime.fromisoformat(str(_raw_ts))
            if _signal_ts.tzinfo is None:
                _signal_ts = _signal_ts.replace(tzinfo=timezone.utc)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"invalid signal_ts (expected ISO-8601): {exc}",
            ) from exc
    else:
        _signal_ts = datetime.now(timezone.utc)

    try:
        signal = TradeSignal(
            user_id=uuid.UUID(str(request["user_id"])),
            telegram_user_id=int(request.get("telegram_user_id", 0)),
            access_tier=int(request.get("access_tier", 2)),
            auto_trade_on=bool(request.get("auto_trade_on", True)),
            paused=bool(request.get("paused", False)),
            market_id=str(request["market_id"]),
            market_question=request.get("market_question"),
            yes_token_id=request.get("yes_token_id"),
            no_token_id=request.get("no_token_id"),
            side=str(request["side"]),
            proposed_size_usdc=Decimal(str(request["proposed_size_usdc"])),
            price=float(request["price"]),
            market_liquidity=float(request["market_liquidity"]),
            market_status=str(request.get("market_status", "active")),
            idempotency_key=str(request.get(
                "idempotency_key",
                f"dryrun-{uuid.uuid4()}",
            )),
            strategy_type=str(request["strategy_type"]),
            risk_profile=str(request["risk_profile"]),
            trading_mode=str(request.get("trading_mode", "paper")),
            signal_ts=_signal_ts,
            edge_bps=float(request["edge_bps"]) if "edge_bps" in request else None,
            tp_pct=float(request["tp_pct"]) if "tp_pct" in request else None,
            sl_pct=float(request["sl_pct"]) if "sl_pct" in request else None,
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=422, detail=f"invalid dry-run payload: {exc}",
        ) from exc

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
