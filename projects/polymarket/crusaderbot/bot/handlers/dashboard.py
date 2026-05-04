"""Dashboard / Positions / Activity views."""
from __future__ import annotations

from decimal import Decimal

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...database import get_pool
from ...users import set_auto_trade, upsert_user
from ...wallet.ledger import daily_pnl, get_balance
from ..keyboards import autotrade_toggle
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


async def dashboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user, ok = await _ensure(update, Tier.ALLOWLISTED)
    if not ok or update.message is None:
        return
    bal = await get_balance(user["id"])
    pnl = await daily_pnl(user["id"])
    pool = get_pool()
    async with pool.acquire() as conn:
        cnt = await conn.fetchval(
            "SELECT COUNT(*) FROM positions WHERE user_id=$1 AND status='open'",
            user["id"],
        )
    auto = user["auto_trade_on"]
    text = (
        "*📊 Dashboard*\n\n"
        f"USDC balance: *${bal:.2f}*\n"
        f"Today's P&L: *${pnl:+.2f}*\n"
        f"Open positions: *{cnt}*\n"
        f"Auto-trade: {'✅ ON' if auto else '❌ OFF'}\n"
        f"Tier: *{user['access_tier']}*\n"
    )
    if has_tier(user["access_tier"], Tier.FUNDED):
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN,
                                        reply_markup=autotrade_toggle(auto))
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


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
    from ...integrations.polymarket import get_market
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
