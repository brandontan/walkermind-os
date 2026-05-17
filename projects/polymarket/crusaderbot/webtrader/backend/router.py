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
from ...domain.execution import router as exec_router
from ...domain.ops import kill_switch
from ... import notifications as notif_module
from . import sse as webtrader_sse
from .auth import authenticate_telegram, get_current_user
from .schemas import (
    AlertItem,
    AutoTradeState,
    AutoTradeToggleRequest,
    ChartPoint,
    ClosePositionResponse,
    CustomizeRequest,
    DashboardSummary,
    KillSwitchStatus,
    LeaderboardEntry,
    LedgerEntry,
    MarketFilterUpdate,
    OrderItem,
    PortfolioAnalytics,
    PortfolioSummary,
    PositionItem,
    PresetActivateRequest,
    RiskProfileRequest,
    StrategyPnl,
    TelegramAuthPayload,
    TokenResponse,
    TradeHighlight,
    TradingSettingsUpdate,
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
        # settled YES = pnl_usdc > 0 (win), settled NO = pnl_usdc <= 0 (loss).
        # Expired markets (exit_reason='market_expired') are excluded — expiry ≠ settled outcome.
        totals = await conn.fetchrow(
            """SELECT
                 COUNT(*) FILTER (WHERE exit_reason IS DISTINCT FROM 'market_expired') AS total,
                 COUNT(*) FILTER (WHERE pnl_usdc > 0 AND exit_reason IS DISTINCT FROM 'market_expired') AS wins,
                 COUNT(*) FILTER (WHERE pnl_usdc <= 0 AND exit_reason IS DISTINCT FROM 'market_expired') AS losses
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


@router.get("/orders")
async def get_orders(
    user: _CurrentUser,
    limit: int = 50,
    offset: int = 0,
) -> list[OrderItem]:
    pool = get_pool()
    user_id = user["user_id"]
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT o.id, o.market_id, m.question AS market_question,
                      o.side, o.size_usdc, o.price, o.status, o.mode,
                      o.strategy_type,
                      COALESCE(o.filled_amount, 0) AS filled_amount,
                      o.remaining_amount,
                      o.created_at
               FROM orders o
               LEFT JOIN markets m ON m.id = o.market_id
               WHERE o.user_id = $1::uuid
               ORDER BY o.created_at DESC
               LIMIT $2 OFFSET $3""",
            user_id, limit, offset,
        )
    return [
        OrderItem(
            id=str(r["id"]),
            market_id=r["market_id"],
            market_question=r["market_question"],
            side=r["side"],
            size_usdc=float(r["size_usdc"]),
            price=float(r["price"]),
            status=r["status"],
            mode=r["mode"],
            strategy_type=r["strategy_type"],
            filled_amount=float(r["filled_amount"] or 0),
            remaining_amount=float(r["remaining_amount"]) if r["remaining_amount"] is not None else None,
            created_at=r["created_at"],
        )
        for r in rows
    ]


@router.post("/positions/{position_id}/close", response_model=ClosePositionResponse)
async def close_position_endpoint(
    position_id: str,
    user: _CurrentUser,
) -> ClosePositionResponse:
    """Manually close an open position at current market price."""
    pool = get_pool()
    user_id = user["user_id"]

    async with pool.acquire() as conn:
        pos_row = await conn.fetchrow(
            """SELECT p.id, p.user_id, p.market_id, p.side, p.size_usdc,
                      p.entry_price, p.current_price, p.status, p.mode,
                      m.yes_token_id, m.no_token_id, m.question,
                      u.telegram_user_id
               FROM positions p
               LEFT JOIN markets m ON m.id = p.market_id
               LEFT JOIN users u ON u.id = p.user_id
               WHERE p.id = $1::uuid AND p.user_id = $2::uuid AND p.status = 'open'""",
            position_id, user_id,
        )

    if not pos_row:
        raise HTTPException(status_code=404, detail="open position not found")

    position = dict(pos_row)
    entry_price = float(position["entry_price"])
    exit_price = float(position["current_price"] or position["entry_price"])
    size_usdc = float(position["size_usdc"])
    estimated_fill = size_usdc * (exit_price / max(entry_price, 0.0001))

    try:
        result = await exec_router.close(
            position=position,
            exit_price=exit_price,
            exit_reason="manual",
        )
    except Exception as exc:
        log.error("manual close failed position=%s: %s", position_id, exc)
        raise HTTPException(status_code=500, detail=f"close failed: {exc}")

    pnl = float(result.get("pnl_usdc", 0))
    pnl_sign = "+" if pnl >= 0 else "−"
    tg_id = position.get("telegram_user_id")
    if tg_id:
        market_label = position.get("question") or position["market_id"][:30]
        try:
            await notif_module.send(
                int(tg_id),
                f"🔴 <b>Position Manually Closed</b>\n"
                f"Market: {market_label}\n"
                f"Exit: ${exit_price:.3f}\n"
                f"PnL: {pnl_sign}${abs(pnl):.2f}",
            )
        except Exception as exc:
            log.warning("manual close TG notify failed: %s", exc)

    return ClosePositionResponse(
        order_id=result.get("order_id"),
        estimated_fill=estimated_fill,
        status="closed",
    )


@router.get("/autotrade", response_model=AutoTradeState)
async def get_autotrade(user: _CurrentUser) -> AutoTradeState:
    pool = get_pool()
    user_id = user["user_id"]

    async with pool.acquire() as conn:
        u_row = await conn.fetchrow(
            "SELECT auto_trade_on FROM users WHERE id=$1::uuid", user_id
        )
        s_row = await conn.fetchrow(
            """SELECT risk_profile, capital_alloc_pct, tp_pct, sl_pct, active_preset,
                      category_filters, min_liquidity, max_resolution_days, min_volume_24h
               FROM user_settings WHERE user_id=$1::uuid""",
            user_id,
        )

    cats: list[str] = list(s_row["category_filters"]) if s_row and s_row["category_filters"] else []
    return AutoTradeState(
        auto_trade_on=bool(u_row["auto_trade_on"]) if u_row else False,
        active_preset=s_row["active_preset"] if s_row else None,
        risk_profile=s_row["risk_profile"] if s_row else "balanced",
        capital_alloc_pct=float(s_row["capital_alloc_pct"]) if s_row else 0.5,
        tp_pct=float(s_row["tp_pct"]) if s_row and s_row["tp_pct"] else 0.0,
        sl_pct=float(s_row["sl_pct"]) if s_row and s_row["sl_pct"] else 0.0,
        market_categories=cats,
        min_liquidity=float(s_row["min_liquidity"]) if s_row and s_row["min_liquidity"] is not None else 1000.0,
        max_resolution_days=int(s_row["max_resolution_days"]) if s_row and s_row["max_resolution_days"] is not None else None,
        min_volume_24h=float(s_row["min_volume_24h"]) if s_row and s_row["min_volume_24h"] is not None else 100.0,
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


# Preset key → default risk parameters applied when preset is activated.
# Risk profile (capital/TP/SL) can be overridden separately via /autotrade/risk-profile.
_PRESET_PARAMS: dict[str, dict[str, str | float]] = {
    # Legacy preset keys — kept for backward compatibility with existing users.
    "signal_sniper": {"risk_profile": "conservative", "capital_alloc_pct": 0.20, "tp_pct": 0.10, "sl_pct": 0.05},
    "full_auto":     {"risk_profile": "aggressive",   "capital_alloc_pct": 0.60, "tp_pct": 0.30, "sl_pct": 0.20},
    "value_hunter":  {"risk_profile": "balanced",     "capital_alloc_pct": 0.40, "tp_pct": 0.20, "sl_pct": 0.15},
    "whale_mirror":  {"risk_profile": "conservative", "capital_alloc_pct": 0.20, "tp_pct": 0.10, "sl_pct": 0.05},
    "hybrid":        {"risk_profile": "balanced",     "capital_alloc_pct": 0.40, "tp_pct": 0.15, "sl_pct": 0.10},
    # New preset keys mapped to lib/strategies/ classes.
    "trend_breakout": {"risk_profile": "balanced",     "capital_alloc_pct": 0.40, "tp_pct": 0.20, "sl_pct": 0.15},
    "contrarian":     {"risk_profile": "balanced",     "capital_alloc_pct": 0.40, "tp_pct": 0.15, "sl_pct": 0.10},
    "close_sweep":    {"risk_profile": "balanced",     "capital_alloc_pct": 0.30, "tp_pct": 0.15, "sl_pct": 0.08},
    "pair_arb":       {"risk_profile": "conservative", "capital_alloc_pct": 0.20, "tp_pct": 0.05, "sl_pct": 0.03},
    "ensemble":       {"risk_profile": "balanced",   "capital_alloc_pct": 0.40, "tp_pct": 0.20, "sl_pct": 0.12},
}

_VALID_RISK_PROFILES: frozenset[str] = frozenset({"conservative", "balanced", "aggressive", "custom"})

_RISK_PROFILE_DEFAULTS: dict[str, dict[str, float]] = {
    "conservative": {"capital_alloc_pct": 0.20, "tp_pct": 0.10, "sl_pct": 0.05},
    "balanced":     {"capital_alloc_pct": 0.40, "tp_pct": 0.20, "sl_pct": 0.15},
    "aggressive":   {"capital_alloc_pct": 0.60, "tp_pct": 0.30, "sl_pct": 0.20},
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


@router.patch("/autotrade/market-filters")
async def update_market_filters(body: MarketFilterUpdate, user: _CurrentUser):
    pool = get_pool()
    user_id = user["user_id"]
    updates: list[str] = []
    params: list = []

    # Use model_dump(exclude_unset=True) so fields explicitly set to null
    # (e.g. max_resolution_days=null meaning "Any") are included and correctly
    # propagated to the DB, while truly absent fields are skipped.
    data = body.model_dump(exclude_unset=True)
    for field, val in data.items():
        col = "category_filters" if field == "market_categories" else field
        params.append(val)
        updates.append(f"{col}=${len(params)}")

    if not updates:
        return {"updated": False}

    params.append(user_id)
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE user_settings SET {', '.join(updates)}, updated_at=NOW() WHERE user_id=${len(params)}::uuid",
            *params,
        )
    return {"updated": True}


@router.patch("/autotrade/risk-profile")
async def set_risk_profile(body: RiskProfileRequest, user: _CurrentUser):
    """Set user's risk profile independently of their strategy preset.

    For standard profiles (conservative/balanced/aggressive), pre-defined
    capital/TP/SL defaults are applied. For 'custom', the caller must supply
    all three parameters.

    Validation is enforced server-side so it cannot be bypassed via the WebTrader.
    """
    if body.profile not in _VALID_RISK_PROFILES:
        raise HTTPException(
            status_code=400,
            detail=f"invalid risk profile: {body.profile!r}. "
                   f"Must be one of {sorted(_VALID_RISK_PROFILES)}",
        )

    if body.profile == "custom":
        if body.capital_alloc_pct is None or body.tp_pct is None or body.sl_pct is None:
            raise HTTPException(
                status_code=422,
                detail="custom profile requires capital_alloc_pct, tp_pct, and sl_pct",
            )
        if body.capital_alloc_pct > 0.80:
            raise HTTPException(
                status_code=422,
                detail="capital_alloc_pct must not exceed 0.80 (80% hard ceiling)",
            )
        if body.tp_pct <= body.sl_pct:
            raise HTTPException(
                status_code=422,
                detail="tp_pct must be greater than sl_pct",
            )
        cap = body.capital_alloc_pct
        tp = body.tp_pct
        sl = body.sl_pct
    else:
        defaults = _RISK_PROFILE_DEFAULTS[body.profile]
        cap = float(body.capital_alloc_pct) if body.capital_alloc_pct is not None else defaults["capital_alloc_pct"]
        tp = float(body.tp_pct) if body.tp_pct is not None else defaults["tp_pct"]
        sl = float(body.sl_pct) if body.sl_pct is not None else defaults["sl_pct"]

    pool = get_pool()
    user_id = user["user_id"]
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE user_settings
                  SET risk_profile      = $1,
                      capital_alloc_pct = $2,
                      tp_pct            = $3,
                      sl_pct            = $4,
                      updated_at        = NOW()
               WHERE user_id = $5::uuid""",
            body.profile, cap, tp, sl, user_id,
        )
    return {"risk_profile": body.profile, "capital_alloc_pct": cap, "tp_pct": tp, "sl_pct": sl}


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
            """SELECT risk_profile, notifications_on, auto_redeem, auto_redeem_mode
               FROM user_settings WHERE user_id=$1::uuid""",
            user_id,
        )
    return {
        "risk_profile": row["risk_profile"] if row else "balanced",
        "notifications_on": bool(row["notifications_on"]) if row else True,
        "auto_redeem": bool(row["auto_redeem"]) if row and row["auto_redeem"] is not None else False,
        "redeem_mode": row["auto_redeem_mode"] if row and row["auto_redeem_mode"] else "hourly",
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


@router.patch("/config/trading")
async def update_trading_settings(body: TradingSettingsUpdate, user: _CurrentUser):
    pool = get_pool()
    user_id = user["user_id"]
    updates: list[str] = []
    params: list = []

    if body.auto_redeem is not None:
        params.append(body.auto_redeem)
        updates.append(f"auto_redeem=${len(params)}")

    if body.redeem_mode is not None:
        if body.redeem_mode not in ("instant", "hourly"):
            raise HTTPException(status_code=422, detail="redeem_mode must be 'instant' or 'hourly'")
        params.append(body.redeem_mode)
        updates.append(f"auto_redeem_mode=${len(params)}")

    if body.min_liquidity_usd is not None:
        if body.min_liquidity_usd < 0:
            raise HTTPException(status_code=422, detail="min_liquidity_usd must be >= 0")
        params.append(body.min_liquidity_usd)
        updates.append(f"min_liquidity=${len(params)}")

    if body.slippage_tolerance_pct is not None:
        if not (0.0 <= body.slippage_tolerance_pct <= 1.0):
            raise HTTPException(status_code=422, detail="slippage_tolerance_pct must be between 0 and 1")
        params.append(body.slippage_tolerance_pct)
        updates.append(f"slippage_tolerance_pct=${len(params)}")

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
    "7D":  timedelta(weeks=1),   # frontend alias for 1W
    "1M":  timedelta(days=30),
    "30D": timedelta(days=30),   # frontend alias for 1M
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


@router.get("/portfolio/analytics", response_model=PortfolioAnalytics)
async def get_portfolio_analytics(user: _CurrentUser) -> PortfolioAnalytics:
    pool = get_pool()
    user_id = user["user_id"]

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT p.pnl_usdc, p.opened_at, p.closed_at,
                      COALESCE(p.strategy_type, 'unknown') AS strategy_type,
                      COALESCE(m.question, p.market_id) AS market_question
               FROM positions p
               LEFT JOIN markets m ON m.id = p.market_id
               WHERE p.user_id = $1::uuid
                 AND p.status IN ('closed', 'expired')
                 AND p.pnl_usdc IS NOT NULL
               ORDER BY p.closed_at ASC""",
            user_id,
        )

    if not rows:
        return PortfolioAnalytics(
            has_data=False,
            max_drawdown_pct=None,
            profit_per_strategy=[],
            best_trade=None,
            worst_trade=None,
            win_loss_ratio=None,
            wins=0,
            losses=0,
            avg_hold_hours=None,
        )

    pnls = [float(r["pnl_usdc"]) for r in rows]

    # Max drawdown: peak-to-trough on cumulative equity curve.
    # When peak > 0: standard percentage drawdown against high watermark.
    # When peak == 0 (all-losses case): express as 100% — the curve never
    # recovered above the starting point, so the full loss is the drawdown.
    running = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        running += p
        if running > peak:
            peak = running
        if peak > 0:
            dd = (peak - running) / peak
        elif running < 0:
            dd = 1.0  # 100% drawdown from zero starting point
        else:
            dd = 0.0
        if dd > max_dd:
            max_dd = dd

    # Profit per strategy
    strat_pnl: dict[str, float] = {}
    for r in rows:
        s = r["strategy_type"]
        strat_pnl[s] = strat_pnl.get(s, 0.0) + float(r["pnl_usdc"])
    profit_per_strategy = [
        StrategyPnl(strategy=k, pnl_usdc=round(v, 2))
        for k, v in sorted(strat_pnl.items(), key=lambda x: -x[1])
    ]

    # Best / worst trade
    best_row = max(rows, key=lambda r: float(r["pnl_usdc"]))
    worst_row = min(rows, key=lambda r: float(r["pnl_usdc"]))

    # Win / loss
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p <= 0)
    win_loss_ratio = round(wins / losses, 2) if losses > 0 else None

    # Avg hold duration in hours
    durations = [
        (r["closed_at"] - r["opened_at"]).total_seconds() / 3600.0
        for r in rows
        if r["closed_at"] and r["opened_at"]
    ]
    avg_hold_hours = round(sum(durations) / len(durations), 1) if durations else None

    return PortfolioAnalytics(
        has_data=True,
        max_drawdown_pct=round(max_dd * 100, 2),
        profit_per_strategy=profit_per_strategy,
        best_trade=TradeHighlight(
            market_question=best_row["market_question"],
            pnl_usdc=round(float(best_row["pnl_usdc"]), 2),
        ),
        worst_trade=TradeHighlight(
            market_question=worst_row["market_question"],
            pnl_usdc=round(float(worst_row["pnl_usdc"]), 2),
        ),
        win_loss_ratio=win_loss_ratio,
        wins=wins,
        losses=losses,
        avg_hold_hours=avg_hold_hours,
    )


@router.get("/leaderboard", response_model=list[LeaderboardEntry])
async def get_leaderboard(user: _CurrentUser) -> list[LeaderboardEntry]:
    pool = get_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT wallet, alias, win_rate, total_pnl, volume_usdc, roi_pct, badge
               FROM leaderboard_stats
               ORDER BY total_pnl DESC
               LIMIT 50"""
        )

    return [
        LeaderboardEntry(
            rank=i + 1,
            wallet=r["wallet"],
            alias=r["alias"],
            win_rate=float(r["win_rate"]) if r["win_rate"] is not None else None,
            total_pnl=float(r["total_pnl"]) if r["total_pnl"] is not None else None,
            volume_usdc=float(r["volume_usdc"]) if r["volume_usdc"] is not None else None,
            roi_pct=float(r["roi_pct"]) if r["roi_pct"] is not None else None,
            badge=r["badge"],
        )
        for i, r in enumerate(rows)
    ]


# ── Copy Trade ────────────────────────────────────────────────────────────────

from typing import Literal as _Literal  # noqa: E402

from pydantic import BaseModel as _BaseModel  # noqa: E402

# Enum-constrained at the schema boundary so a malformed client payload
# (e.g. "buy_only", "manuall") is rejected with 422 before persistence —
# monitor logic branches on exact literals, so silent typos would change
# trading behaviour (sell filtering / manual-confirm bypass).
_CopyDirection = _Literal["buys_only", "buys_and_sells"]
_CopyType = _Literal["fixed", "percentage", "rm"]
_ExecutionMode = _Literal["auto", "manual"]
_TaskStatus = _Literal["active", "paused"]


class CopyTradeTaskCreate(_BaseModel):
    wallet_address: str
    nickname: Optional[str] = None
    copy_direction: _CopyDirection = "buys_only"
    copy_type: _CopyType = "fixed"
    amount: float = 10.0
    execution_mode: _ExecutionMode = "auto"
    slippage_pct: float = 0.05
    allow_topups: bool = True


class CopyTradeTaskPatch(_BaseModel):
    nickname: Optional[str] = None
    copy_direction: Optional[_CopyDirection] = None
    execution_mode: Optional[_ExecutionMode] = None
    allow_topups: Optional[bool] = None
    status: Optional[_TaskStatus] = None


@router.get("/copy-trade/tasks")
async def list_copy_trade_tasks(user: _CurrentUser):
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id::text, wallet_address,
                      COALESCE(nickname, task_name) AS nickname,
                      status,
                      COALESCE(copy_direction, 'buys_only') AS copy_direction,
                      copy_mode, copy_amount,
                      COALESCE(execution_mode, 'auto') AS execution_mode,
                      COALESCE(allow_topups, true) AS allow_topups,
                      created_at
               FROM copy_trade_tasks
               WHERE user_id = $1::uuid
               ORDER BY created_at ASC""",
            user["user_id"],
        )
    return [dict(r) for r in rows]


@router.post("/copy-trade/tasks", status_code=201)
async def create_copy_trade_task(body: CopyTradeTaskCreate, user: _CurrentUser):
    copy_mode = {"fixed": "fixed", "percentage": "proportional", "rm": "rm_mirror"}.get(
        body.copy_type, "fixed"
    )
    copy_amount = body.amount if body.copy_type == "fixed" else 10.0
    copy_pct = body.amount / 100.0 if body.copy_type != "fixed" else None
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO copy_trade_tasks
               (user_id, wallet_address, task_name, copy_mode, copy_amount, copy_pct,
                slippage_pct, status, nickname, copy_direction, execution_mode, allow_topups)
               VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, 'active', $8, $9, $10, $11)
               RETURNING id::text""",
            user["user_id"],
            body.wallet_address.lower(),
            body.nickname or body.wallet_address[:12],
            copy_mode,
            copy_amount,
            copy_pct,
            body.slippage_pct,
            body.nickname,
            body.copy_direction,
            body.execution_mode,
            body.allow_topups,
        )
    return {"id": row["id"], "status": "active"}


@router.patch("/copy-trade/tasks/{task_id}")
async def update_copy_trade_task(task_id: str, body: CopyTradeTaskPatch, user: _CurrentUser):
    fields: list[str] = []
    values: list = []
    if body.nickname is not None:
        fields.append(f"nickname = ${len(values)+3}")
        values.append(body.nickname)
    if body.copy_direction is not None:
        fields.append(f"copy_direction = ${len(values)+3}")
        values.append(body.copy_direction)
    if body.execution_mode is not None:
        fields.append(f"execution_mode = ${len(values)+3}")
        values.append(body.execution_mode)
    if body.allow_topups is not None:
        fields.append(f"allow_topups = ${len(values)+3}")
        values.append(body.allow_topups)
    if body.status is not None:
        if body.status not in ("active", "paused"):
            raise HTTPException(status_code=422, detail="status must be active or paused")
        fields.append(f"status = ${len(values)+3}")
        values.append(body.status)
    if not fields:
        raise HTTPException(status_code=422, detail="no fields to update")
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE copy_trade_tasks SET {', '.join(fields)}, updated_at=NOW() "
            f"WHERE id=$1::uuid AND user_id=$2::uuid",
            task_id, user["user_id"], *values,
        )
    return {"updated": True}


@router.delete("/copy-trade/tasks/{task_id}", status_code=204)
async def delete_copy_trade_task(task_id: str, user: _CurrentUser):
    pool = get_pool()
    async with pool.acquire() as conn:
        deleted = await conn.fetchval(
            "DELETE FROM copy_trade_tasks WHERE id=$1::uuid AND user_id=$2::uuid RETURNING 1",
            task_id, user["user_id"],
        )
    if not deleted:
        raise HTTPException(status_code=404, detail="task not found")


@router.get("/copy-trade/tasks/{task_id}/stats")
async def get_copy_trade_task_stats(task_id: str, user: _CurrentUser):
    pool = get_pool()
    async with pool.acquire() as conn:
        task = await conn.fetchrow(
            "SELECT wallet_address FROM copy_trade_tasks WHERE id=$1::uuid AND user_id=$2::uuid",
            task_id, user["user_id"],
        )
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    try:
        from ...services.copy_trade.wallet_stats import fetch_wallet_stats
        stats = await fetch_wallet_stats(task["wallet_address"])
        return {
            "pnl_30d": stats.pnl_30d,
            "win_rate": stats.win_rate,
            "total_predictions": stats.total_predictions,
            "biggest_win": stats.biggest_win,
        }
    except Exception as exc:
        log.warning("copy_trade_stats_fetch_failed wallet=%s error=%s", task["wallet_address"], exc)
        return {"error": "stats unavailable"}
