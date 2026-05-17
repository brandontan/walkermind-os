"""WebTrader API router — mounted at /api/web in main.py."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from ...database import get_pool
from ...domain.ops import kill_switch
from . import sse as webtrader_sse
from .auth import authenticate_telegram, get_current_user
from .schemas import (
    AlertItem,
    AutoTradeState,
    AutoTradeToggleRequest,
    ChartPoint,
    CustomizeRequest,
    DashboardSummary,
    KillSwitchStatus,
    LedgerEntry,
    PortfolioSummary,
    PositionItem,
    PresetActivateRequest,
    TelegramAuthPayload,
    TokenResponse,
    UserSettingsUpdate,
    WalletInfo,
)

log = logging.getLogger(__name__)
router = APIRouter()

_CurrentUser = Annotated[dict, Depends(get_current_user)]


@router.get("/health")
async def web_health():
    return {"ok": True}


@router.post("/auth/telegram", response_model=TokenResponse)
async def auth_telegram(data: TelegramAuthPayload) -> TokenResponse:
    return await authenticate_telegram(data)


@router.get("/me")
async def get_me(user: _CurrentUser):
    return {"user_id": user["user_id"], "first_name": user["first_name"]}


@router.get("/dashboard", response_model=DashboardSummary)
async def get_dashboard(user: _CurrentUser) -> DashboardSummary:
    pool = get_pool()
    user_id = user["user_id"]

    async with pool.acquire() as conn:
        u_row = await conn.fetchrow(
            "SELECT auto_trade_on FROM users WHERE id = $1::uuid", user_id
        )
        settings_row = await conn.fetchrow(
            """SELECT risk_profile, capital_alloc_pct, tp_pct, sl_pct,
                      active_preset, trading_mode
               FROM user_settings WHERE user_id = $1::uuid""",
            user_id,
        )
        wallet_row = await conn.fetchrow(
            "SELECT balance_usdc FROM wallets WHERE user_id = $1::uuid", user_id
        )
        open_count = await conn.fetchval(
            "SELECT COUNT(*) FROM positions WHERE user_id=$1::uuid AND status='open'",
            user_id,
        )
        pnl_today = await conn.fetchval(
            """SELECT COALESCE(SUM(pnl_usdc),0) FROM positions
               WHERE user_id=$1::uuid AND status='closed'
                 AND closed_at >= NOW() - INTERVAL '24 hours'""",
            user_id,
        )
        pnl_7d = await conn.fetchval(
            """SELECT COALESCE(SUM(pnl_usdc),0) FROM positions
               WHERE user_id=$1::uuid AND status='closed'
                 AND closed_at >= NOW() - INTERVAL '7 days'""",
            user_id,
        )
        totals = await conn.fetchrow(
            """SELECT COUNT(*) AS total,
                      COUNT(*) FILTER (WHERE pnl_usdc > 0) AS wins,
                      COUNT(*) FILTER (WHERE pnl_usdc <= 0) AS losses
               FROM positions WHERE user_id=$1::uuid AND status='closed'""",
            user_id,
        )
        ks_active = await kill_switch.is_active()

    balance = float(wallet_row["balance_usdc"]) if wallet_row else 0.0
    trading_mode = settings_row["trading_mode"] if settings_row else "paper"

    return DashboardSummary(
        balance_usdc=balance,
        equity_usdc=balance,
        pnl_today=float(pnl_today or 0),
        pnl_7d=float(pnl_7d or 0),
        open_positions=int(open_count or 0),
        total_trades=int(totals["total"] or 0),
        wins=int(totals["wins"] or 0),
        losses=int(totals["losses"] or 0),
        auto_trade_on=bool(u_row["auto_trade_on"]) if u_row else False,
        kill_switch_active=ks_active,
        trading_mode=trading_mode,
        active_preset=settings_row["active_preset"] if settings_row else None,
    )


@router.get("/positions")
async def get_positions(
    user: _CurrentUser,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[PositionItem]:
    pool = get_pool()
    user_id = user["user_id"]
    where = "WHERE p.user_id = $1::uuid"
    params: list = [user_id]
    if status:
        where += f" AND p.status = ${len(params)+1}"
        params.append(status)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""SELECT p.id, p.market_id, m.question AS market_question,
                       p.side, p.size_usdc, p.entry_price, p.current_price,
                       p.pnl_usdc, p.status, p.mode, p.opened_at, p.closed_at,
                       p.exit_reason
                FROM positions p
                LEFT JOIN markets m ON m.id = p.market_id
                {where}
                ORDER BY p.opened_at DESC
                LIMIT ${len(params)+1} OFFSET ${len(params)+2}""",
            *params, limit, offset,
        )

    return [
        PositionItem(
            id=str(r["id"]),
            market_id=r["market_id"],
            market_question=r["market_question"],
            side=r["side"],
            size_usdc=float(r["size_usdc"]),
            entry_price=float(r["entry_price"]),
            current_price=float(r["current_price"]) if r["current_price"] else None,
            pnl_usdc=float(r["pnl_usdc"]) if r["pnl_usdc"] else None,
            status=r["status"],
            mode=r["mode"],
            opened_at=r["opened_at"],
            closed_at=r["closed_at"],
            exit_reason=r["exit_reason"],
        )
        for r in rows
    ]


@router.get("/autotrade", response_model=AutoTradeState)
async def get_autotrade(user: _CurrentUser) -> AutoTradeState:
    pool = get_pool()
    user_id = user["user_id"]

    async with pool.acquire() as conn:
        u_row = await conn.fetchrow(
            "SELECT auto_trade_on FROM users WHERE id=$1::uuid", user_id
        )
        s_row = await conn.fetchrow(
            """SELECT risk_profile, capital_alloc_pct, tp_pct, sl_pct, active_preset
               FROM user_settings WHERE user_id=$1::uuid""",
            user_id,
        )

    return AutoTradeState(
        auto_trade_on=bool(u_row["auto_trade_on"]) if u_row else False,
        active_preset=s_row["active_preset"] if s_row else None,
        risk_profile=s_row["risk_profile"] if s_row else "balanced",
        capital_alloc_pct=float(s_row["capital_alloc_pct"]) if s_row else 0.5,
        tp_pct=float(s_row["tp_pct"]) if s_row and s_row["tp_pct"] else 0.0,
        sl_pct=float(s_row["sl_pct"]) if s_row and s_row["sl_pct"] else 0.0,
    )


@router.post("/autotrade/toggle")
async def toggle_autotrade(body: AutoTradeToggleRequest, user: _CurrentUser):
    if body.enabled and await kill_switch.is_active():
        raise HTTPException(status_code=409, detail="kill switch is active — resume trading first")

    pool = get_pool()
    user_id = user["user_id"]
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET auto_trade_on=$1 WHERE id=$2::uuid",
            body.enabled, user_id,
        )
    return {"auto_trade_on": body.enabled}


_PRESET_PARAMS: dict[str, dict[str, str | float]] = {
    "signal_sniper": {"risk_profile": "conservative", "capital_alloc_pct": 0.20, "tp_pct": 0.10, "sl_pct": 0.05},
    "full_auto":     {"risk_profile": "balanced",   "capital_alloc_pct": 0.40, "tp_pct": 0.20, "sl_pct": 0.15},
    "value_hunter":  {"risk_profile": "aggressive", "capital_alloc_pct": 0.60, "tp_pct": 0.30, "sl_pct": 0.20},
    "whale_mirror":  {"risk_profile": "balanced",   "capital_alloc_pct": 0.50, "tp_pct": 0.20, "sl_pct": 0.10},
    "hybrid":        {"risk_profile": "balanced",   "capital_alloc_pct": 0.60, "tp_pct": 0.15, "sl_pct": 0.10},
}


@router.post("/autotrade/preset")
async def activate_preset(body: PresetActivateRequest, user: _CurrentUser):
    if body.preset_key not in _PRESET_PARAMS:
        raise HTTPException(status_code=400, detail=f"invalid preset key: {body.preset_key}")
    pool = get_pool()
    user_id = user["user_id"]
    params = _PRESET_PARAMS[body.preset_key]
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE user_settings
                  SET active_preset       = $1,
                      risk_profile        = COALESCE($2, risk_profile),
                      capital_alloc_pct   = COALESCE($3, capital_alloc_pct),
                      tp_pct              = COALESCE($4, tp_pct),
                      sl_pct              = COALESCE($5, sl_pct),
                      updated_at          = NOW()
               WHERE user_id = $6::uuid""",
            body.preset_key,
            params.get("risk_profile"),
            params.get("capital_alloc_pct"),
            params.get("tp_pct"),
            params.get("sl_pct"),
            user_id,
        )
    return {"active_preset": body.preset_key}


@router.post("/autotrade/customize")
async def customize_strategy(body: CustomizeRequest, user: _CurrentUser):
    pool = get_pool()
    user_id = user["user_id"]
    updates: list[str] = []
    params: list = []

    def _add(col: str, val):
        if val is not None:
            params.append(val)
            updates.append(f"{col}=${len(params)}")

    _add("tp_pct", body.tp_pct)
    _add("sl_pct", body.sl_pct)
    _add("capital_alloc_pct", body.capital_alloc_pct)
    _add("max_position_pct", body.max_position_pct)
    _add("auto_redeem_mode", body.auto_redeem_mode)
    _add("category_filters", body.category_filters)

    if not updates:
        return {"updated": False}

    params.append(user_id)
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE user_settings SET {', '.join(updates)}, updated_at=NOW() WHERE user_id=${len(params)}::uuid",
            *params,
        )
    return {"updated": True}


@router.get("/wallet", response_model=WalletInfo)
async def get_wallet(user: _CurrentUser) -> WalletInfo:
    pool = get_pool()
    user_id = user["user_id"]

    async with pool.acquire() as conn:
        w_row = await conn.fetchrow(
            "SELECT deposit_address, balance_usdc FROM wallets WHERE user_id=$1::uuid",
            user_id,
        )
        ledger_rows = await conn.fetch(
            """SELECT type, amount_usdc, note, created_at FROM ledger
               WHERE user_id=$1::uuid ORDER BY created_at DESC LIMIT 20""",
            user_id,
        )

    if not w_row:
        raise HTTPException(status_code=404, detail="wallet not found")

    return WalletInfo(
        deposit_address=w_row["deposit_address"],
        balance_usdc=float(w_row["balance_usdc"]),
        ledger_recent=[
            LedgerEntry(
                type=r["type"],
                amount_usdc=float(r["amount_usdc"]),
                note=r["note"],
                created_at=r["created_at"],
            )
            for r in ledger_rows
        ],
    )


@router.get("/settings")
async def get_settings_endpoint(user: _CurrentUser):
    pool = get_pool()
    user_id = user["user_id"]
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT risk_profile, notifications_on FROM user_settings WHERE user_id=$1::uuid",
            user_id,
        )
    return {
        "risk_profile": row["risk_profile"] if row else "balanced",
        "notifications_on": bool(row["notifications_on"]) if row else True,
    }


@router.patch("/settings")
async def update_settings(body: UserSettingsUpdate, user: _CurrentUser):
    pool = get_pool()
    user_id = user["user_id"]
    updates: list[str] = []
    params: list = []

    if body.risk_profile is not None:
        params.append(body.risk_profile)
        updates.append(f"risk_profile=${len(params)}")

    if body.notifications_on is not None:
        params.append(body.notifications_on)
        updates.append(f"notifications_on=${len(params)}")

    if not updates:
        return {"updated": False}

    params.append(user_id)
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE user_settings SET {', '.join(updates)}, updated_at=NOW() WHERE user_id=${len(params)}::uuid",
            *params,
        )
    return {"updated": True}


@router.get("/alerts")
async def get_alerts() -> list[AlertItem]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, severity, title, body, created_at
               FROM system_alerts
               WHERE dismissed=FALSE
                 AND (expires_at IS NULL OR expires_at > NOW())
               ORDER BY created_at DESC
               LIMIT 20""",
        )
    return [
        AlertItem(
            id=str(r["id"]),
            severity=r["severity"],
            title=r["title"],
            body=r["body"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


@router.get("/killswitch", response_model=KillSwitchStatus)
async def get_killswitch(user: _CurrentUser) -> KillSwitchStatus:
    return KillSwitchStatus(active=await kill_switch.is_active())


@router.post("/kill")
async def web_kill(user: _CurrentUser):
    try:
        await kill_switch.set_active(
            action="pause",
            actor_id=None,
            reason=f"webtrader kill — user {user['user_id']}",
        )
    except Exception as exc:
        log.error("web kill switch failed: %s", exc)
        raise HTTPException(status_code=500, detail="kill switch failed")
    return {"ok": True, "kill_switch_active": True}


@router.get("/portfolio/summary", response_model=PortfolioSummary)
async def get_portfolio_summary(user: _CurrentUser) -> PortfolioSummary:
    pool = get_pool()
    user_id = user["user_id"]

    async with pool.acquire() as conn:
        balance_row = await conn.fetchrow(
            "SELECT balance_usdc FROM wallets WHERE user_id=$1::uuid", user_id
        )
        realized_pnl = float(
            await conn.fetchval(
                "SELECT COALESCE(SUM(pnl_usdc), 0) FROM positions WHERE user_id=$1::uuid AND status IN ('closed', 'expired')",
                user_id,
            ) or 0
        )
        open_rows = await conn.fetch(
            "SELECT size_usdc, entry_price, current_price FROM positions WHERE user_id=$1::uuid AND status='open'",
            user_id,
        )

    balance = float(balance_row["balance_usdc"]) if balance_row else 0.0
    unrealized_pnl = _unrealized_pnl(open_rows)
    deployed = sum(float(r["size_usdc"]) for r in open_rows)
    equity = balance + deployed + unrealized_pnl

    return PortfolioSummary(
        available_usdc=balance,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        equity_usdc=equity,
        balance_usdc=balance,
    )


def _unrealized_pnl(open_rows: list) -> float:
    total = 0.0
    for r in open_rows:
        ep = float(r["entry_price"])
        if ep <= 0:
            continue
        cp = float(r["current_price"] if r["current_price"] is not None else r["entry_price"])
        total += (cp / ep - 1) * float(r["size_usdc"])
    return total


_CHART_LOOKBACK: dict[str, timedelta | None] = {
    "1D":  timedelta(days=1),
    "1W":  timedelta(weeks=1),
    "1M":  timedelta(days=30),
    "1Y":  timedelta(days=365),
    "ALL": None,
}


@router.get("/portfolio/chart")
async def get_portfolio_chart(
    user: _CurrentUser,
    period: str = "1W",
) -> list[ChartPoint]:
    pool = get_pool()
    user_id = user["user_id"]
    now = datetime.now(timezone.utc)
    lookback = _CHART_LOOKBACK.get(period.upper(), _CHART_LOOKBACK["1W"])
    since = now - lookback if lookback else None

    async with pool.acquire() as conn:
        balance_row = await conn.fetchrow(
            "SELECT balance_usdc FROM wallets WHERE user_id=$1::uuid", user_id
        )
        where_period = "WHERE user_id=$1::uuid AND status IN ('closed', 'expired')"
        params_period: list = [user_id]
        if since:
            params_period.append(since)
            where_period += f" AND closed_at >= ${len(params_period)}"
        period_rows = await conn.fetch(
            f"SELECT closed_at, pnl_usdc FROM positions {where_period} ORDER BY closed_at ASC",
            *params_period,
        )
        open_rows = await conn.fetch(
            "SELECT size_usdc, entry_price, current_price FROM positions WHERE user_id=$1::uuid AND status='open'",
            user_id,
        )

    if not period_rows:
        return []

    balance = float(balance_row["balance_usdc"]) if balance_row else 0.0
    period_pnl_sum = sum(float(r["pnl_usdc"] or 0) for r in period_rows)
    unrealized = _unrealized_pnl(open_rows)
    deployed = sum(float(r["size_usdc"]) for r in open_rows)

    equity_at_start = balance - period_pnl_sum
    start_ts = since if since else period_rows[0]["closed_at"]
    points: list[ChartPoint] = [
        ChartPoint(ts=start_ts.isoformat(), equity=round(equity_at_start, 2))
    ]
    running = equity_at_start
    for row in period_rows:
        running += float(row["pnl_usdc"] or 0)
        points.append(ChartPoint(ts=row["closed_at"].isoformat(), equity=round(running, 2)))

    points.append(ChartPoint(ts=now.isoformat(), equity=round(balance + deployed + unrealized, 2)))
    return points


@router.get("/stream")
async def sse_stream(user: _CurrentUser):
    telegram_id: int | None = user.get("telegram_id")
    return EventSourceResponse(
        webtrader_sse.stream_for_user(user["user_id"], telegram_id)
    )
