"""WebTrader API router — mounted at /api/web in main.py."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from uuid import UUID

from ...database import get_pool
from ... import audit
from ...api.per_user_rate_limit import per_ip_rate_limit, per_user_rate_limit
from ...domain.execution import router as exec_router
from ...domain.ops import kill_switch
from ...domain.positions import mark_force_close_intent_for_user
from ...domain.strategy.strategies.late_entry_v3 import (
    resolve_per_trade_ceiling,
    suggested_trade_size,
)
from ... import notifications as notif_module
from ...integrations import polymarket as _polymarket
from . import sse as webtrader_sse
from .auth import (
    authenticate_telegram, decode_stream_token, get_current_user, link_email,
    login_email, mint_stream_token, register_email,
)
from . import notification_prefs as _notif_prefs
from .schemas import (
    AdminUserDetail,
    AdminUserUpdate,
    AlertItem,
    AutoTradeState,
    AutoTradeToggleRequest,
    ChartPoint,
    ClosePositionResponse,
    CustomizeRequest,
    EmergencyStopResponse,
    DashboardSummary,
    KillSwitchStatus,
    LeaderboardEntry,
    LedgerEntry,
    LedgerPage,
    LiveEnableRequest,
    LiveEnableResponse,
    LiveStatus,
    MarketFeedItem,
    MarketFilterUpdate,
    OrderItem,
    PortfolioAnalytics,
    PortfolioSummary,
    PositionItem,
    PresetActivateRequest,
    RiskProfileRequest,
    RuntimeStatus,
    StrategyPnl,
    StrategyToggleRequest,
    EmailLoginRequest,
    EmailRegisterRequest,
    LinkEmailRequest,
    TelegramAuthPayload,
    TokenResponse,
    TradeHighlight,
    TradingSettingsUpdate,
    UserSettingsUpdate,
    WalletInfo,
    WithdrawRequest,
    WithdrawResponse,
)

log = logging.getLogger(__name__)
router = APIRouter()

_CurrentUser = Annotated[dict, Depends(get_current_user)]


@router.get("/health")
async def web_health():
    return {"ok": True}


@router.get("/markets")
async def get_markets_list(
    category: str | None = None,
    q: str | None = None,
    limit: int = 50,
):
    """Proxy Polymarket Gamma — Discover Markets search + category filter.

    Uses the events-with-markets endpoint so each row carries a usable
    ``category`` string (built from event tag labels). Filtering happens
    server-side here:
      * ``category`` — case-insensitive substring match against the tag
        labels string Gamma returns per event.
      * ``q`` — case-insensitive substring match against the market
        question. Both filters compose (AND).
    """
    cap = min(limit, 200)
    try:
        # Fetch a wider page than the cap so client filters still find ~cap rows.
        raw = await _polymarket.get_events_with_markets(limit=max(cap * 4, 200))
        cat_needle = category.strip().lower() if category else ""
        q_needle = q.strip().lower() if q else ""
        out: list[dict] = []
        for m in raw:
            row_cat = str(m.get("category") or "").lower()
            row_q = str(m.get("question") or "").lower()
            if cat_needle and cat_needle not in row_cat:
                continue
            if q_needle and q_needle not in row_q:
                continue
            out.append(m)
            if len(out) >= cap:
                break
        return out
    except Exception as exc:
        log.warning("get_markets_list failed: %s", exc)
        return []


@router.post("/auth/telegram", response_model=TokenResponse)
async def auth_telegram(data: TelegramAuthPayload) -> TokenResponse:
    return await authenticate_telegram(data)


@router.post(
    "/auth/register",
    response_model=TokenResponse,
    dependencies=[Depends(per_ip_rate_limit("auth_register", limit=5))],
)
async def auth_register(data: EmailRegisterRequest) -> TokenResponse:
    """Register a new account with email + password (no Telegram required)."""
    return await register_email(data)


@router.post(
    "/auth/login",
    response_model=TokenResponse,
    dependencies=[Depends(per_ip_rate_limit("auth_login", limit=10))],
)
async def auth_login(data: EmailLoginRequest) -> TokenResponse:
    """Authenticate with email + password."""
    return await login_email(data)


@router.post("/auth/link-email")
async def auth_link_email(
    data: LinkEmailRequest,
    user: dict = Depends(get_current_user),
) -> dict:
    """Link an email + password to an existing Telegram account."""
    return await link_email(user["user_id"], data)


@router.get("/me")
async def get_me(user: _CurrentUser):
    """Current account identity for the Settings page. Includes persisted
    email/telegram link state so the UI renders "connected" rows instead of
    re-showing the link forms after a refresh."""
    user_id = user["user_id"]
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT email, username, telegram_user_id, role FROM users WHERE id = $1::uuid",
            user_id,
        )
        # trading_mode is the canonical per-user mode in user_settings; surface
        # it here so the app-wide TopBar pill shows LIVE/PAPER on every page
        # without each page making its own mode call.
        settings_row = await conn.fetchrow(
            "SELECT trading_mode FROM user_settings WHERE user_id = $1::uuid",
            user_id,
        )
    email = row["email"] if row else None
    # Synthetic tombstone emails (merged-<uuid>@telegram.local) are not real
    # user logins — never surface them as a "linked email".
    if email and email.endswith("@telegram.local"):
        email = None
    return {
        "user_id": user_id,
        "first_name": user["first_name"],
        "username": (row["username"] if row else None),
        "email": email,
        "telegram_linked": bool(row and row["telegram_user_id"] is not None),
        "role": (row["role"] if row else "user") or "user",
        "is_admin": bool(row and row["role"] == "admin"),
        "trading_mode": (settings_row["trading_mode"] if settings_row else "paper") or "paper",
    }


@router.get("/signals/recent")
async def get_recent_signals(user: _CurrentUser, limit: int = 10):
    """Recent signal publications for the live market feed on dashboard."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT sp.market_id, sp.side, sp.target_price,
                   sp.signal_type, sp.published_at,
                   m.question AS market_question
            FROM signal_publications sp
            LEFT JOIN markets m ON m.id = sp.market_id
            WHERE sp.exit_signal = FALSE
              AND sp.published_at >= NOW() - INTERVAL '4 hours'
            ORDER BY sp.published_at DESC
            LIMIT $1
            """,
            min(limit, 20),
        )
    return [
        {
            "market_id": r["market_id"],
            "market_question": r["market_question"] or r["market_id"][:24] + "…",
            "side": r["side"],
            "target_price": float(r["target_price"]) if r["target_price"] else None,
            "signal_type": r["signal_type"],
            "published_at": r["published_at"].isoformat(),
        }
        for r in rows
    ]


@router.get("/activity")
async def get_activity(user: _CurrentUser, limit: int = 10):
    """Last N trade events (opens + closes) for the authenticated user."""
    pool = get_pool()
    user_id = user["user_id"]
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT p.id, p.status, p.side, p.size_usdc,
                   p.entry_price, p.pnl_usdc, p.exit_reason,
                   p.strategy_type, p.created_at, p.closed_at,
                   COALESCE(m.question, p.market_question) AS market_question
              FROM positions p
              LEFT JOIN markets m ON m.id = p.market_id
             WHERE p.user_id = $1::uuid
             ORDER BY COALESCE(p.closed_at, p.created_at) DESC
             LIMIT $2
            """,
            user_id,
            min(limit, 20),
        )
    return [
        {
            "id": str(r["id"]),
            "type": "trade_close" if r["status"] == "closed" else "trade_open",
            "status": r["status"],
            "side": r["side"],
            "size_usdc": float(r["size_usdc"]) if r["size_usdc"] else None,
            "entry_price": float(r["entry_price"]) if r["entry_price"] else None,
            "pnl_usdc": float(r["pnl_usdc"]) if r["pnl_usdc"] else None,
            "exit_reason": r["exit_reason"],
            "strategy_type": r["strategy_type"],
            "market_question": r["market_question"] or "",
            "ts": (r["closed_at"] or r["created_at"]).isoformat(),
        }
        for r in rows
    ]


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
                      active_preset, trading_mode, alerts_ack_at
               FROM user_settings WHERE user_id = $1::uuid""",
            user_id,
        )
        wallet_row = await conn.fetchrow(
            "SELECT balance_usdc FROM wallets WHERE user_id = $1::uuid", user_id
        )
        open_count = await conn.fetchval(
            "SELECT COUNT(*) FROM positions WHERE user_id=$1::uuid AND status IN ('open','pending_settlement')",
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
        pnl_alltime = await conn.fetchval(
            "SELECT COALESCE(SUM(pnl_usdc),0) FROM positions WHERE user_id=$1::uuid AND status='closed'",
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
        signals_today = await conn.fetchval(
            """SELECT COUNT(*) FROM positions
               WHERE user_id=$1::uuid
                 AND opened_at >= NOW() - INTERVAL '24 hours'""",
            user_id,
        )
        ks_active = await kill_switch.is_active()

        # Same global-pause lookup as /autotrade — the System Status sidebar
        # and topbar consume DashboardSummary, so SCANNER would still read
        # RUNNING during an admin pause if we relied on auto_trade_on alone.
        _active_preset = settings_row["active_preset"] if settings_row else None
        _strategy_name = _PRESET_TO_STRATEGY.get(str(_active_preset)) if _active_preset else None
        preset_globally_enabled = True
        if _strategy_name:
            _se = await conn.fetchval(
                "SELECT enabled FROM strategies WHERE name = $1", _strategy_name
            )
            preset_globally_enabled = True if _se is None else bool(_se)

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
        risk_profile=str(settings_row["risk_profile"] or "balanced") if settings_row else "balanced",
        pnl_alltime=float(pnl_alltime or 0),
        signals_today=int(signals_today or 0),
        active_preset_globally_enabled=preset_globally_enabled,
        alerts_ack_at=settings_row["alerts_ack_at"] if settings_row else None,
    )


@router.get("/market-feed")
async def get_market_feed(user: _CurrentUser) -> list[MarketFeedItem]:
    """Live crypto up/down candle markets — nearest close per asset.

    Reads the already-synced ``markets`` table (Polymarket CLOB prices); no
    external spot-price dependency. Powers the Home auto-slide market feed.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT DISTINCT ON (split_part(slug, '-updown-', 1))
                      split_part(slug, '-updown-', 1) AS asset,
                      yes_price, liquidity_usdc, resolution_at
               FROM markets
               WHERE slug LIKE '%updown%'
                 AND split_part(slug, '-updown-', 1) IN ('btc', 'eth', 'sol', 'bnb', 'xrp', 'doge', 'hype')
                 AND resolved = false
                 AND resolution_at > now()
                 AND yes_price IS NOT NULL
                 AND liquidity_usdc > 0
               ORDER BY split_part(slug, '-updown-', 1), resolution_at ASC"""
        )

    now = datetime.now(timezone.utc)
    asset_labels = {"btc": "BTC", "eth": "ETH", "sol": "SOL", "bnb": "BNB",
                    "xrp": "XRP", "doge": "DOGE", "hype": "HYPE"}
    feed: list[MarketFeedItem] = []
    for r in rows:
        asset_key = str(r["asset"] or "").lower()
        up_prob = float(r["yes_price"] or 0.0)
        if up_prob >= 0.52:
            lean = "UP"
        elif up_prob <= 0.48:
            lean = "DOWN"
        else:
            lean = "EVEN"
        secs = int((r["resolution_at"] - now).total_seconds())
        label = asset_labels.get(asset_key, asset_key.upper())
        feed.append(
            MarketFeedItem(
                asset=label,
                label=label,
                up_prob=up_prob,
                lean=lean,
                seconds_to_close=max(0, secs),
                liquidity_usdc=float(r["liquidity_usdc"] or 0.0),
            )
        )
    return feed


def _tp_sl_price(entry: float, side: str, pct, *, is_tp: bool) -> Optional[float]:
    """Derive the TP/SL trigger price (YES-price units, matching entry_price).

    Mirrors the PnL formula in domain/execution/paper.close_position: a YES
    position profits as the price rises, a NO position as it falls. Returns None
    when no TP/SL fraction is set. Result clamped to (0, 1).
    """
    if pct is None:
        return None
    p = float(pct)
    if p <= 0:
        return None
    if str(side).lower() == "no":
        # NO profits when YES price falls; TP is below entry, SL above.
        comp = 1.0 - entry
        price = 1.0 - comp * (1.0 + p) if is_tp else 1.0 - comp * (1.0 - p)
    else:
        price = entry * (1.0 + p) if is_tp else entry * (1.0 - p)
    return max(0.001, min(0.999, price))


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
    if status == "open":
        # Include pending_settlement so won-positions awaiting payout are visible
        where += " AND p.status IN ('open', 'pending_settlement')"
    elif status:
        where += f" AND p.status = ${len(params)+1}"
        params.append(status)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""SELECT p.id, p.market_id, COALESCE(m.question, p.market_question) AS market_question,
                       p.side, p.size_usdc, p.entry_price, p.current_price,
                       p.pnl_usdc, p.status, p.mode, p.opened_at, p.closed_at,
                       p.exit_reason, p.strategy_type, p.active_preset,
                       m.resolved AS market_resolved, m.winning_side,
                       COALESCE(p.applied_tp_pct, p.tp_pct) AS tp_pct,
                       COALESCE(p.applied_sl_pct, p.sl_pct) AS sl_pct
                FROM positions p
                LEFT JOIN markets m ON m.id = p.market_id
                {where}
                ORDER BY COALESCE(p.closed_at, p.opened_at) DESC
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
            current_price=float(r["current_price"]) if r["current_price"] is not None else None,
            pnl_usdc=float(r["pnl_usdc"]) if r["pnl_usdc"] is not None else None,
            status=r["status"],
            mode=r["mode"],
            opened_at=r["opened_at"],
            closed_at=r["closed_at"],
            exit_reason=r["exit_reason"],
            strategy_type=r["strategy_type"],
            active_preset=r["active_preset"],
            tp_pct=float(r["tp_pct"]) if r["tp_pct"] is not None else None,
            sl_pct=float(r["sl_pct"]) if r["sl_pct"] is not None else None,
            tp_price=_tp_sl_price(float(r["entry_price"]), r["side"], r["tp_pct"], is_tp=True),
            sl_price=_tp_sl_price(float(r["entry_price"]), r["side"], r["sl_pct"], is_tp=False),
            awaiting_redeem=(
                r["status"] in ("open", "pending_settlement")
                and bool(r["market_resolved"])
                and r["winning_side"] is not None
                and str(r["winning_side"]) == str(r["side"])
            ),
        )
        for r in rows
    ]


@router.post(
    "/positions/{position_id}/redeem",
    dependencies=[Depends(per_user_rate_limit("position_action", limit=30))],
)
async def force_redeem_position(position_id: str, user: _CurrentUser) -> JSONResponse:
    """Manually trigger redemption of a resolved winning position.

    For hourly auto-redeem users a won position sits 'open' (queued) until the
    next hourly tick. This lets the user settle it now: it runs the existing
    instant redeem fast-path on the position's pending redeem_queue row. The
    position must belong to the user, still be open, and have a pending queue
    row (i.e. the market resolved in their favour). Idempotent — a missing /
    already-claimed row returns a clear 409.
    """
    from ...services.redeem import instant_worker

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT rq.id AS queue_id
                 FROM redeem_queue rq
                 JOIN positions p ON p.id = rq.position_id
                WHERE rq.position_id = $1::uuid
                  AND p.user_id = $2::uuid
                  AND rq.status = 'pending'
                  AND p.status = 'open'
                LIMIT 1""",
            position_id, user["user_id"],
        )
    if row is None:
        raise HTTPException(
            status_code=409,
            detail="No pending redemption for this position (not yet won, "
                   "already settling, or already redeemed).",
        )
    await instant_worker.try_process(row["queue_id"])
    return JSONResponse({"status": "ok", "position_id": position_id})


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


@router.post(
    "/positions/{position_id}/close",
    response_model=ClosePositionResponse,
    dependencies=[Depends(per_user_rate_limit("position_action", limit=30))],
)
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
                      m.yes_token_id, m.no_token_id,
                      COALESCE(m.question, p.market_question) AS question,
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
                f"\U0001f534 <b>Position Manually Closed</b>\n"
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
                      category_filters, min_liquidity, max_resolution_days, min_volume_24h,
                      slippage_tolerance_pct, selected_timeframe, selected_assets,
                      max_per_trade_mode, max_per_trade_usdc, max_per_trade_pct,
                      daily_loss_override, max_drawdown_pct
               FROM user_settings WHERE user_id=$1::uuid""",
            user_id,
        )
        eq_row = await conn.fetchrow(
            """SELECT COALESCE(w.balance_usdc, 0)
                     + COALESCE((SELECT SUM(p.size_usdc) FROM positions p
                                 WHERE p.user_id = $1::uuid AND p.status = 'open'), 0)
                       AS equity_usdc
                 FROM wallets w WHERE w.user_id = $1::uuid""",
            user_id,
        )
        # Is the strategy backing the active preset globally enabled (operator
        # Ops-Console on/off)? When OFF, no new trades fire even though the
        # user's preset selection is unchanged — the dashboard reflects this as
        # "PAUSED (Admin)" instead of "ACTIVE". Default True (missing row = ON).
        _active_preset = s_row["active_preset"] if s_row else None
        _strategy_name = _PRESET_TO_STRATEGY.get(str(_active_preset)) if _active_preset else None
        preset_globally_enabled = True
        if _strategy_name:
            _se = await conn.fetchval(
                "SELECT enabled FROM strategies WHERE name = $1", _strategy_name
            )
            preset_globally_enabled = True if _se is None else bool(_se)

    cats: list[str] = list(s_row["category_filters"]) if s_row and s_row["category_filters"] else []
    cap_pct = float(s_row["capital_alloc_pct"]) if s_row else 0.5
    equity = float(eq_row["equity_usdc"]) if eq_row and eq_row["equity_usdc"] is not None else 0.0
    mpt_mode = (s_row["max_per_trade_mode"] if s_row and s_row["max_per_trade_mode"] else "auto")
    mpt_usdc = (float(s_row["max_per_trade_usdc"]) if s_row and s_row["max_per_trade_usdc"] is not None else None)
    mpt_pct = (float(s_row["max_per_trade_pct"]) if s_row and s_row["max_per_trade_pct"] is not None else None)
    ceiling = resolve_per_trade_ceiling(equity, mpt_mode, mpt_usdc, mpt_pct)
    return AutoTradeState(
        auto_trade_on=bool(u_row["auto_trade_on"]) if u_row else False,
        active_preset=s_row["active_preset"] if s_row else None,
        risk_profile=s_row["risk_profile"] if s_row else "balanced",
        capital_alloc_pct=float(s_row["capital_alloc_pct"]) if s_row else 0.5,
        tp_pct=float(s_row["tp_pct"]) if s_row and s_row["tp_pct"] is not None else None,
        sl_pct=float(s_row["sl_pct"]) if s_row and s_row["sl_pct"] is not None else None,
        market_categories=cats,
        min_liquidity=float(s_row["min_liquidity"]) if s_row and s_row["min_liquidity"] is not None else 1000.0,
        max_resolution_days=int(s_row["max_resolution_days"]) if s_row and s_row["max_resolution_days"] is not None else None,
        min_volume_24h=float(s_row["min_volume_24h"]) if s_row and s_row["min_volume_24h"] is not None else 100.0,
        slippage_tolerance_pct=float(s_row["slippage_tolerance_pct"]) if s_row and s_row["slippage_tolerance_pct"] is not None else None,
        selected_timeframe=s_row["selected_timeframe"] if s_row else None,
        selected_assets=list(s_row["selected_assets"]) if s_row and s_row["selected_assets"] else None,
        equity_usdc=round(equity, 2),
        effective_max_per_trade_usdc=round(suggested_trade_size(equity, cap_pct, ceiling_usdc=ceiling), 2),
        max_per_trade_mode=mpt_mode,
        max_per_trade_usdc=mpt_usdc,
        max_per_trade_pct=mpt_pct,
        daily_loss_override=(
            float(s_row["daily_loss_override"])
            if s_row and s_row["daily_loss_override"] is not None
            else None
        ),
        max_drawdown_pct=(
            float(s_row["max_drawdown_pct"])
            if s_row and s_row["max_drawdown_pct"] is not None
            else None
        ),
        active_preset_globally_enabled=preset_globally_enabled,
    )


@router.post("/autotrade/toggle")
async def toggle_autotrade(body: AutoTradeToggleRequest, user: _CurrentUser):
    if body.enabled and await kill_switch.is_active():
        raise HTTPException(status_code=409, detail="kill switch is active — resume trading first")

    pool = get_pool()
    user_id = user["user_id"]
    async with pool.acquire() as conn:
        if body.enabled:
            preset_row = await conn.fetchrow(
                "SELECT active_preset FROM user_settings WHERE user_id=$1::uuid", user_id,
            )
            if not preset_row or not preset_row["active_preset"]:
                raise HTTPException(
                    status_code=400,
                    detail="select a strategy preset before enabling auto-trade",
                )
        await conn.execute(
            "UPDATE users SET auto_trade_on=$1 WHERE id=$2::uuid",
            body.enabled, user_id,
        )
    return {"auto_trade_on": body.enabled}


# Preset key → the strategy it routes to, for the global on/off (strategies
# table) lookup. Mirrors signal_scan_job._PRESET_ALLOWED. Used so the dashboard
# can show "PAUSED (Admin)" when the active preset's strategy is globally off.
# Only contains presets that point to a real, reachable strategy.
_PRESET_TO_STRATEGY: dict[str, str] = {
    "close_sweep": "late_entry_v3",
    "safe_close":  "late_entry_v3",
    "flip_hunter": "late_entry_v3",
}


@router.get("/autotrade/preset-availability")
async def get_preset_availability(user: _CurrentUser) -> dict:
    """Per-preset + per-strategy availability for the authenticated user.

    Returns:
      ``{
         "presets": [{"key": "...", "strategy": "...", "enabled": bool}, ...],
         "strategies": {"<strategy_name>": bool, ...}
      }``

    The picker (WebTrader AutoTradePage + Telegram preset_tier_kb) MUST hide
    presets whose backing strategy is disabled. The ``strategies`` map covers
    every entry in ``_ADMIN_STRATEGIES`` so the frontend can also gate features
    that are not preset-backed (e.g. the Copy Trade tab — copy_trade has its
    own pipeline, not a preset, so it would not otherwise appear in
    ``presets``).

    FAIL-SAFE: a missing row in ``strategies`` defaults to enabled=True. A DB
    error is logged at WARNING and the endpoint returns every preset / strategy
    as enabled (consistent with the scanner-side fail-safe: a transient blip
    must never silently wipe the user's picker).
    """
    state: dict[str, bool] = {}
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT name, enabled FROM strategies")
        state = {str(r["name"]): bool(r["enabled"]) for r in rows}
    except Exception as exc:  # noqa: BLE001
        log.warning("preset_availability_db_error: %s", exc)
    presets = [
        {"key": preset, "strategy": strat, "enabled": state.get(strat, True)}
        for preset, strat in _PRESET_TO_STRATEGY.items()
    ]
    strategies = {name: state.get(name, True) for name in _ADMIN_STRATEGIES}
    return {"presets": presets, "strategies": strategies}

# Preset key → default risk parameters applied when preset is activated.
# Risk profile (capital/TP/SL) can be overridden separately via /autotrade/risk-profile.
#
# Narrowed to the 3 candle presets after WARP/R00T/strategy-system-cleanup. The
# scanner's _PRESET_ALLOWED only routes these three to a strategy
# (late_entry_v3); accepting any other key here would let a stale client /
# direct API call persist active_preset=<archived> → scanner emits no
# candidates and the dashboard "PAUSED (Admin)" indicator can't fire because
# the key is absent from _PRESET_TO_STRATEGY. activate_preset() rejects 400
# anything not in this map.
_PRESET_PARAMS: dict[str, dict[str, str | float]] = {
    "close_sweep": {"risk_profile": "balanced", "capital_alloc_pct": 0.30, "tp_pct": 0.15, "sl_pct": 0.08},
    "safe_close":  {"risk_profile": "balanced", "capital_alloc_pct": 0.25, "tp_pct": 0.12, "sl_pct": 0.06},
    "flip_hunter": {"risk_profile": "balanced", "capital_alloc_pct": 0.30, "tp_pct": 0.25, "sl_pct": 0.12},
}

# Presets restricted to short-duration crypto markets. Activating one auto-locks
# the market category filter to Crypto only and requires a timeframe (5m/15m).
_CRYPTO_SHORT_PRESETS: frozenset[str] = frozenset({"close_sweep", "safe_close", "flip_hunter"})
_VALID_TIMEFRAMES: frozenset[str] = frozenset({"5m", "15m"})
# Assets offered for crypto-short presets. BTC/ETH/SOL/BNB have deep candle
# books; XRP/DOGE/HYPE are offered but their books are thinner so they are
# opt-in. Activation with no explicit selection defaults to BTC only.
_CRYPTO_SHORT_ASSETS: tuple[str, ...] = ("BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "HYPE")
_VALID_ASSETS: frozenset[str] = frozenset(_CRYPTO_SHORT_ASSETS)
_DEFAULT_CRYPTO_SHORT_ASSETS: tuple[str, ...] = ("BTC",)

# Light per-timeframe params merged into user_settings.strategy_params (JSONB).
# close_sweep / safe_close: expiration_timing lib strategy reads these config knobs.
# flip_hunter: same market filters; underdog direction is hardcoded in the strategy.
# hours_before_* are in HOURS (6m=0.1, 18m=0.3).
_CLOSE_SWEEP_TF_PARAMS: dict[str, dict[str, float]] = {
    "5m":  {"hours_before_min": 0.0, "hours_before_max": 0.1, "min_price": 0.40, "max_price": 0.60,
            "min_volume_24h": 0.0, "min_liquidity": 500.0},
    "15m": {"hours_before_min": 0.0, "hours_before_max": 0.3, "min_price": 0.35, "max_price": 0.65,
            "min_volume_24h": 0.0, "min_liquidity": 500.0},
}
# safe_close: tighter price range (majority side must be 0.60–0.70); 30–60s window.
_SAFE_CLOSE_TF_PARAMS: dict[str, dict[str, float]] = {
    "5m":  {"hours_before_min": 0.0, "hours_before_max": 0.1, "min_price": 0.40, "max_price": 0.60,
            "min_volume_24h": 0.0, "min_liquidity": 500.0},
    "15m": {"hours_before_min": 0.0, "hours_before_max": 0.3, "min_price": 0.35, "max_price": 0.65,
            "min_volume_24h": 0.0, "min_liquidity": 500.0},
}
# flip_hunter: broader price filter — underdog side is 0.26–0.35, market overall
# is less leaned. hours_before_max = 0.04h ≈ 2.4m covers the 140s window.
_FLIP_HUNTER_TF_PARAMS: dict[str, dict[str, float]] = {
    "5m":  {"hours_before_min": 0.0, "hours_before_max": 0.04, "min_price": 0.25, "max_price": 0.75,
            "min_volume_24h": 0.0, "min_liquidity": 500.0},
    "15m": {"hours_before_min": 0.0, "hours_before_max": 0.1,  "min_price": 0.25, "max_price": 0.75,
            "min_volume_24h": 0.0, "min_liquidity": 500.0},
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
    # TP/SL follow the RISK PROFILE, not the preset (Kreo parity). The preset
    # still routes strategy + capital + window, but take-profit / stop-loss are
    # owned by the user's risk profile so they stay consistent across presets.
    from ...domain.risk.constants import tp_sl_for_profile
    params = dict(_PRESET_PARAMS[body.preset_key])
    _profile_ts = tp_sl_for_profile(str(params.get("risk_profile") or "balanced"))
    params["tp_pct"] = _profile_ts["tp_pct"]
    params["sl_pct"] = _profile_ts["sl_pct"]

    is_crypto_short = body.preset_key in _CRYPTO_SHORT_PRESETS

    # Resolve timeframe: crypto-short presets require one (default 5m); all other
    # presets clear it so the web UI hides the timeframe toggle and category lock.
    timeframe: str | None = None
    assets: list[str] | None = None
    if is_crypto_short:
        timeframe = body.selected_timeframe or "5m"
        if timeframe not in _VALID_TIMEFRAMES:
            raise HTTPException(
                status_code=400, detail=f"invalid timeframe: {timeframe} (expected 5m or 15m)"
            )
        # Normalize + validate the asset selection; default to all offered assets.
        raw_assets = [str(a).strip().upper() for a in (body.selected_assets or [])]
        assets = [a for a in raw_assets if a in _VALID_ASSETS]
        bad = [a for a in raw_assets if a not in _VALID_ASSETS]
        if bad:
            raise HTTPException(
                status_code=400,
                detail=f"invalid asset(s): {', '.join(bad)} (expected any of {', '.join(_CRYPTO_SHORT_ASSETS)})",
            )
        if not assets:
            assets = list(_DEFAULT_CRYPTO_SHORT_ASSETS)

    # Auto-lock market category to Crypto only for crypto-short presets;
    # None leaves the existing category_filters untouched for other presets.
    category_filters = ["Crypto"] if is_crypto_short else None

    # Light per-timeframe params → merged into strategy_params for candle presets.
    tf_params_json: str | None = None
    if body.preset_key == "close_sweep" and timeframe in _CLOSE_SWEEP_TF_PARAMS:
        tf_params_json = json.dumps({"expiration_timing": _CLOSE_SWEEP_TF_PARAMS[timeframe]})
    elif body.preset_key == "safe_close" and timeframe in _SAFE_CLOSE_TF_PARAMS:
        tf_params_json = json.dumps({"expiration_timing": _SAFE_CLOSE_TF_PARAMS[timeframe]})
    elif body.preset_key == "flip_hunter" and timeframe in _FLIP_HUNTER_TF_PARAMS:
        tf_params_json = json.dumps({"expiration_timing": _FLIP_HUNTER_TF_PARAMS[timeframe]})

    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE user_settings
                  SET active_preset       = $1,
                      risk_profile        = COALESCE($2, risk_profile),
                      capital_alloc_pct   = COALESCE($3, capital_alloc_pct),
                      tp_pct              = COALESCE($4, tp_pct),
                      sl_pct              = COALESCE($5, sl_pct),
                      selected_timeframe  = $6,
                      category_filters    = COALESCE($7, category_filters),
                      strategy_params     = CASE
                                              WHEN $8::jsonb IS NULL THEN strategy_params
                                              ELSE COALESCE(strategy_params, '{}'::jsonb) || $8::jsonb
                                            END,
                      selected_assets     = $9,
                      updated_at          = NOW()
               WHERE user_id = $10::uuid""",
            body.preset_key,
            params.get("risk_profile"),
            params.get("capital_alloc_pct"),
            params.get("tp_pct"),
            params.get("sl_pct"),
            timeframe,
            category_filters,
            tf_params_json,
            assets,
            user_id,
        )
    return {
        "active_preset": body.preset_key,
        "selected_timeframe": timeframe,
        "selected_assets": assets,
    }


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

    # Bounds: these feed trade sizing / exit thresholds. Without guards a user
    # could submit capital_alloc_pct=99999, negative tp/sl, etc. (stored raw,
    # used at execution time). Reject out-of-range values up front.
    if body.tp_pct is not None and not (0 < body.tp_pct <= 10):
        raise HTTPException(status_code=400, detail="tp_pct must be in (0, 10] (0%–1000%)")
    if body.sl_pct is not None and not (0 < body.sl_pct <= 1):
        raise HTTPException(status_code=400, detail="sl_pct must be in (0, 1] (0%–100%)")
    if body.capital_alloc_pct is not None and not (0 < body.capital_alloc_pct <= 0.80):
        raise HTTPException(status_code=400, detail="capital_alloc_pct must be in (0, 0.80]")
    if body.max_position_pct is not None and not (0 < body.max_position_pct <= 0.10):
        raise HTTPException(status_code=400, detail="max_position_pct must be in (0, 0.10] (system max 10%)")

    _add("tp_pct", body.tp_pct)
    _add("sl_pct", body.sl_pct)
    _add("capital_alloc_pct", body.capital_alloc_pct)
    _add("max_position_pct", body.max_position_pct)
    _add("auto_redeem_mode", body.auto_redeem_mode)
    _add("category_filters", body.category_filters)

    # Per-trade cap mode + values (owner-directed; also bounded at sizing time).
    if body.max_per_trade_mode is not None:
        if body.max_per_trade_mode not in ("auto", "fixed", "pct"):
            raise HTTPException(status_code=400, detail="max_per_trade_mode must be auto|fixed|pct")
        _add("max_per_trade_mode", body.max_per_trade_mode)
    if body.max_per_trade_usdc is not None and body.max_per_trade_usdc <= 0:
        raise HTTPException(status_code=400, detail="max_per_trade_usdc must be > 0")
    if body.max_per_trade_pct is not None and not (0 < body.max_per_trade_pct <= 1):
        raise HTTPException(status_code=400, detail="max_per_trade_pct must be in (0, 1] (0%–100%)")
    _add("max_per_trade_usdc", body.max_per_trade_usdc)
    _add("max_per_trade_pct", body.max_per_trade_pct)

    # Daily loss override: must be negative and no looser than -$2000 system floor.
    if body.daily_loss_override is not None:
        if body.daily_loss_override >= 0:
            raise HTTPException(status_code=400, detail="daily_loss_override must be negative (e.g. -300)")
        if body.daily_loss_override < -2000:
            raise HTTPException(status_code=400, detail="daily_loss_override cannot exceed system floor of -$2000")
        _add("daily_loss_override", body.daily_loss_override)

    # Max drawdown %: must be in (0, 8%]. Users can only make it stricter than 8%.
    if body.max_drawdown_pct is not None:
        if not (0 < body.max_drawdown_pct <= 0.08):
            raise HTTPException(status_code=400, detail="max_drawdown_pct must be in (0, 0.08] (0%–8%)")
        _add("max_drawdown_pct", body.max_drawdown_pct)

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
        # Custom allows TP-only OR SL-only: require capital + at least one of
        # tp/sl. The exit watcher already no-ops the unset side (it guards each
        # branch with `is not None`), so a null tp or null sl is safe.
        if body.capital_alloc_pct is None:
            raise HTTPException(
                status_code=422,
                detail="custom profile requires capital_alloc_pct",
            )
        if body.tp_pct is None and body.sl_pct is None:
            raise HTTPException(
                status_code=422,
                detail="custom profile requires at least one of tp_pct or sl_pct",
            )
        if body.capital_alloc_pct > 0.80:
            raise HTTPException(
                status_code=422,
                detail="capital_alloc_pct must not exceed 0.80 (80% hard ceiling)",
            )
        # Only enforce the ordering when BOTH are set.
        if body.tp_pct is not None and body.sl_pct is not None and body.tp_pct <= body.sl_pct:
            raise HTTPException(
                status_code=422,
                detail="tp_pct must be greater than sl_pct",
            )
        cap = body.capital_alloc_pct
        tp = body.tp_pct   # may be None → TP disabled
        sl = body.sl_pct   # may be None → SL disabled
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
            """SELECT id::text, type, amount_usdc, note, created_at FROM ledger
               WHERE user_id=$1::uuid ORDER BY created_at DESC, id DESC LIMIT 20""",
            user_id,
        )
        settings_row = await conn.fetchrow(
            "SELECT trading_mode FROM user_settings WHERE user_id=$1::uuid",
            user_id,
        )

    if not w_row:
        raise HTTPException(status_code=404, detail="wallet not found")

    trading_mode = settings_row["trading_mode"] if settings_row else "paper"

    return WalletInfo(
        deposit_address=w_row["deposit_address"],
        balance_usdc=float(w_row["balance_usdc"]),
        ledger_recent=[
            LedgerEntry(
                id=r["id"],
                type=r["type"],
                amount_usdc=float(r["amount_usdc"]),
                note=r["note"],
                created_at=r["created_at"],
            )
            for r in ledger_rows
        ],
        trading_mode=trading_mode,
        paper_mode=trading_mode != "live",
    )


@router.get("/wallet/ledger", response_model=LedgerPage)
async def get_wallet_ledger(
    user: _CurrentUser,
    offset: int = 0,
    limit: int = 20,
) -> LedgerPage:
    """Paginated ledger entries for wallet recent activity."""
    pool = get_pool()
    user_id = user["user_id"]
    limit = min(max(limit, 1), 100)
    offset = max(offset, 0)

    async with pool.acquire() as conn:
        total_row = await conn.fetchrow(
            "SELECT COUNT(*) AS cnt FROM ledger WHERE user_id=$1::uuid",
            user_id,
        )
        rows = await conn.fetch(
            """SELECT id::text, type, amount_usdc, note, created_at FROM ledger
               WHERE user_id=$1::uuid ORDER BY created_at DESC, id DESC
               LIMIT $2 OFFSET $3""",
            user_id,
            limit,
            offset,
        )

    total = int(total_row["cnt"]) if total_row else 0
    entries = [
        LedgerEntry(
            id=r["id"],
            type=r["type"],
            amount_usdc=float(r["amount_usdc"]),
            note=r["note"],
            created_at=r["created_at"],
        )
        for r in rows
    ]
    return LedgerPage(
        entries=entries,
        has_more=(offset + len(entries)) < total,
        total=total,
    )


@router.post(
    "/wallet/withdraw",
    response_model=WithdrawResponse,
    dependencies=[Depends(per_user_rate_limit("withdraw", limit=10))],
)
async def request_withdrawal(body: WithdrawRequest, user: _CurrentUser) -> WithdrawResponse:
    """Submit a withdrawal request (paper: queued for admin; live: same flow)."""
    from decimal import Decimal
    from ...wallet.withdrawals import (
        MIN_WITHDRAWAL_USDC,
        create_withdrawal_request,
        get_approval_mode,
    )

    amount = Decimal(str(body.amount_usdc))
    if amount < MIN_WITHDRAWAL_USDC:
        raise HTTPException(
            status_code=400,
            detail=f"Minimum withdrawal is ${float(MIN_WITHDRAWAL_USDC):.2f} USDC",
        )

    import re
    if not re.fullmatch(r"0x[0-9a-fA-F]{40}", body.destination_address):
        raise HTTPException(status_code=400, detail="Invalid EVM destination address")

    user_id = user["user_id"]
    try:
        withdrawal_id = await create_withdrawal_request(
            user_id=user_id,
            amount_usdc=amount,
            destination_address=body.destination_address,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    approval_mode = await get_approval_mode()
    return WithdrawResponse(
        id=str(withdrawal_id),
        status="pending",
        approval_mode=approval_mode,
        amount_usdc=float(amount),
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
        slippage = min(max(body.slippage_tolerance_pct, 0.0), 0.9999)
        params.append(slippage)
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
async def get_alerts(user: _CurrentUser) -> list[AlertItem]:
    """Active alerts for the current user.

    Includes both broadcast operator banners (user_id IS NULL) AND per-user
    trade-lifecycle events (user_id = current user). Limit 50 covers a busy
    auto-trade session without forcing the UI to paginate.

    Server-side respects ``user_settings.alerts_ack_at`` (the "Mark all read"
    watermark) so a click in AlertCenter sticks across devices, browsers,
    and localStorage clears — the localStorage-only watermark used to
    resurface every alert on a fresh refresh because the bell count was
    rebuilt purely from the latest /alerts payload.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT a.id, a.severity, a.title, a.body, a.created_at
               FROM system_alerts a
               LEFT JOIN user_settings us ON us.user_id = $1::uuid
               WHERE a.dismissed = FALSE
                 AND (a.expires_at IS NULL OR a.expires_at > NOW())
                 AND (a.user_id IS NULL OR a.user_id = $1::uuid)
                 AND (us.alerts_ack_at IS NULL OR a.created_at > us.alerts_ack_at)
               ORDER BY a.created_at DESC
               LIMIT 50""",
            user["user_id"],
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


@router.post("/alerts/ack-all")
async def ack_all_alerts(user: _CurrentUser) -> dict[str, str | None]:
    """Persist the AlertCenter "Mark all read" click server-side.

    Sets ``user_settings.alerts_ack_at = NOW()`` so subsequent /alerts and
    closed-position alert fetches collapse to "nothing pre-dating the click"
    on every device the user signs in from. Returns the new watermark
    serialised as ISO-8601 with offset so the caller can update its local
    visibleAlerts filter immediately without waiting for the next /dashboard
    refresh.

    Idempotent: a second call simply moves the watermark forward to the
    current NOW() and returns the new ts.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        # INSERT...ON CONFLICT covers users who haven't materialised a
        # user_settings row yet (rare in practice but possible on the
        # signup → settings-write race).
        # NOT NULL columns (risk_profile, trading_mode, …) carry DEFAULTs in
        # the migration 001 schema, but we still write the canonical paper-
        # parity literals here so this endpoint stays aligned with the rest
        # of the codebase's "explicit > schema default" convention pinned by
        # test_paper_default_invariant (signup INSERTs are required to spell
        # trading_mode='paper' so a future schema edit that drops the
        # default doesn't silently flip a brand-new user to live mode).
        row = await conn.fetchrow(
            """INSERT INTO user_settings (user_id, alerts_ack_at, trading_mode, risk_profile, capital_alloc_pct)
               VALUES ($1::uuid, NOW(), 'paper', 'balanced', 0.40)
               ON CONFLICT (user_id) DO UPDATE SET alerts_ack_at = NOW()
               RETURNING alerts_ack_at""",
            user["user_id"],
        )
    return {"alerts_ack_at": row["alerts_ack_at"].isoformat() if row and row["alerts_ack_at"] else None}


@router.get("/settings/notification-prefs")
async def get_notification_prefs(user: _CurrentUser) -> dict:
    """Return the user's per-alert × per-channel notification prefs.

    Shape: {"trade_opened": {"web": true, "tg": true}, ...}. Missing keys
    default to both channels ON; UI fills the rest from the static defaults.
    """
    prefs = await _notif_prefs.get_prefs(user["user_id"])
    return {"prefs": prefs}


@router.patch("/settings/notification-prefs")
async def update_notification_prefs(
    body: dict,
    user: _CurrentUser,
) -> dict:
    """Overwrite the user's notification prefs blob (UI sends the full dict)."""
    raw = body.get("prefs") if isinstance(body, dict) else None
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="prefs must be an object")
    await _notif_prefs.set_prefs(user["user_id"], raw)
    return {"updated": True}


@router.get("/killswitch", response_model=KillSwitchStatus)
async def get_killswitch(user: _CurrentUser) -> KillSwitchStatus:
    return KillSwitchStatus(active=await kill_switch.is_active())


@router.post(
    "/kill",
    dependencies=[Depends(per_user_rate_limit("user_pause", limit=10))],
)
async def web_kill(user: _CurrentUser):
    """Pause THIS user's bot — does NOT activate the global kill switch.

    Multi-tenant safety (Axis #1): the per-user "kill" / pause button on
    the dashboard sets ``users.paused=TRUE`` for the calling user only.
    The risk gate honours ``ctx.paused`` and rejects new trades for that
    user. The bot-wide kill switch is operator-only — Telegram ``/kill``
    or ``/api/ops/kill`` activates it, never a regular WebTrader user.
    """
    from ...users import set_paused
    user_id = user["user_id"]
    try:
        await set_paused(UUID(str(user_id)), True)
    except Exception as exc:
        log.error("web kill failed: %s", exc)
        raise HTTPException(status_code=500, detail="kill switch failed")
    await audit.write(
        actor_role="user",
        action="webtrader_user_pause",
        user_id=UUID(str(user_id)),
        payload={"source": "/api/web/kill"},
    )
    return {"ok": True, "user_paused": True}


@router.post(
    "/resume",
    dependencies=[Depends(per_user_rate_limit("user_pause", limit=10))],
)
async def web_resume(user: _CurrentUser):
    """Resume THIS user's bot — clears the per-user paused flag.

    Mirrors ``/kill``: sets ``users.paused=FALSE`` so the risk gate
    accepts new trades for this user again. Does not touch the global
    kill switch (operator-only). Shares the "user_pause" rate-limit
    scope with ``/kill`` so a single user cannot flap the flag.
    """
    from ...users import set_paused
    user_id = user["user_id"]
    try:
        await set_paused(UUID(str(user_id)), False)
    except Exception as exc:
        log.error("web resume failed: %s", exc)
        raise HTTPException(status_code=500, detail="resume failed")
    await audit.write(
        actor_role="user",
        action="webtrader_user_resume",
        user_id=UUID(str(user_id)),
        payload={"source": "/api/web/resume"},
    )
    return {"ok": True, "user_paused": False}


@router.post(
    "/emergency-stop",
    response_model=EmergencyStopResponse,
    dependencies=[Depends(per_user_rate_limit("emergency_stop", limit=5))],
)
async def web_emergency_stop(user: _CurrentUser) -> EmergencyStopResponse:
    """Halt THIS user's bot and force-close every open position they own.

    Multi-tenant safety (Axis #1): scoped to the calling user only. Two
    effects mirror the Telegram pause+close-all flow but stay per-user:
      1. ``users.paused=TRUE`` — the risk gate blocks new trades for
         this user. Other users are unaffected.
      2. ``positions.force_close_intent=TRUE`` for every open position
         owned by this user — the exit watcher closes them on its next
         tick at current market price, regardless of profit or loss.
    The global ``system_settings.kill_switch_active`` is NOT touched —
    that is an operator-only control reachable via ``/api/ops/kill`` or
    Telegram ``/kill``.
    """
    from ...users import set_paused
    user_id = user["user_id"]
    try:
        await set_paused(UUID(str(user_id)), True)
        marked = await mark_force_close_intent_for_user(UUID(str(user_id)))
    except Exception as exc:
        log.error("web emergency stop failed user=%s: %s", user_id, exc)
        raise HTTPException(status_code=500, detail="emergency stop failed")

    await audit.write(
        actor_role="user",
        action="webtrader_emergency_stop_close_all",
        user_id=UUID(str(user_id)),
        payload={"positions_marked": marked, "user_paused": True},
    )
    return EmergencyStopResponse(positions_marked=marked, user_paused=True)


@router.get("/status", response_model=RuntimeStatus)
async def get_runtime_status(user: _CurrentUser) -> RuntimeStatus:
    """Realtime backend runtime state — scanner, trading mode, risk, positions."""
    from ...jobs.market_signal_scanner import get_scanner_state
    pool = get_pool()
    user_id = user["user_id"]
    async with pool.acquire() as conn:
        settings_row = await conn.fetchrow(
            "SELECT risk_profile, trading_mode, active_preset FROM user_settings WHERE user_id=$1::uuid",
            user_id,
        )
        open_count = await conn.fetchval(
            "SELECT COUNT(*) FROM positions WHERE user_id=$1::uuid AND status IN ('open','pending_settlement')",
            user_id,
        )
        user_paused = bool(await conn.fetchval(
            "SELECT paused FROM users WHERE id=$1::uuid", user_id,
        ) or False)
    scanner = get_scanner_state()
    ks_active = await kill_switch.is_active()
    trading_mode = settings_row["trading_mode"] if settings_row else "paper"
    return RuntimeStatus(
        trading_mode=trading_mode,
        paper_mode=trading_mode != "live",
        active_preset=settings_row["active_preset"] if settings_row else None,
        risk_profile=settings_row["risk_profile"] if settings_row else "balanced",
        kill_switch_active=ks_active,
        user_paused=user_paused,
        open_positions=int(open_count or 0),
        scanner_scanned=scanner.get("scanned", 0),
        scanner_published=scanner.get("published", 0),
        scanner_last_tick=scanner.get("last_tick_ts"),
    )


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
            "SELECT size_usdc, entry_price, current_price FROM positions WHERE user_id=$1::uuid AND status IN ('open','pending_settlement')",
            user_id,
        )
        total_closed = int(
            await conn.fetchval(
                "SELECT COUNT(*) FROM positions WHERE user_id=$1::uuid AND status IN ('closed', 'expired', 'market_expired')",
                user_id,
            ) or 0
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
        total_closed=total_closed,
    )


def _unrealized_pnl(open_rows: list) -> float:
    total = 0.0
    for r in open_rows:
        ep = float(r["entry_price"])
        if ep <= 0:
            continue
        # Strict-interior guard: reject the CLOB empty-book 1.0/0.0 sentinel
        # that PR #1182 fixed on the fetch path but may still sit in stale
        # current_price DB rows written before the fix. Out-of-band values
        # fall back to entry_price (P&L = 0) until exit_watcher self-heals.
        cp = ep
        cp_raw = r["current_price"]
        if cp_raw is not None:
            val = float(cp_raw)
            if 0 < val < 1:
                cp = val
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
            "SELECT size_usdc, entry_price, current_price FROM positions WHERE user_id=$1::uuid AND status IN ('open','pending_settlement')",
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


@router.post("/stream-token")
async def issue_stream_token(user: _CurrentUser) -> dict:
    """Mint a short-lived, SSE-scoped handshake token so the main JWT never
    appears in the EventSource URL (which lands in proxy/access logs)."""
    return {"token": mint_stream_token(user["user_id"], user.get("telegram_id"))}


@router.get("/stream")
async def sse_stream(token: str | None = Query(default=None)):
    # Authenticated via the short-lived SSE handshake token only (NOT the main
    # JWT) — see issue_stream_token. decode_stream_token enforces scope='sse'.
    payload = decode_stream_token(token)
    telegram_id: int | None = payload.get("telegram_id")
    return EventSourceResponse(
        webtrader_sse.stream_for_user(payload["user_id"], telegram_id)
    )


@router.get("/portfolio/analytics", response_model=PortfolioAnalytics)
async def get_portfolio_analytics(user: _CurrentUser) -> PortfolioAnalytics:
    pool = get_pool()
    user_id = user["user_id"]

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT p.pnl_usdc, p.opened_at, p.closed_at,
                      COALESCE(p.strategy_type, 'unknown') AS strategy_type,
                      p.active_preset,
                      COALESCE(m.question, p.market_question, p.market_id) AS market_question
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
            dd = min((peak - running) / peak, 1.0)
        elif running < 0:
            dd = 1.0  # 100% drawdown from zero starting point
        else:
            dd = 0.0
        if dd > max_dd:
            max_dd = dd

    # Profit per strategy — aggregate by active_preset when present so the
    # three late_entry_v3 presets (close_sweep / safe_close / flip_hunter)
    # surface separately. Falls back to strategy_type for rows opened before
    # migration 062 added the active_preset column.
    strat_pnl: dict[str, float] = {}
    for r in rows:
        key = r["active_preset"] or r["strategy_type"]
        strat_pnl[key] = strat_pnl.get(key, 0.0) + float(r["pnl_usdc"])
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
               WHERE updated_at > NOW() - INTERVAL '2 hours'
               ORDER BY total_pnl DESC NULLS LAST
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


import re as _re  # noqa: E402

_WALLET_RE = _re.compile(r"^0x[0-9a-fA-F]{40}$")


@router.get("/copy-trade/wallet-360/{address}")
async def get_wallet_360_endpoint(address: str, user: _CurrentUser):
    if not _WALLET_RE.match(address):
        raise HTTPException(status_code=422, detail="Invalid wallet address format")
    from ...services.copy_trade.wallet_360 import get_wallet_360
    result = await get_wallet_360(address, window_days="7")
    return {
        "address": result.address,
        "win_rate": result.win_rate,
        "roi": result.roi,
        "total_pnl": result.total_pnl,
        "sharpe_ratio": result.sharpe_ratio,
        "max_drawdown": result.max_drawdown,
        "markets_traded": result.markets_traded,
        "total_trades": result.total_trades,
        "performance_trend": result.performance_trend,
        "risk_level": result.risk_level,
        "sybil_risk_flag": result.sybil_risk_flag,
        "sybil_risk_score": result.sybil_risk_score,
        "combined_risk_score": result.combined_risk_score,
        "flagged_metrics": result.flagged_metrics,
        "last_active": result.last_active,
        "available": result.available,
    }


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


@router.post(
    "/copy-trade/tasks",
    status_code=201,
    dependencies=[Depends(per_user_rate_limit("copy_task", limit=20))],
)
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


# ── Live-trading activation (Axis #3 — WARP/ROOT-live-activation-flow) ──────
# Per-user opt-in into live execution. Reads operator env guards + the
# 8-gate live_checklist + the user's `live_capital_cap_usdc` setting.
# A user toggles into live mode via /live/enable with an EXPLICIT capital
# cap and an EXACT typed confirm phrase. /live/disable reverts. Risk gate
# step 15 (domain/risk/gate.py) enforces the cap on every approved live
# trade — a user with cap=0 cannot execute live, and the gate rejects
# any trade that would push aggregate live exposure past the cap.

# Single source of truth shared with the Telegram /enable_live flow
# (domain/activation/live_opt_in_gate.py) so both surfaces stay in sync.
from ...domain.activation.live_opt_in_gate import (  # noqa: E402
    LIVE_CAP_MAX_USDC,
    LIVE_CAP_MIN_USDC,
    LIVE_ENABLE_CONFIRM_PHRASE as _LIVE_ENABLE_CONFIRM_PHRASE,
)


def _operator_guards_open(s) -> bool:
    """All five operator-level env guards must be open before any user
    can flip to live mode (mirrors `assert_live_guards` defensively)."""
    return bool(
        s.ENABLE_LIVE_TRADING
        and s.EXECUTION_PATH_VALIDATED
        and s.CAPITAL_MODE_CONFIRMED
        and s.RISK_CONTROLS_VALIDATED
        and s.SECURITY_HARDENING_VALIDATED
    )


@router.get("/live/status", response_model=LiveStatus)
async def get_live_status(user: _CurrentUser) -> LiveStatus:
    """Return the user's live-mode readiness + current state.

    Surfaces every piece of information the UI needs to render the live
    opt-in screen: current trading_mode, capital cap, open live exposure,
    operator env-guard state, and the 8-gate live_checklist outcome.
    """
    from ...domain.activation import live_checklist
    from ...config import get_settings
    s = get_settings()
    user_id = user["user_id"]
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT trading_mode, live_capital_cap_usdc "
            "FROM user_settings WHERE user_id = $1::uuid",
            user_id,
        )
        open_live = float(await conn.fetchval(
            "SELECT COALESCE(SUM(size_usdc), 0) "
            "FROM positions "
            "WHERE user_id = $1::uuid "
            "  AND mode = 'live' "
            "  AND status IN ('open', 'pending_settlement')",
            user_id,
        ) or 0)
    trading_mode = (row["trading_mode"] if row else "paper") or "paper"
    cap = float((row["live_capital_cap_usdc"] if row else 0) or 0)
    checklist = await live_checklist.evaluate(UUID(str(user_id)))
    return LiveStatus(
        trading_mode=trading_mode,
        live_capital_cap_usdc=cap,
        open_live_exposure_usdc=open_live,
        operator_guards_open=_operator_guards_open(s),
        checklist_passed=checklist.passed,
        failed_gates=list(checklist.failed_gates),
    )


@router.post(
    "/live/enable",
    response_model=LiveEnableResponse,
    dependencies=[Depends(per_user_rate_limit("live_activation", limit=5))],
)
async def enable_live(
    body: LiveEnableRequest,
    user: _CurrentUser,
) -> LiveEnableResponse:
    """Flip the user's trading_mode to 'live' after typed confirmation.

    Defensive gates (all must pass):
      1. Operator env guards are open.
      2. 8-gate live_checklist passes for this user.
      3. `confirm_phrase` matches the exact required string. Defends
         against accidental clicks; no normalisation, case-sensitive.
      4. `live_capital_cap_usdc > 0` and bounded by SYSTEM ceiling (the
         user is not allowed to set an unbounded cap).
      5. The gate-level enforcement in `domain/risk/gate.py` step 15
         still has the final say on every individual trade — this
         endpoint only flips the user-level enable switch.
    """
    from ...domain.activation import live_checklist
    from ...config import get_settings
    s = get_settings()
    user_id = user["user_id"]

    if not _operator_guards_open(s):
        raise HTTPException(
            status_code=409,
            detail="operator activation guards are not open",
        )
    if body.confirm_phrase != _LIVE_ENABLE_CONFIRM_PHRASE:
        raise HTTPException(
            status_code=400,
            detail=(
                f"confirm_phrase must equal the exact string "
                f"'{_LIVE_ENABLE_CONFIRM_PHRASE}' to enable live trading"
            ),
        )
    if not (LIVE_CAP_MIN_USDC < float(body.live_capital_cap_usdc) <= LIVE_CAP_MAX_USDC):
        raise HTTPException(
            status_code=400,
            detail=f"live_capital_cap_usdc must be > 0 and ≤ {int(LIVE_CAP_MAX_USDC)}",
        )

    checklist = await live_checklist.evaluate(UUID(str(user_id)))
    if not checklist.passed:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "live_checklist gates not all passing",
                "failed_gates": list(checklist.failed_gates),
            },
        )

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE user_settings "
                "   SET trading_mode = 'live', "
                "       live_capital_cap_usdc = $2, "
                "       updated_at = NOW() "
                " WHERE user_id = $1::uuid",
                user_id, float(body.live_capital_cap_usdc),
            )

    await audit.write(
        actor_role="user",
        action="webtrader_live_enable",
        user_id=UUID(str(user_id)),
        payload={
            "live_capital_cap_usdc": float(body.live_capital_cap_usdc),
            "operator_guards_open": True,
            "checklist_passed": True,
        },
    )
    return LiveEnableResponse(
        trading_mode="live",
        live_capital_cap_usdc=float(body.live_capital_cap_usdc),
    )


@router.post(
    "/live/disable",
    dependencies=[Depends(per_user_rate_limit("live_activation", limit=5))],
)
async def disable_live(user: _CurrentUser) -> dict:
    """Flip the user's trading_mode back to 'paper'.

    Single-step, no confirm phrase — easy to back out of live mode.
    Preserves `live_capital_cap_usdc` so a subsequent enable doesn't
    require re-entering the cap (the user already verified that value
    on opt-in). Open live positions are NOT closed by this endpoint —
    they will resolve under the original live mode. New trades will be
    paper-mode-only.
    """
    user_id = user["user_id"]
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE user_settings "
            "   SET trading_mode = 'paper', "
            "       updated_at = NOW() "
            " WHERE user_id = $1::uuid",
            user_id,
        )
    await audit.write(
        actor_role="user",
        action="webtrader_live_disable",
        user_id=UUID(str(user_id)),
        payload={"source": "/api/web/live/disable"},
    )
    return {"ok": True, "trading_mode": "paper"}


# ── Account unification — reverse Telegram-link ────────────────────────────
# An email-first WebTrader user links their Telegram so both surfaces resolve
# to ONE account (one user_id → LIVE/PAPER state always in sync). WebTrader
# mints a one-time code; the user redeems it in the bot via `/link <code>`.


@router.get("/account/link-telegram/status")
async def link_telegram_status(user: _CurrentUser) -> dict:
    """Whether this account already has a Telegram identity linked."""
    user_id = user["user_id"]
    pool = get_pool()
    async with pool.acquire() as conn:
        tg = await conn.fetchval(
            "SELECT telegram_user_id FROM users WHERE id = $1::uuid", user_id,
        )
    return {"linked": tg is not None}


@router.post(
    "/account/link-telegram/start",
    dependencies=[Depends(per_user_rate_limit("account_link", limit=5))],
)
async def link_telegram_start(user: _CurrentUser) -> dict:
    """Mint a one-time link code for the authenticated (email) account.

    The user sends `/link <code>` to the bot to attach their Telegram. 409 if
    the account already has a Telegram linked.
    """
    from ...domain.activation.account_link import (
        AccountLinkError,
        CODE_TTL_MINUTES,
        format_code_for_display,
        generate_link_code,
    )
    from ...config import get_settings
    user_id = user["user_id"]
    try:
        code = await generate_link_code(UUID(str(user_id)))
    except AccountLinkError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    display = format_code_for_display(code)
    bot_username = (get_settings().TELEGRAM_BOT_USERNAME or "").lstrip("@")
    return {
        "code": display,
        "link_command": f"/link {display}",
        "expires_minutes": CODE_TTL_MINUTES,
        "bot_username": bot_username,
    }


# ── Admin console (role='admin' only) ──────────────────────────────────────
# Operator dashboard for the logged-in admin: system overview (incl. master
# hot-pool address + balances for funding), user roster, and global strategy
# on/off switches. All endpoints gate on users.role = 'admin'.

# Canonical strategy roster the operator can toggle. Only strategies with a
# real user-facing trigger path live here — see migration 068. Adding a new
# strategy means: (1) implement scan/exit, (2) add a preset that routes to it,
# (3) seed a row in `strategies`, (4) append the name here, (5) add to
# _PRESET_TO_STRATEGY so the user dashboard "PAUSED (Admin)" indicator works.
_ADMIN_STRATEGIES: tuple[str, ...] = (
    "late_entry_v3",
    "signal_following",
    "copy_trade",
)


async def _require_admin(user: _CurrentUser) -> dict:
    """Dependency: 403 unless the authenticated user has role='admin'."""
    pool = get_pool()
    async with pool.acquire() as conn:
        role = await conn.fetchval(
            "SELECT role FROM users WHERE id = $1::uuid", user["user_id"],
        )
    if role != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    return user


_AdminUser = Annotated[dict, Depends(_require_admin)]


@router.get("/admin/overview")
async def admin_overview(user: _AdminUser) -> dict:
    """System snapshot for the admin console."""
    from ...config import get_settings
    from ...wallet.vault import master_wallet
    from ...integrations import polygon
    s = get_settings()

    pool_address: Optional[str] = None
    pool_usdc: Optional[float] = None
    pool_matic: Optional[float] = None
    try:
        pool_address, _ = master_wallet()
    except Exception:
        pool_address = None
    if pool_address:
        try:
            pool_usdc = await polygon.get_usdc_balance(pool_address)
        except Exception:
            pool_usdc = None
        try:
            pool_matic = await polygon.get_native_balance(pool_address)
        except Exception:
            pool_matic = None

    pool = get_pool()
    async with pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users") or 0
        admins = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'admin'") or 0
        auto_on = await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE auto_trade_on = TRUE AND paused = FALSE"
        ) or 0
        live_users = await conn.fetchval(
            "SELECT COUNT(*) FROM user_settings WHERE trading_mode = 'live'"
        ) or 0
        open_paper = await conn.fetchval(
            "SELECT COUNT(*) FROM positions WHERE status = 'open' AND mode = 'paper'"
        ) or 0
        open_live = await conn.fetchval(
            "SELECT COUNT(*) FROM positions WHERE status = 'open' AND mode = 'live'"
        ) or 0
        total_balance = await conn.fetchval(
            "SELECT COALESCE(SUM(balance_usdc), 0) FROM wallets"
        ) or 0
        last_scan = await conn.fetchrow(
            "SELECT started_at, markets_seen, candidates_emitted, "
            "       risk_approved, paper_orders_created, mode "
            "FROM scan_runs ORDER BY started_at DESC LIMIT 1"
        )

    kill_active = False
    try:
        from ...database import is_kill_switch_active
        kill_active = bool(await is_kill_switch_active())
    except Exception:
        kill_active = False

    # Polymarket trading-account config so the operator can VERIFY the funder /
    # sig type / credential source actually loaded (these live in env/secrets,
    # not the DB, and were previously invisible in the console).
    try:
        from ...integrations import clob as _clob
        _api_key, _, _ = _clob.effective_credentials(s)
    except Exception:
        _api_key = ""
    if s.POLYMARKET_API_KEY:
        creds_source = "env"
    elif _api_key:
        creds_source = "derived"
    else:
        creds_source = "none"

    return {
        "pool": {
            "address": pool_address,
            "usdc": pool_usdc,
            "matic": pool_matic,
        },
        "polymarket": {
            "funder_address": s.POLYMARKET_FUNDER_ADDRESS or None,
            "signature_type": int(s.POLYMARKET_SIGNATURE_TYPE),
            "use_real_clob": bool(s.USE_REAL_CLOB),
            "creds_source": creds_source,        # env | derived | none
            "creds_ready": bool(_api_key),
        },
        "guards": {
            "ENABLE_LIVE_TRADING": bool(s.ENABLE_LIVE_TRADING),
            "EXECUTION_PATH_VALIDATED": bool(s.EXECUTION_PATH_VALIDATED),
            "CAPITAL_MODE_CONFIRMED": bool(s.CAPITAL_MODE_CONFIRMED),
            "RISK_CONTROLS_VALIDATED": bool(s.RISK_CONTROLS_VALIDATED),
            "SECURITY_HARDENING_VALIDATED": bool(s.SECURITY_HARDENING_VALIDATED),
            "USE_REAL_CLOB": bool(s.USE_REAL_CLOB),
        },
        "kill_switch_active": kill_active,
        "counts": {
            "users": int(total_users),
            "admins": int(admins),
            "auto_trade_on": int(auto_on),
            "live_users": int(live_users),
            "open_positions_paper": int(open_paper),
            "open_positions_live": int(open_live),
            "total_wallet_usdc": float(total_balance),
        },
        "last_scan": dict(last_scan) if last_scan else None,
    }


@router.get("/admin/users")
async def admin_users(user: _AdminUser, limit: int = 50, offset: int = 0) -> dict:
    """Paginated user roster."""
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    pool = get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM users") or 0
        rows = await conn.fetch(
            """
            SELECT u.id, u.username, u.email, u.role, u.auto_trade_on, u.paused,
                   u.created_at,
                   COALESCE(st.trading_mode, 'paper')        AS trading_mode,
                   COALESCE(st.active_preset, '')            AS active_preset,
                   COALESCE(w.balance_usdc, 0)               AS balance_usdc,
                   (SELECT COUNT(*) FROM positions p
                     WHERE p.user_id = u.id AND p.status = 'open') AS open_positions
              FROM users u
              LEFT JOIN user_settings st ON st.user_id = u.id
              LEFT JOIN wallets       w  ON w.user_id  = u.id
             ORDER BY u.created_at DESC NULLS LAST
             LIMIT $1 OFFSET $2
            """,
            limit, offset,
        )
    users = []
    for r in rows:
        email = r["email"]
        if email and email.endswith("@telegram.local"):
            email = None
        users.append({
            "user_id": str(r["id"]),
            "username": r["username"],
            "email": email,
            "role": r["role"],
            "trading_mode": r["trading_mode"],
            "active_preset": r["active_preset"] or None,
            "balance_usdc": float(r["balance_usdc"]),
            "auto_trade_on": bool(r["auto_trade_on"]),
            "paused": bool(r["paused"]),
            "open_positions": int(r["open_positions"]),
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        })
    return {"total": int(total), "limit": limit, "offset": offset, "users": users}


@router.get("/admin/strategies")
async def admin_strategies(user: _AdminUser) -> dict:
    """List every toggleable strategy + its global enabled state (default ON)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT name, enabled FROM strategies")
    state = {str(r["name"]): bool(r["enabled"]) for r in rows}
    strategies = [
        {"name": name, "enabled": state.get(name, True)}
        for name in _ADMIN_STRATEGIES
    ]
    return {"strategies": strategies}


@router.post(
    "/admin/strategies/toggle",
    dependencies=[Depends(per_user_rate_limit("admin_strategy", limit=30))],
)
async def admin_toggle_strategy(body: StrategyToggleRequest, user: _AdminUser) -> dict:
    """Flip a strategy on/off globally (fail-safe: scanner treats missing/ON)."""
    if body.name not in _ADMIN_STRATEGIES:
        raise HTTPException(status_code=400, detail="unknown strategy")
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO strategies (name, enabled, updated_at) "
            "VALUES ($1, $2, NOW()) "
            "ON CONFLICT (name) DO UPDATE SET enabled = $2, updated_at = NOW()",
            body.name, bool(body.enabled),
        )
    await audit.write(
        actor_role="admin",
        action="admin_strategy_toggle",
        user_id=UUID(str(user["user_id"])),
        payload={"strategy": body.name, "enabled": bool(body.enabled)},
    )
    return {"name": body.name, "enabled": bool(body.enabled)}


# ── Admin user detail + edit ──────────────────────────────────────────────────
# Per-user operator view + partial settings update. Mirrors the user-facing
# /autotrade/preset, /autotrade/risk-profile, /autotrade/settings entry points
# but acting on behalf of any user (operator override). Every mutating call
# is audit-logged with actor_role='admin' + target user_id.


_VALID_MAX_PER_TRADE_MODES: frozenset[str] = frozenset({"auto", "fixed", "pct"})
# Hard ceilings (echoed from the user-facing customize path). Operator edits
# are subject to the same physical bounds — admin can change a user's value,
# not bypass the system fence.
_MAX_PER_TRADE_USDC_MIN = 1.0
_MAX_PER_TRADE_USDC_MAX = 500.0
_MAX_PER_TRADE_PCT_MIN = 0.005
_MAX_PER_TRADE_PCT_MAX = 0.10
_CAPITAL_ALLOC_PCT_MIN = 0.01
_CAPITAL_ALLOC_PCT_MAX = 0.80
_TP_PCT_MIN = 0.005
_TP_PCT_MAX = 10.0
_SL_PCT_MIN = 0.005
_SL_PCT_MAX = 1.0


@router.get("/admin/users/{user_id}", response_model=AdminUserDetail)
async def admin_user_detail(user_id: str, user: _AdminUser) -> AdminUserDetail:
    """Full per-user operator view (read-only).

    404 when the target user does not exist. Surfaces every editable field +
    runtime state so the Ops Console drawer can render "what the user sees
    now" without re-fetching across multiple endpoints.
    """
    try:
        target_uuid = UUID(user_id)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(status_code=400, detail="invalid user_id") from exc
    pool = get_pool()
    async with pool.acquire() as conn:
        u_row = await conn.fetchrow(
            """SELECT u.id, u.username, u.email, u.role, u.auto_trade_on,
                      u.paused, u.created_at
                 FROM users u
                WHERE u.id = $1::uuid""",
            target_uuid,
        )
        if not u_row:
            raise HTTPException(status_code=404, detail="user not found")
        s_row = await conn.fetchrow(
            """SELECT trading_mode, active_preset, risk_profile,
                      capital_alloc_pct, tp_pct, sl_pct,
                      max_per_trade_mode, max_per_trade_usdc, max_per_trade_pct,
                      selected_timeframe, selected_assets
                 FROM user_settings WHERE user_id = $1::uuid""",
            target_uuid,
        )
        w_row = await conn.fetchrow(
            "SELECT balance_usdc FROM wallets WHERE user_id = $1::uuid",
            target_uuid,
        )
        open_count = await conn.fetchval(
            "SELECT COUNT(*) FROM positions "
            "WHERE user_id = $1::uuid AND status IN ('open','pending_settlement')",
            target_uuid,
        ) or 0
    email = u_row["email"]
    if email and email.endswith("@telegram.local"):
        email = None
    return AdminUserDetail(
        user_id=str(u_row["id"]),
        username=u_row["username"],
        email=email,
        role=str(u_row["role"]),
        created_at=u_row["created_at"],
        trading_mode=str(s_row["trading_mode"]) if s_row else "paper",
        auto_trade_on=bool(u_row["auto_trade_on"]),
        paused=bool(u_row["paused"]),
        open_positions=int(open_count),
        balance_usdc=float(w_row["balance_usdc"]) if w_row else 0.0,
        active_preset=s_row["active_preset"] if s_row else None,
        risk_profile=str(s_row["risk_profile"]) if s_row else "balanced",
        capital_alloc_pct=float(s_row["capital_alloc_pct"]) if s_row else 0.40,
        tp_pct=float(s_row["tp_pct"]) if s_row and s_row["tp_pct"] is not None else None,
        sl_pct=float(s_row["sl_pct"]) if s_row and s_row["sl_pct"] is not None else None,
        max_per_trade_mode=str(s_row["max_per_trade_mode"]) if s_row else "auto",
        max_per_trade_usdc=float(s_row["max_per_trade_usdc"]) if s_row and s_row["max_per_trade_usdc"] is not None else None,
        max_per_trade_pct=float(s_row["max_per_trade_pct"]) if s_row and s_row["max_per_trade_pct"] is not None else None,
        selected_timeframe=s_row["selected_timeframe"] if s_row else None,
        selected_assets=list(s_row["selected_assets"]) if s_row and s_row["selected_assets"] else None,
    )


_NOT_NULL_PATCH_FIELDS: frozenset[str] = frozenset({
    "risk_profile", "capital_alloc_pct", "max_per_trade_mode",
})


def _validate_admin_user_patch(body: AdminUserUpdate) -> None:
    """Per-field bounds check. Raises HTTPException(400) on the first miss."""
    # Reject explicit-null on columns the DB declares NOT NULL — otherwise the
    # upsert below would attempt to write NULL into risk_profile /
    # capital_alloc_pct / max_per_trade_mode and 500 with an asyncpg
    # IntegrityError. The user-facing endpoints can't reach these columns
    # with a null because their schemas type the field as a non-Optional
    # value; the admin schema marks them Optional for the "leave alone"
    # pattern, so we have to enforce the NOT NULL contract here.
    explicit_fields = body.model_dump(exclude_unset=True)
    for col in _NOT_NULL_PATCH_FIELDS:
        if col in explicit_fields and explicit_fields[col] is None:
            raise HTTPException(
                status_code=400,
                detail=f"{col} cannot be null (column is NOT NULL — omit the "
                       f"field to leave it unchanged)",
            )
    if body.active_preset is not None and body.active_preset not in _PRESET_TO_STRATEGY:
        raise HTTPException(
            status_code=400,
            detail=f"invalid active_preset: {body.active_preset}. "
                   f"Must be one of {sorted(_PRESET_TO_STRATEGY.keys())}",
        )
    if body.risk_profile is not None and body.risk_profile not in _VALID_RISK_PROFILES:
        raise HTTPException(
            status_code=400,
            detail=f"invalid risk_profile: {body.risk_profile}. "
                   f"Must be one of {sorted(_VALID_RISK_PROFILES)}",
        )
    if body.capital_alloc_pct is not None:
        if not (_CAPITAL_ALLOC_PCT_MIN <= body.capital_alloc_pct <= _CAPITAL_ALLOC_PCT_MAX):
            raise HTTPException(
                status_code=400,
                detail=f"capital_alloc_pct out of range "
                       f"[{_CAPITAL_ALLOC_PCT_MIN}, {_CAPITAL_ALLOC_PCT_MAX}]",
            )
    if body.tp_pct is not None and not (_TP_PCT_MIN <= body.tp_pct <= _TP_PCT_MAX):
        raise HTTPException(
            status_code=400,
            detail=f"tp_pct out of range [{_TP_PCT_MIN}, {_TP_PCT_MAX}]",
        )
    if body.sl_pct is not None and not (_SL_PCT_MIN <= body.sl_pct <= _SL_PCT_MAX):
        raise HTTPException(
            status_code=400,
            detail=f"sl_pct out of range [{_SL_PCT_MIN}, {_SL_PCT_MAX}]",
        )
    if body.max_per_trade_mode is not None and body.max_per_trade_mode not in _VALID_MAX_PER_TRADE_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"invalid max_per_trade_mode: {body.max_per_trade_mode}. "
                   f"Must be one of {sorted(_VALID_MAX_PER_TRADE_MODES)}",
        )
    if body.max_per_trade_usdc is not None and not (
        _MAX_PER_TRADE_USDC_MIN <= body.max_per_trade_usdc <= _MAX_PER_TRADE_USDC_MAX
    ):
        raise HTTPException(
            status_code=400,
            detail=f"max_per_trade_usdc out of range "
                   f"[{_MAX_PER_TRADE_USDC_MIN}, {_MAX_PER_TRADE_USDC_MAX}]",
        )
    if body.max_per_trade_pct is not None and not (
        _MAX_PER_TRADE_PCT_MIN <= body.max_per_trade_pct <= _MAX_PER_TRADE_PCT_MAX
    ):
        raise HTTPException(
            status_code=400,
            detail=f"max_per_trade_pct out of range "
                   f"[{_MAX_PER_TRADE_PCT_MIN}, {_MAX_PER_TRADE_PCT_MAX}]",
        )


@router.patch(
    "/admin/users/{user_id}",
    response_model=AdminUserDetail,
    dependencies=[Depends(per_user_rate_limit("admin_user_patch", limit=60))],
)
async def admin_user_update(
    user_id: str,
    body: AdminUserUpdate,
    user: _AdminUser,
) -> AdminUserDetail:
    """Partial update of a user's bot settings (operator override).

    Only fields explicitly provided in the request body are written. Skipped
    fields are left untouched (COALESCE-style). Every successful call is
    audit-logged with the actor admin's user_id, the target user_id, and the
    full patch payload so post-hoc operator review can attribute changes.

    Returns the freshly-fetched AdminUserDetail so the client can re-render
    without a second round-trip.
    """
    try:
        target_uuid = UUID(user_id)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(status_code=400, detail="invalid user_id") from exc
    _validate_admin_user_patch(body)

    # Build the field list dynamically so unset fields are NOT overwritten —
    # COALESCE($n, col) would not work for nullable-by-design fields like
    # tp_pct (a legitimate "clear it to None" edit is indistinguishable from
    # "leave it alone" through COALESCE).
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="empty patch body")

    pool = get_pool()
    async with pool.acquire() as conn:
        # 404 guard — fail before touching user_settings so we never lazy-
        # create a row for a non-existent user.
        exists = await conn.fetchval(
            "SELECT 1 FROM users WHERE id = $1::uuid", target_uuid,
        )
        if not exists:
            raise HTTPException(status_code=404, detail="user not found")

        set_clauses = [f"{col} = ${i + 2}" for i, col in enumerate(fields.keys())]
        values = list(fields.values())
        # Upsert so an operator edit on a brand-new user (no user_settings
        # row yet) creates the row with explicit paper-mode + balanced defaults
        # per the paper-default invariant.
        insert_cols = ["user_id"] + list(fields.keys())
        insert_vals = ["$1::uuid"] + [f"${i + 2}" for i in range(len(fields))]
        if "trading_mode" not in fields:
            insert_cols.append("trading_mode")
            insert_vals.append("'paper'")
        if "risk_profile" not in fields:
            insert_cols.append("risk_profile")
            insert_vals.append("'balanced'")
        if "capital_alloc_pct" not in fields:
            insert_cols.append("capital_alloc_pct")
            insert_vals.append("0.40")
        sql = (
            f"INSERT INTO user_settings ({', '.join(insert_cols)}) "
            f"VALUES ({', '.join(insert_vals)}) "
            f"ON CONFLICT (user_id) DO UPDATE SET "
            f"{', '.join(set_clauses)}, updated_at = NOW()"
        )
        await conn.execute(sql, target_uuid, *values)

    await audit.write(
        actor_role="admin",
        action="admin_user_settings_update",
        user_id=UUID(str(user["user_id"])),
        payload={"target_user_id": str(target_uuid), "patch": fields},
    )
    return await admin_user_detail(str(target_uuid), user)
