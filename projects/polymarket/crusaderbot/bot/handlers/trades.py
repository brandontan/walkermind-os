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
            """SELECT p.id, p.market_id, m.question AS market_question, p.side, p.entry_price,
                      p.size_usdc, p.current_price, p.opened_at
               FROM positions p
               LEFT JOIN markets m ON m.id = p.market_id
               WHERE p.user_id = $1 AND p.status = 'open'
               ORDER BY p.opened_at DESC
               LIMIT 10""",
            user_id,
        )
        closed_rows = await conn.fetch(
            """SELECT m.question AS market_question, p.pnl_usdc, p.closed_at
               FROM positions p
               LEFT JOIN markets m ON m.id = p.market_id
               WHERE p.user_id = $1 AND p.status = 'closed'
               ORDER BY p.closed_at DESC
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
    try:
        open_pos, recent_closed = await _fetch_trades(user["id"])
    except Exception as exc:
        logger.error("show_trades fetch failed user=%s err=%s", user["id"], exc)
        open_pos, recent_closed = [], []

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

    # Trades screen: history view only — no Close buttons (those live in Positions)
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📋 Full History", callback_data="p5:trades:history"),
        InlineKeyboardButton("⬅ Portfolio",     callback_data="portfolio:portfolio"),
    ]])

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

async def _fetch_mark_price(token_id: str | None) -> float | None:
    """Fetch CLOB midpoint with a 3 s budget. Returns None on timeout or empty book."""
    if not token_id:
        return None
    import asyncio
    from ...integrations.polymarket import get_book
    try:
        book = await asyncio.wait_for(get_book(token_id), timeout=3.0)
    except Exception:
        return None
    bids = book.get("bids") or []
    asks = book.get("asks") or []
    try:
        bid = float(bids[0]["price"]) if bids else None
        ask = float(asks[0]["price"]) if asks else None
    except (KeyError, TypeError, ValueError):
        return None
    if bid is not None and ask is not None:
        return (bid + ask) / 2.0
    return bid if bid is not None else ask


def _paper_pnl(side: str, entry: float, mark: float, size_usdc: float) -> tuple[float, float]:
    """Return (pnl_usdc, pnl_pct) matching paper.py formula."""
    if entry <= 0:
        return 0.0, 0.0
    if side == "yes":
        ret_pct = (mark - entry) / max(entry, 1e-6)
    else:
        comp_entry = 1 - entry
        comp_exit = 1 - mark
        ret_pct = (comp_exit - comp_entry) / max(comp_entry, 1e-6)
    pnl = size_usdc * ret_pct
    pct = ret_pct * 100.0
    return pnl, pct


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

    user = await upsert_user(update.effective_user.id, update.effective_user.username)

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT m.question AS market_question, p.entry_price, p.current_price,
                      p.size_usdc, p.side, p.mode, m.yes_token_id, m.no_token_id
               FROM positions p
               LEFT JOIN markets m ON m.id = p.market_id
               WHERE p.id = $1 AND p.user_id = $2 AND p.status = 'open'""",
            pos_id, user["id"],
        )
    if row is None:
        await q.answer("Position not found or already closed.", show_alert=True)
        return

    entry = float(row["entry_price"] or 0)
    size = float(row["size_usdc"] or 0)
    side = row["side"] or "yes"

    # Try live mark price first; fall back to stored current_price, then entry.
    token_id = row["yes_token_id"] if side == "yes" else row["no_token_id"]
    mark = await _fetch_mark_price(token_id)
    if mark is None and row["current_price"] is not None:
        mark = float(row["current_price"])

    if mark is not None and entry > 0:
        pnl, pnl_pct = _paper_pnl(side, entry, mark, size)
    else:
        pnl, pnl_pct = 0.0, 0.0

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

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT p.id, p.user_id, p.market_id, p.side, p.size_usdc,
                      p.entry_price, p.current_price, p.mode, m.yes_token_id, m.no_token_id
               FROM positions p
               LEFT JOIN markets m ON m.id = p.market_id
               WHERE p.id = $1 AND p.user_id = $2 AND p.status = 'open'""",
            UUID(pos_id), user["id"],
        )
    if row is None:
        await _safe_edit(
            q, "ℹ️ Position already closed or not found.",
            parse_mode=ParseMode.HTML, reply_markup=trades_kb(),
        )
        return

    if row["mode"] == "paper":
        # Paper positions: close immediately via paper engine.
        token_id = row["yes_token_id"] if row["side"] == "yes" else row["no_token_id"]
        mark = await _fetch_mark_price(token_id)
        if mark is None and row["current_price"] is not None:
            mark = float(row["current_price"])
        exit_price = mark if mark is not None else float(row["entry_price"])

        try:
            from ...domain.execution import paper as paper_exec
            result = await paper_exec.close_position(
                position=dict(row),
                exit_price=exit_price,
                exit_reason="manual",
            )
            realized = float(result.get("pnl_usdc", 0))
            sign = "+" if realized > 0 else ""
            msg = f"✅ Position closed. Realized P&L: {sign}${realized:.2f}"
        except Exception as exc:
            logger.error("close_confirm_cb paper close failed pos=%s err=%s", pos_id, exc)
            msg = "⚠️ Could not close position. Please try again."
    else:
        # Live positions: queue force-close via exit watcher marker.
        try:
            from .emergency import mark_force_close_intent_for_position
            updated = await mark_force_close_intent_for_position(
                UUID(pos_id), user["id"],
            )
            msg = ("✅ Position queued for close." if updated
                   else "ℹ️ Position already closing or not found.")
        except Exception as exc:
            logger.error("close_confirm_cb live close failed pos=%s err=%s", pos_id, exc)
            msg = "⚠️ Could not queue close. Please try again."

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
            """SELECT m.question AS market_question, p.side, p.pnl_usdc, p.size_usdc, p.closed_at
               FROM positions p
               LEFT JOIN markets m ON m.id = p.market_id
               WHERE p.user_id = $1 AND p.status = 'closed'
               ORDER BY p.closed_at DESC LIMIT 20""",
            user["id"],
        )
    if not rows:
        await _safe_edit(
            q, "<b>📋 Full History</b>\n\nNo closed trades yet.",
            parse_mode=ParseMode.HTML, reply_markup=trades_kb(),
        )
        return

    lines = ["<b>📋 Full History</b>", "━━━━━━━━━━━━━━━━━━━━━━━━━━", ""]
    for r in rows:
        pnl = float(r["pnl_usdc"] or 0)
        emoji = "✅" if pnl >= 0 else "❌"
        sign = "+" if pnl >= 0 else ""
        q_text = (r["market_question"] or "Unknown")[:50]
        lines.append(f"{emoji} {q_text}")
        lines.append(f"   {r['side'].upper()} | {sign}${pnl:.2f}")

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
