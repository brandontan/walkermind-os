"""Dashboard / Positions / Activity views."""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...database import get_pool
from ...users import get_settings_for, set_auto_trade, upsert_user
from ...wallet.ledger import daily_pnl, get_balance
from ...wallet.vault import get_wallet
from ..keyboards import autotrade_toggle, dashboard_nav, setup_menu, wallet_menu
from ..tier import Tier, has_tier, tier_block_message


async def _ensure(update: Update, min_tier: int) -> tuple[dict | None, bool]:
    if update.effective_user is None:
        return None, False
    user = await upsert_user(update.effective_user.id, update.effective_user.username)
    if not has_tier(user["access_tier"], min_tier):
        msg = tier_block_message(min_tier)
        if update.message:
            await update.message.reply_text(msg)
        elif update.callback_query:
            await update.callback_query.answer(msg, show_alert=True)
        return None, False
    return user, True


async def _fetch_stats(user_id: UUID) -> dict:
    """All supplementary dashboard data in one connection."""
    pool = get_pool()
    async with pool.acquire() as conn:
        pos = await conn.fetchrow(
            """
            SELECT
                COALESCE(SUM(size_usdc), 0) AS positions_value,
                COUNT(*) FILTER (WHERE current_price IS NOT NULL
                                   AND current_price > entry_price) AS winning,
                COUNT(*) FILTER (WHERE current_price IS NOT NULL
                                   AND current_price < entry_price) AS losing
            FROM positions
            WHERE user_id = $1 AND status = 'open'
            """,
            user_id,
        )
        trades = await conn.fetchrow(
            """
            SELECT
                COUNT(*)                                        AS total_trades,
                COUNT(*) FILTER (WHERE pnl_usdc > 0)           AS wins,
                COUNT(*) FILTER (WHERE pnl_usdc IS NOT NULL
                                   AND pnl_usdc <= 0)          AS losses,
                COALESCE(SUM(size_usdc), 0)                    AS total_volume,
                COUNT(DISTINCT market_id)                       AS markets_traded
            FROM positions
            WHERE user_id = $1 AND status != 'open'
            """,
            user_id,
        )
        pnl = await conn.fetchrow(
            """
            SELECT
                COALESCE(SUM(amount_usdc) FILTER (
                    WHERE type IN ('trade_close','redeem','fee')
                      AND created_at >= NOW() - INTERVAL '7 days'), 0)  AS pnl_7d,
                COALESCE(SUM(amount_usdc) FILTER (
                    WHERE type IN ('trade_close','redeem','fee')
                      AND created_at >= NOW() - INTERVAL '30 days'), 0) AS pnl_30d,
                COALESCE(SUM(amount_usdc) FILTER (
                    WHERE type IN ('trade_close','redeem','fee')), 0)    AS pnl_all
            FROM ledger
            WHERE user_id = $1
            """,
            user_id,
        )
        sett = await conn.fetchrow(
            "SELECT risk_profile, strategy_types, trading_mode "
            "FROM user_settings WHERE user_id = $1",
            user_id,
        )
    return {
        "positions_value": Decimal(str(pos["positions_value"])),
        "winning":         int(pos["winning"]),
        "losing":          int(pos["losing"]),
        "total_trades":    int(trades["total_trades"]),
        "wins":            int(trades["wins"]),
        "losses":          int(trades["losses"]),
        "total_volume":    Decimal(str(trades["total_volume"])),
        "markets_traded":  int(trades["markets_traded"]),
        "pnl_7d":          Decimal(str(pnl["pnl_7d"])),
        "pnl_30d":         Decimal(str(pnl["pnl_30d"])),
        "pnl_all":         Decimal(str(pnl["pnl_all"])),
        "risk_profile":    sett["risk_profile"]   if sett else "balanced",
        "strategy_types":  sett["strategy_types"] if sett else ["copy_trade"],
        "trading_mode":    sett["trading_mode"]   if sett else "paper",
    }


def _pnl_line(val: Decimal, base: Decimal | None = None) -> str:
    sign = "+" if val >= 0 else ""
    pct = ""
    if base and base > 0:
        pct = f" ({sign}{float(val) / float(base) * 100:.1f}%)"
    return f"{sign}${val:.2f}{pct}"


def _risk_icon(profile: str) -> str:
    return {"conservative": "🟢", "balanced": "🟡", "aggressive": "🔴"}.get(profile, "🟡")


def _build_text(
    bal: Decimal,
    pnl_today: Decimal,
    st: dict,
    auto_on: bool,
) -> str:
    equity = bal + st["positions_value"]
    closed_total = st["wins"] + st["losses"]
    win_rate = int(st["wins"] / closed_total * 100) if closed_total else 0

    pnl_all = st["pnl_all"]
    pnl_all_str = f"+${pnl_all:.2f}" if pnl_all >= 0 else f"-${abs(pnl_all):.2f}"

    auto_status = "🟢 ACTIVE" if auto_on else "⚪ INACTIVE"
    strats = st["strategy_types"]
    preset = (
        ", ".join(s.replace("_", " ").title() for s in strats)
        if strats else "Not configured"
    )
    risk_icon = _risk_icon(st["risk_profile"])
    risk_label = st["risk_profile"].title()
    mode_label = "🔴 Live" if st["trading_mode"] == "live" else "📝 Paper"

    return (
        "📊 *CrusaderBot Dashboard*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "💼 *Portfolio*\n"
        f"├─ Balance: ${bal:.2f}\n"
        f"├─ Positions Value: ${st['positions_value']:.2f}\n"
        f"├─ Total Equity: ${equity:.2f}\n"
        f"└─ Winning: {st['winning']} | Losing: {st['losing']}\n\n"
        "💰 *Profit & Loss*\n"
        f"├─ Today: {_pnl_line(pnl_today, bal)}\n"
        f"├─ 7 Day: {_pnl_line(st['pnl_7d'], bal)}\n"
        f"├─ 30 Day: {_pnl_line(st['pnl_30d'], bal)}\n"
        f"└─ All-Time: {pnl_all_str}\n\n"
        "📈 *Trading Stats*\n"
        f"├─ Total Trades: {st['total_trades']}\n"
        f"├─ Win Rate: {win_rate}% ({st['wins']}W / {st['losses']}L)\n"
        f"├─ Total Volume: ${st['total_volume']:.2f}\n"
        f"└─ Markets Traded: {st['markets_traded']}\n\n"
        "🤖 *Auto-Trade*\n"
        f"├─ Status: {auto_status}\n"
        f"├─ Preset: {preset}\n"
        f"├─ Risk: {risk_icon} {risk_label}\n"
        f"└─ Mode: {mode_label}"
    )


async def dashboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user, ok = await _ensure(update, Tier.ALLOWLISTED)
    if not ok or update.message is None:
        return

    bal = await get_balance(user["id"])
    pnl_today = await daily_pnl(user["id"])
    st = await _fetch_stats(user["id"])

    text = _build_text(bal, pnl_today, st, user["auto_trade_on"])
    has_trades = st["total_trades"] > 0 or (st["winning"] + st["losing"]) > 0

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=dashboard_nav(has_trades),
    )


async def dashboard_nav_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles dashboard inline nav: [🤖 Auto-Trade] [📈 Trades] [💰 Wallet] [📊 main]."""
    q = update.callback_query
    if q is None:
        return
    await q.answer()

    sub = (q.data or "").split(":", 1)[-1]
    user, ok = await _ensure(update, Tier.ALLOWLISTED)
    if not ok:
        return

    if sub == "main":
        bal = await get_balance(user["id"])
        pnl_today = await daily_pnl(user["id"])
        st = await _fetch_stats(user["id"])
        text = _build_text(bal, pnl_today, st, user["auto_trade_on"])
        has_trades = st["total_trades"] > 0 or (st["winning"] + st["losing"]) > 0
        await q.message.reply_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=dashboard_nav(has_trades),
        )
        return

    if sub == "autotrade":
        s = await get_settings_for(user["id"])
        text = (
            "*🤖 Auto-Trade Setup*\n\n"
            f"Strategy: `{', '.join(s['strategy_types'])}`\n"
            f"Risk profile: `{s['risk_profile']}`\n"
            f"Capital alloc: `{float(s['capital_alloc_pct']) * 100:.0f}%`\n"
            f"Mode: `{s['trading_mode']}`\n"
        )
        await q.message.reply_text(text, parse_mode=ParseMode.MARKDOWN,
                                   reply_markup=setup_menu())

    elif sub == "trades":
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT p.side, p.size_usdc, p.pnl_usdc, p.status,
                       m.question, p.market_id
                  FROM positions p
                  LEFT JOIN markets m ON m.id = p.market_id
                 WHERE p.user_id = $1
                 ORDER BY COALESCE(p.closed_at, p.opened_at) DESC
                 LIMIT 10
                """,
                user["id"],
            )
        if not rows:
            await q.message.reply_text(
                "No trades yet. Tap 🤖 Auto-Trade to configure and start."
            )
            return
        lines = ["*📈 Recent Trades:*\n"]
        for r in rows:
            title = (r["question"] or r["market_id"])[:40]
            pnl = (
                f" P&L: *${float(r['pnl_usdc']):+.2f}*"
                if r["pnl_usdc"] is not None else ""
            )
            lines.append(
                f"*{r['side'].upper()}* ${float(r['size_usdc']):.2f} "
                f"[{r['status']}]{pnl}\n_{title}_"
            )
        await q.message.reply_text(
            "\n\n".join(lines), parse_mode=ParseMode.MARKDOWN,
        )

    elif sub == "wallet":
        bal = await get_balance(user["id"])
        w = await get_wallet(user["id"])
        addr = w["deposit_address"] if w else "(not set)"
        await q.message.reply_text(
            f"*💰 Wallet*\n\nBalance: *${bal:.2f}* USDC\n\nDeposit address (Polygon):\n`{addr}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=wallet_menu(),
        )

    elif sub == "insights":
        from .pnl_insights import _fetch_insights, format_insights
        from ..keyboards import insights_kb
        data = await _fetch_insights(user["id"])
        await q.message.reply_text(
            format_insights(data),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=insights_kb(),
        )


async def autotrade_toggle_cb(update: Update,
                              ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q is None:
        return
    await q.answer()
    user, ok = await _ensure(update, Tier.FUNDED)
    if not ok:
        return
    new_state = not user["auto_trade_on"]
    if new_state and user.get("locked", False):
        await q.answer("Account locked. Contact an operator to unlock.", show_alert=True)
        return
    from .activation import autotrade_toggle_pending_confirm
    if await autotrade_toggle_pending_confirm(update, ctx):
        return
    await set_auto_trade(user["id"], new_state)
    await q.message.reply_text(
        f"Auto-trade is now *{'ON' if new_state else 'OFF'}*.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def positions(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user, ok = await _ensure(update, Tier.ALLOWLISTED)
    if not ok or update.message is None:
        return
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT p.id, p.market_id, p.side, p.size_usdc, p.entry_price,
                   p.current_price, p.mode, p.opened_at, m.question
              FROM positions p
              LEFT JOIN markets m ON m.id = p.market_id
             WHERE p.user_id=$1 AND p.status='open'
             ORDER BY p.opened_at DESC LIMIT 25
            """,
            user["id"],
        )
    if not rows:
        await update.message.reply_text("No open positions.")
        return
    lines = ["*📈 Open positions:*\n"]
    buttons = []
    for r in rows:
        q = (r["question"] or r["market_id"])[:48]
        lines.append(
            f"`{str(r['id'])[:8]}` *{r['side'].upper()}* @ "
            f"{float(r['entry_price']):.3f} · ${float(r['size_usdc']):.2f} "
            f"[{r['mode']}]\n_{q}_"
        )
        buttons.append([InlineKeyboardButton(
            f"🛑 Close {str(r['id'])[:6]}",
            callback_data=f"position:close:{r['id']}",
        )])
    await update.message.reply_text(
        "\n\n".join(lines), parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def close_position_cb(update: Update,
                            ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from ...domain.execution.router import close
    q = update.callback_query
    if q is None:
        return
    await q.answer("Closing…")
    user, ok = await _ensure(update, Tier.ALLOWLISTED)
    if not ok:
        return
    pos_id = (q.data or "").split(":", 2)[-1]
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM positions WHERE id=$1 AND user_id=$2 AND status='open'",
            pos_id, user["id"],
        )
        if not row:
            await q.message.reply_text("Position not found or already closed.")
            return
        market = await conn.fetchrow(
            "SELECT yes_price, no_price FROM markets WHERE id=$1", row["market_id"],
        )
    exit_price = float(
        (market["yes_price"] if row["side"] == "yes" else market["no_price"])
        if market else row["entry_price"]
    )
    res = await close(position=dict(row), exit_price=exit_price,
                      exit_reason="user_close")
    await q.message.reply_text(
        f"📉 *Closed* `{str(pos_id)[:8]}` @ {exit_price:.3f}\n"
        f"P&L: *${float(res['pnl_usdc']):+.2f}*",
        parse_mode=ParseMode.MARKDOWN,
    )


async def activity(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user, ok = await _ensure(update, Tier.ALLOWLISTED)
    if not ok or update.message is None:
        return
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT o.id, o.market_id, o.side, o.size_usdc, o.price, o.mode,
                   o.status, o.created_at, m.question
              FROM orders o
              LEFT JOIN markets m ON m.id = o.market_id
             WHERE o.user_id=$1
             ORDER BY o.created_at DESC LIMIT 10
            """,
            user["id"],
        )
    if not rows:
        await update.message.reply_text("No activity yet.")
        return
    lines = ["*📋 Last 10 trades:*\n"]
    for r in rows:
        q = (r["question"] or r["market_id"])[:40]
        lines.append(
            f"{r['created_at'].strftime('%m-%d %H:%M')} · "
            f"*{r['side'].upper()}* @ {float(r['price']):.3f} · "
            f"${float(r['size_usdc']):.2f} [{r['mode']}/{r['status']}]\n_{q}_"
        )
    await update.message.reply_text("\n\n".join(lines),
                                    parse_mode=ParseMode.MARKDOWN)
