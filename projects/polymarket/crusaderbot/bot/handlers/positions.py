"""Live position monitor + per-position force-close UX (R12d).

Surfaces:
  show_positions(update, ctx)      — text 📈 Positions OR /positions
                                     Lists every open position with mark
                                     price, unrealized P&L, applied TP/SL.
                                     Each row carries a [🛑 Force Close]
                                     inline button.
  force_close_ask(update, ctx)     — first tap on 🛑 Force Close → emits a
                                     confirmation dialog.
  force_close_confirm(update, ctx) — confirm dialog → flips
                                     ``force_close_intent = TRUE`` on the
                                     single chosen position via
                                     emergency.mark_force_close_intent_for_position.

Tier gates:
  * View    — Tier 2 (ALLOWLISTED) minimum
  * Force close — Tier 3 (FUNDED) minimum

Mark-price source:
  CLOB orderbook midpoint via integrations.polymarket.get_book, hard-capped
  at 3.0 s per fetch. On timeout / empty book we degrade gracefully to
  "price unavailable" rather than crashing the handler.

This handler does NOT execute trades or call the close router. Force close
is a marker write — the existing exit watcher (R12c) sees the flag on its
next tick and drives the close pipeline via the priority chain
(force_close_intent > tp_hit > sl_hit > strategy_exit > hold).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from decimal import Decimal

from ...database import get_pool
from ...integrations.polymarket import get_book
from ...users import upsert_user
from ...wallet.ledger import daily_pnl, get_balance
from ..keyboards import main_menu, portfolio_kb
from ..keyboards.positions import force_close_confirm_kb, positions_list_kb

from .emergency import mark_force_close_intent_for_position

logger = logging.getLogger(__name__)

PRICE_FETCH_TIMEOUT_SEC = 3.0
MARKET_TITLE_MAX = 40


async def _ensure_tier(update: Update, _min_tier: int = 0) -> tuple[Optional[dict], bool]:
    """All registered users pass — no tier gate. Calls local upsert_user for testability."""
    if update.effective_user is None:
        return None, False
    user = await upsert_user(update.effective_user.id, update.effective_user.username)
    return user, True


async def _fetch_mark_price(token_id: Optional[str]) -> Optional[float]:
    """CLOB midpoint for ``token_id`` with a 3 s wall-clock budget.

    Returns None if no token_id, request times out, or book is empty —
    the handler renders "price unavailable" in that case.
    """
    if not token_id:
        return None
    try:
        book = await asyncio.wait_for(
            get_book(token_id), timeout=PRICE_FETCH_TIMEOUT_SEC
        )
    except asyncio.TimeoutError:
        logger.warning("mark price fetch timed out: %s", token_id)
        return None
    except Exception as exc:
        logger.warning("mark price fetch failed: %s: %s", token_id, exc)
        return None
    bids = book.get("bids") or []
    asks = book.get("asks") or []
    try:
        best_bid = float(bids[0]["price"]) if bids else None
        best_ask = float(asks[0]["price"]) if asks else None
    except (KeyError, TypeError, ValueError):
        return None
    if best_bid is not None and best_ask is not None:
        return (best_bid + best_ask) / 2.0
    return best_bid if best_bid is not None else best_ask


def _unrealized_pnl(side: str, entry: float, mark: float, size: float) -> tuple[float, float]:
    """Return (pnl_usdc, pnl_pct).

    YES: pnl = (mark - entry) * size_in_shares
    NO : pnl = (entry - mark) * size_in_shares

    ``size`` is stored as USDC notional at entry, so size_in_shares = size / entry.
    Pct uses ``size`` (USDC notional) as the denominator.
    """
    if entry <= 0:
        return 0.0, 0.0
    shares = size / entry
    if side == "yes":
        pnl = (mark - entry) * shares
    else:
        pnl = (entry - mark) * shares
    pct = (pnl / size) * 100.0 if size > 0 else 0.0
    return pnl, pct


def _format_pnl(pnl: float, pct: float) -> str:
    return f"{pnl:+.2f} ({pct:+.1f}%)"


def _format_tp_sl(applied_tp_pct: Optional[float],
                  applied_sl_pct: Optional[float]) -> str:
    parts = []
    if applied_tp_pct is not None:
        parts.append(f"TP {float(applied_tp_pct) * 100:.1f}%")
    if applied_sl_pct is not None:
        parts.append(f"SL {float(applied_sl_pct) * 100:.1f}%")
    return " · ".join(parts) if parts else "TP/SL N/A"


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


async def _load_open_positions(user_id) -> list[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT p.id, p.market_id, p.side, p.size_usdc, p.entry_price,
                   p.applied_tp_pct, p.applied_sl_pct, p.opened_at,
                   m.question, m.yes_token_id, m.no_token_id
              FROM positions p
              LEFT JOIN markets m ON m.id = p.market_id
             WHERE p.user_id = $1 AND p.status = 'open'
             ORDER BY p.opened_at DESC
             LIMIT 25
            """,
            user_id,
        )
    return [dict(r) for r in rows]


def _pnl_fmt(val: Decimal) -> str:
    sign = "+" if val >= 0 else ""
    return f"{sign}${val:.2f}"


async def show_portfolio(update: Update, ctx: ContextTypes.DEFAULT_TYPE, refresh: bool = False) -> None:
    """Portfolio overview screen — handles both message and callback paths."""
    is_cb = update.callback_query is not None
    if is_cb:
        q = update.callback_query
        await q.answer()

    user, ok = await _ensure_tier(update)
    if not ok:
        return
    if not is_cb and update.message is None:
        return

    from .dashboard import _fetch_stats
    bal = await get_balance(user["id"])
    pnl_today = await daily_pnl(user["id"])
    st = await _fetch_stats(user["id"])

    open_count = st.get("open_positions", 0)

    if open_count == 0:
        footer = "No open positions. Use Auto Trade to start."
    else:
        footer = "Tap Positions for full details."

    stats = (
        f"💼 Portfolio\n\n"
        f"💰 Balance: ${bal:.2f} USDC\n"
        f"📈 Today: {_pnl_fmt(pnl_today)}\n"
        f"📋 Open: {open_count}\n\n"
        f"{footer}"
    )

    if is_cb:
        await update.callback_query.message.reply_text(
            stats,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=portfolio_kb(),
        )
    else:
        await update.message.reply_text(
            stats,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=portfolio_kb(),
        )


async def portfolio_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle portfolio:* callbacks from the Portfolio screen keyboard."""
    q = update.callback_query
    if q is None:
        return
    await q.answer()
    sub = (q.data or "").split(":", 1)[-1]

    if sub == "positions":
        await show_positions(update, ctx)
        return

    if sub == "chart":
        from .portfolio_chart import chart_command
        await chart_command(update, ctx)
        return

    if sub == "insights":
        from .pnl_insights import pnl_insights_command
        await pnl_insights_command(update, ctx)
        return

    if sub == "trades":
        from .my_trades import my_trades
        await my_trades(update, ctx)
        return

    # portfolio:portfolio — fallback to portfolio screen itself
    await show_portfolio(update, ctx)


async def show_positions(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the live position monitor (Tier 2+)."""
    user, ok = await _ensure_tier(update)
    if not ok or update.message is None:
        return

    positions = await _load_open_positions(user["id"])
    if not positions:
        await update.message.reply_text("No open positions.")
        return

    # Fetch mark prices in parallel — total wall-clock capped at the per-call
    # 3 s budget because gather runs them concurrently.
    token_ids = [
        (p["yes_token_id"] if p["side"] == "yes" else p["no_token_id"])
        for p in positions
    ]
    marks = await asyncio.gather(
        *(_fetch_mark_price(tid) for tid in token_ids),
        return_exceptions=False,
    )

    lines = ["📌 Open Positions\n"]
    n = len(positions)
    for i, (pos, mark) in enumerate(zip(positions, marks)):
        connector = "└" if i == n - 1 else "├"
        title = _truncate(pos["question"] or pos["market_id"], MARKET_TITLE_MAX)
        side = pos["side"].upper()
        entry = float(pos["entry_price"])
        size = float(pos["size_usdc"])
        if mark is None:
            pnl_str = "price unavailable"
            mark_str = "N/A"
        else:
            pnl, pct = _unrealized_pnl(pos["side"], entry, mark, size)
            pnl_str = _format_pnl(pnl, pct)
            mark_str = f"{mark:.3f}"
        tp_sl = _format_tp_sl(pos["applied_tp_pct"], pos["applied_sl_pct"])
        lines.append(
            f"{connector} `{str(pos['id'])[:8]}` *{side}* — _{title}_\n"
            f"  size ${size:.2f} · entry {entry:.3f} · mark {mark_str}\n"
            f"  P&L {pnl_str} · {tp_sl}"
        )

    await update.message.reply_text(
        "\n\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=positions_list_kb([p["id"] for p in positions]),
    )


async def my_trades(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Combined My Trades view: open positions summary + recent activity (Tier 2+).

    Shows up to 10 open positions (no mark-price fetch, fast) and the last
    5 closed/filled orders. Users who need live P&L or force-close can reach
    the full view via /positions.
    """
    user, ok = await _ensure_tier(update)
    if not ok or update.message is None:
        return
    pool = get_pool()
    async with pool.acquire() as conn:
        pos_rows = await conn.fetch(
            """
            SELECT p.id, p.market_id, p.side, p.size_usdc, p.entry_price,
                   p.mode, p.opened_at, m.question
              FROM positions p
              LEFT JOIN markets m ON m.id = p.market_id
             WHERE p.user_id = $1 AND p.status = 'open'
             ORDER BY p.opened_at DESC
             LIMIT 10
            """,
            user["id"],
        )
        ord_rows = await conn.fetch(
            """
            SELECT o.market_id, o.side, o.size_usdc, o.price, o.mode,
                   o.status, o.created_at, m.question
              FROM orders o
              LEFT JOIN markets m ON m.id = o.market_id
             WHERE o.user_id = $1
             ORDER BY o.created_at DESC
             LIMIT 5
            """,
            user["id"],
        )
    lines: list[str] = []
    if pos_rows:
        lines.append(f"*📈 Open Positions ({len(pos_rows)}):*\n")
        for r in pos_rows:
            title = _truncate(r["question"] or r["market_id"], MARKET_TITLE_MAX)
            lines.append(
                f"`{str(r['id'])[:8]}` *{r['side'].upper()}* @ "
                f"{float(r['entry_price']):.3f} · ${float(r['size_usdc']):.2f} "
                f"[{r['mode']}]\n_{title}_"
            )
        lines.append("\n_/positions for live P\\&L + force\\-close._")
    else:
        lines.append("*📈 Positions:* No open positions.")
    lines.append("")
    if ord_rows:
        lines.append("*📋 Recent Activity:*\n")
        for r in ord_rows:
            title = _truncate(r["question"] or r["market_id"], 40)
            lines.append(
                f"{r['created_at'].strftime('%m-%d %H:%M')} · "
                f"*{r['side'].upper()}* @ {float(r['price']):.3f} · "
                f"${float(r['size_usdc']):.2f} [{r['mode']}/{r['status']}]\n_{title}_"
            )
    else:
        lines.append("*📋 Recent Activity:* No activity yet.")
    await update.message.reply_text(
        "\n\n".join(lines), parse_mode=ParseMode.MARKDOWN,
    )


async def _verify_user_owns_open_position(user_id, position_id: str) -> Optional[dict]:
    """Single source of truth for the ownership check used by both the
    confirm prompt and the confirm action — guards against a stale callback
    from a different chat or after the position already closed."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT p.id, p.market_id, m.question
              FROM positions p
              LEFT JOIN markets m ON m.id = p.market_id
             WHERE p.id = $1 AND p.user_id = $2 AND p.status = 'open'
            """,
            position_id, user_id,
        )
    return dict(row) if row else None


async def force_close_ask(update: Update,
                          ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """First tap on 🛑 Force Close — emit confirmation dialog (Tier 3+)."""
    q = update.callback_query
    if q is None:
        return
    user, ok = await _ensure_tier(update)
    if not ok:
        return
    await q.answer()
    position_id = (q.data or "").split(":", 2)[-1]
    row = await _verify_user_owns_open_position(user["id"], position_id)
    if row is None:
        await q.message.reply_text("Position not found or already closed.")
        return
    title = _truncate(row["question"] or row["market_id"], MARKET_TITLE_MAX)
    await q.message.reply_text(
        f"Close *{title}*?\nThis cannot be undone.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=force_close_confirm_kb(position_id),
    )


async def force_close_confirm(update: Update,
                              ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirm dialog handler — branches on yes/no (Tier 3+ for yes)."""
    q = update.callback_query
    if q is None:
        return
    data = q.data or ""
    parts = data.split(":", 2)
    if len(parts) != 3:
        await q.answer()
        return
    action = parts[1]
    position_id = parts[2]

    if action == "fc_no":
        await q.answer()
        await q.message.reply_text("Cancelled. Position still open.")
        return

    # action == "fc_yes" past this point
    user, ok = await _ensure_tier(update)
    if not ok:
        return
    await q.answer("Queueing…")
    row = await _verify_user_owns_open_position(user["id"], position_id)
    if row is None:
        await q.message.reply_text("Position not found or already closed.")
        return
    marked = await mark_force_close_intent_for_position(position_id, user["id"])
    if marked:
        await q.message.reply_text(
            "🛑 Force close queued. Exit watcher will close shortly."
        )
    else:
        # Already flagged on a prior tap or status flipped between checks.
        await q.message.reply_text(
            "Force close already queued for this position."
        )
