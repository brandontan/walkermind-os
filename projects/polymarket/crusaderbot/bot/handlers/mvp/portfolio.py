"""MVP Portfolio handler — balance / positions / history / performance."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

from ... import messages_mvp as mvp
from ...keyboards.mvp import portfolio as kb
from . import _users
from ._send import callback_parts, send_or_edit

log = logging.getLogger(__name__)

_RANK_ICONS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣"]


async def _read_portfolio(telegram_user) -> dict:
    p: dict = {
        "uuid": None, "balance": 0.0, "allocated": 0.0,
        "today_pnl": 0.0, "today_trades": 0, "win_rate": 0, "week_pnl": 0.0,
        "positions": [], "history_today": 0, "history_week": 0,
    }
    u = await _users.fetch_user(telegram_user.id, telegram_user.username)
    if u is None:
        return p
    p["uuid"] = u["id"]
    p["balance"] = await _users.fetch_balance(u["id"])
    p["today_pnl"] = await _users.fetch_daily_pnl(u["id"])
    p["positions"] = await _users.fetch_open_positions(u["id"])
    return p


async def show_home(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    p = await _read_portfolio(user) if user else {
        "balance": 0.0, "today_pnl": 0.0, "today_trades": 0, "win_rate": 0, "positions": [],
    }
    text = mvp.render_portfolio_home(
        balance=p["balance"], today_pnl=p["today_pnl"],
        today_trades=p["today_trades"], today_win_rate=p["win_rate"],
        open_positions=len(p["positions"]),
    )
    await send_or_edit(update, text, kb.home_kb())


async def show_positions(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    p = await _read_portfolio(user) if user else {"positions": []}
    if not p["positions"]:
        await send_or_edit(update, mvp.render_positions_empty(), kb.positions_empty_kb())
        return
    items = []
    for idx, pos in enumerate(p["positions"][:8]):
        side_raw = str(pos.get("side") or "").upper()
        side = "🟢 YES" if side_raw in {"YES", "BUY"} else "🔴 NO"
        # Best-effort PnL: entry vs current — fallback 0 if unavailable.
        pnl_val = float(pos.get("pnl") or 0.0)
        items.append({
            "rank": _RANK_ICONS[idx],
            "title": str(pos.get("market_title") or "Market")[:36],
            "id": str(pos.get("id") or idx),
            "side": side,
            "pnl": pnl_val,
        })
    text = mvp.render_positions_list(items)
    await send_or_edit(update, text, kb.positions_list_kb(items))


async def show_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    p = await _read_portfolio(user) if user else {"history_today": 0, "history_week": 0}
    if not p["history_today"] and not p["history_week"]:
        await send_or_edit(update, mvp.render_history_empty(), kb.history_empty_kb())
        return
    await send_or_edit(
        update,
        mvp.render_history_home(today=p["history_today"], week=p["history_week"]),
        kb.history_home_kb(),
    )


async def show_performance(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    p = await _read_portfolio(user) if user else {
        "today_pnl": 0.0, "week_pnl": 0.0, "win_rate": 0, "today_trades": 0,
    }
    await send_or_edit(
        update,
        mvp.render_performance(
            today_pnl=p["today_pnl"], week_pnl=p["week_pnl"],
            win_rate=p["win_rate"], trades=p["today_trades"],
        ),
        kb.performance_kb(),
    )


async def show_balance(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    p = await _read_portfolio(user) if user else {"balance": 0.0, "allocated": 0.0}
    await send_or_edit(
        update,
        mvp.render_balance(available=p["balance"], allocated=p["allocated"]),
        kb.balance_kb(),
    )


async def _port_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    parts = callback_parts(update)
    screen = parts[1] if len(parts) > 1 else "home"
    if screen == "home":
        await show_home(update, ctx); return
    if screen == "positions":
        await show_positions(update, ctx); return
    if screen == "history":
        await show_history(update, ctx); return
    if screen == "performance":
        await show_performance(update, ctx); return
    if screen == "balance":
        await show_balance(update, ctx); return
    await show_home(update, ctx)


def attach(app: Application) -> None:
    app.add_handler(CallbackQueryHandler(_port_cb, pattern=r"^portfolio:"))
