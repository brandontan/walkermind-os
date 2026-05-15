"""Phase 5 UX Rebuild — My Trades (Screen 05 + 06).

Trigger: menu:trades callback.
Shows open positions + recent closed trades.
Close position pattern: close_position:{position_id}
"""
from __future__ import annotations

import logging
from uuid import UUID

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from ...database import get_pool
from ...users import upsert_user
from ..keyboards import close_confirm_kb, close_position_kb, trades_empty_kb, trades_kb
from ..messages import close_confirm_text, trades_empty_text, trades_text

logger = logging.getLogger(__name__)


async def _fetch_trades(user_id: UUID) -> tuple[list[dict], list[dict]]:
    """Return (open_positions, recent_closed)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        open_rows = await conn.fetch(
            """SELECT id, market_id, market_question, side, entry_price,
                      size_usdc, current_price, opened_at
               FROM positions
               WHERE user_id = $1 AND status = 'open'
               ORDER BY opened_at DESC
               LIMIT 10""",
            user_id,
        )
        closed_rows = await conn.fetch(
            """SELECT market_question, pnl_usdc, closed_at
               FROM positions
               WHERE user_id = $1 AND status = 'closed'
               ORDER BY closed_at DESC
               LIMIT 5""",
            user_id,
        )
    return [dict(r) for r in open_rows], [dict(r) for r in closed_rows]


async def _safe_edit(q, text: str, **kwargs) -> None:
    try:
        await q.edit_message_text(text, **kwargs)
    except BadRequest as exc:
        if "Message is not modified" not in str(exc):
            await q.message.reply_text(text, **kwargs)


async def show_trades(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the trades screen (message or callback)."""
    if update.effective_user is None:
        return
    user = await upsert_user(update.effective_user.id, update.effective_user.username)
    open_pos, recent_closed = await _fetch_trades(user["id"])

    if not open_pos and not recent_closed:
        text = trades_empty_text()
        kb = trades_empty_kb()
        q = update.callback_query
        if q is not None and q.message is not None:
            await _safe_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=kb)
        elif update.message is not None:
            await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    # Build the main trades text
    text = trades_text(open_pos, recent_closed)

    # Build keyboard: per-position [🛑 Close] rows + nav row
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    rows = []
    for pos in open_pos:
        pos_id = str(pos.get("id", ""))
        q_text = (pos.get("market_question") or "Position")[:40]
        rows.append([InlineKeyboardButton(
            f"🛑 Close: {q_text}",
            callback_data=f"close_position:{pos_id}",
        )])
    rows.append([
        InlineKeyboardButton("📋 Full History", callback_data="p5:trades:history"),
        InlineKeyboardButton("📊 Dashboard",    callback_data="menu:dashboard"),
    ])
    kb = InlineKeyboardMarkup(rows)

    q = update.callback_query
    if q is not None and q.message is not None:
        await _safe_edit(q, text, parse_mode=ParseMode.HTML, reply_markup=kb)
    elif update.message is not None:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def my_trades(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Command handler alias."""
    await show_trades(update, ctx)


async def my_trades_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback handler alias."""
    await show_trades(update, ctx)


# ── Close position flow ────────────────────────────────────────────────────────

async def close_ask_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Pattern: close_position:{position_id} — show confirmation dialog."""
    q = update.callback_query
    if q is None or update.effective_user is None:
        return
    await q.answer()
    data = q.data or ""
    # Handle both "close_position:{id}" and "position:close:{id}" (legacy)
    if data.startswith("close_position:"):
        pos_id = data[len("close_position:"):]
    elif data.startswith("position:close:"):
        pos_id = data[len("position:close:"):]
    else:
        return

    # Skip the confirm step if it's already a confirmed close
    if pos_id.startswith("confirm:"):
        await close_confirm_cb(update, ctx)
        return

    if update.effective_user is None:
        return
    user = await upsert_user(update.effective_user.id, update.effective_user.username)

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT market_question, entry_price, current_price, size_usdc
               FROM positions WHERE id = $1 AND user_id = $2 AND status = 'open'""",
            pos_id, user["id"],
        )
    if row is None:
        await q.answer("Position not found or already closed.", show_alert=True)
        return

    entry = float(row["entry_price"] or 0)
    current = float(row["current_price"] or entry)
    pnl = (current - entry) * float(row["size_usdc"] or 0)
    pnl_pct = ((current - entry) / entry * 100) if entry else 0.0

    text = close_confirm_text(row["market_question"] or "Unknown market", pnl, pnl_pct)
    await _safe_edit(
        q, text,
        parse_mode=ParseMode.HTML,
        reply_markup=close_confirm_kb(pos_id),
    )


async def close_confirm_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Pattern: close_position:confirm:{position_id} — execute close."""
    q = update.callback_query
    if q is None or update.effective_user is None:
        return
    await q.answer()
    data = q.data or ""

    if data.startswith("close_position:confirm:"):
        pos_id = data[len("close_position:confirm:"):]
    else:
        return

    user = await upsert_user(update.effective_user.id, update.effective_user.username)

    try:
        from ...domain.positions import registry as position_registry
        updated = await position_registry.mark_force_close_intent_for_position(
            UUID(pos_id), user["id"],
        )
        if updated:
            msg = "✅ Position queued for close."
        else:
            msg = "ℹ️ Position already closing or not found."
    except Exception as exc:
        logger.error("close_confirm_cb failed pos=%s err=%s", pos_id, exc)
        msg = "⚠️ Could not close position. Please try again."

    await _safe_edit(q, msg, parse_mode=ParseMode.HTML, reply_markup=trades_kb())


async def cancel_close_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Pattern: p5:trades:cancel_close — go back to trades screen."""
    q = update.callback_query
    if q is None:
        return
    await q.answer()
    await show_trades(update, ctx)


async def history_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Full trade history — paginated first 20 closed trades."""
    q = update.callback_query
    if q is None or update.effective_user is None:
        return
    await q.answer()
    user = await upsert_user(update.effective_user.id, update.effective_user.username)
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT market_question, side, pnl_usdc, size_usdc, closed_at
               FROM positions
               WHERE user_id = $1 AND status = 'closed'
               ORDER BY closed_at DESC LIMIT 20""",
            user["id"],
        )
    if not rows:
        await _safe_edit(
            q, "<b>📋 Full History</b>\n\nNo closed trades yet.",
            parse_mode=ParseMode.HTML, reply_markup=trades_kb(),
        )
        return

    lines = ["<b>📋 Full History</b>", "━━━━━━━━━━━━━━━━━━━━━━━━", ""]
    for r in rows:
        pnl = float(r["pnl_usdc"] or 0)
        emoji = "✅" if pnl >= 0 else "❌"
        sign = "+" if pnl >= 0 else ""
        q_text = (r["market_question"] or "Unknown")[:50]
        lines.append(f"{emoji} {q_text}")
        lines.append(f"<pre>   {r['side'].upper()} | {sign}${pnl:.2f}</pre>")

    await _safe_edit(
        q, "\n".join(lines),
        parse_mode=ParseMode.HTML, reply_markup=trades_kb(),
    )


# ── Backward-compat shims for dispatcher ──────────────────────────────────────

async def close_ask_legacy_cb(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Legacy pattern: mytrades:close_ask:{id}"""
    q = update.callback_query
    if q is None:
        return
    pos_id = (q.data or "").split(":", 2)[-1]
    q._data = f"close_position:{pos_id}"  # type: ignore[attr-defined]
    await close_ask_cb(update, ctx)


async def close_confirm_legacy_cb(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Legacy pattern: mytrades:close_yes:{id} / mytrades:close_no:{id}"""
    q = update.callback_query
    if q is None:
        return
    parts = (q.data or "").split(":")
    if len(parts) < 3:
        return
    action = parts[1]
    pos_id = parts[2]
    if "yes" in action:
        q._data = f"close_position:confirm:{pos_id}"  # type: ignore[attr-defined]
        await close_confirm_cb(update, ctx)
    else:
        await cancel_close_cb(update, ctx)


async def back_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await show_trades(update, ctx)


async def trade_detail_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await show_trades(update, ctx)
