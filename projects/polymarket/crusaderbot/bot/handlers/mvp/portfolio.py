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
        "uuid": None, "balance": 0.0, "equity": 0.0, "allocated": 0.0,
        "today_pnl": 0.0, "today_trades": 0, "win_rate": 0, "week_pnl": 0.0,
        "positions": [], "history_today": 0, "history_week": 0,
    }
    u = await _users.fetch_user(telegram_user.id, telegram_user.username)
    if u is None:
        return p
    p["uuid"] = u["id"]
    p["balance"] = await _users.fetch_balance(u["id"])
    p["equity"] = await _users.fetch_equity(u["id"])
    p["today_pnl"] = await _users.fetch_daily_pnl(u["id"])
    p["week_pnl"] = await _users.fetch_week_pnl(u["id"])
    p["today_trades"] = await _users.fetch_closed_trade_count(u["id"], days=1)
    p["win_rate"] = await _users.fetch_win_rate(u["id"])
    p["history_today"] = p["today_trades"]
    p["history_week"] = await _users.fetch_closed_trade_count(u["id"], days=7)
    p["positions"] = await _users.fetch_open_positions(u["id"])
    return p


async def show_home(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from ._send import nav_push
    nav_push(ctx, "portfolio")
    user = update.effective_user
    p = await _read_portfolio(user) if user else {
        "balance": 0.0, "equity": 0.0, "today_pnl": 0.0, "week_pnl": 0.0,
        "today_trades": 0, "win_rate": 0, "positions": [],
    }
    text = mvp.render_portfolio_home(
        balance=p["balance"],
        equity=p.get("equity", 0.0),
        today_pnl=p["today_pnl"],
        week_pnl=p.get("week_pnl", 0.0),
        open_positions=len(p["positions"]),
    )
    await send_or_edit(update, text, kb.home_kb())


_PAGE_SIZE = 3


async def show_positions(update: Update, ctx: ContextTypes.DEFAULT_TYPE, page: int = 1) -> None:
    user = update.effective_user
    p = await _read_portfolio(user) if user else {"positions": []}
    if not p["positions"]:
        await send_or_edit(update, mvp.render_positions_empty(), kb.positions_empty_kb())
        return

    total = len(p["positions"])
    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    page = max(1, min(page, total_pages))

    if ctx.user_data is not None:
        ctx.user_data["positions_page"] = page

    start = (page - 1) * _PAGE_SIZE
    page_positions = p["positions"][start : start + _PAGE_SIZE]

    items = []
    for idx, pos in enumerate(page_positions):
        side_raw = str(pos.get("side") or "").upper()
        side = "🟢 YES" if side_raw in {"YES", "BUY"} else "🔴 NO"
        pnl_val = float(pos.get("pnl") or 0.0)
        items.append({
            "rank": _RANK_ICONS[start + idx],
            "title": str(pos.get("market_title") or "Market").strip(),
            "id": str(pos.get("id") or idx),
            "side": side,
            "pnl": pnl_val,
        })

    text = mvp.render_positions_list(items, page=page, total_pages=total_pages, total=total)
    await send_or_edit(update, text, kb.positions_list_kb(items, page=page, total_pages=total_pages))


async def show_positions_page(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle portfolio:positions:page:{n} callback."""
    q = update.callback_query
    parts = (q.data or "").split(":")
    try:
        page = int(parts[-1])
    except (ValueError, IndexError):
        page = 1
    await show_positions(update, ctx, page=page)


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
            today_pnl=p.get("today_pnl", 0.0),
            week_pnl=p.get("week_pnl", 0.0),
            win_rate=p.get("win_rate", 0),
            trades=p.get("today_trades", 0),
        ),
        kb.performance_kb(),
    )


async def show_history_range(update: Update, ctx: ContextTypes.DEFAULT_TYPE, range_key: str) -> None:
    """Show closed trades for today / this week / all time."""
    user = update.effective_user
    label_map = {"today": "Today", "week": "This Week", "all": "All Time"}
    label = label_map.get(range_key, "History")
    count = 0
    if user is not None:
        u = await _users.fetch_user(user.id, user.username)
        if u is not None:
            try:
                from ....database import get_pool  # type: ignore
                pool = get_pool()
                async with pool.acquire() as conn:
                    if range_key == "today":
                        count = int(await conn.fetchval(
                            "SELECT COUNT(*) FROM positions WHERE user_id=$1 AND status='closed'"
                            " AND closed_at >= NOW() - INTERVAL '1 day'",
                            u["id"],
                        ) or 0)
                    elif range_key == "week":
                        count = int(await conn.fetchval(
                            "SELECT COUNT(*) FROM positions WHERE user_id=$1 AND status='closed'"
                            " AND closed_at >= NOW() - INTERVAL '7 days'",
                            u["id"],
                        ) or 0)
                    else:
                        count = int(await conn.fetchval(
                            "SELECT COUNT(*) FROM positions WHERE user_id=$1 AND status='closed'",
                            u["id"],
                        ) or 0)
            except Exception as exc:  # noqa: BLE001
                log.debug("history range fetch failed: %s", exc)
    from ...keyboards.mvp.portfolio import history_range_kb  # type: ignore
    await send_or_edit(update, mvp.render_history_range(label=label, count=count), history_range_kb())


async def show_performance_range(update: Update, ctx: ContextTypes.DEFAULT_TYPE, range_key: str) -> None:
    """Show performance stats for a specific time window."""
    user = update.effective_user
    pnl_val = 0.0
    win_rate = 0
    trades = 0
    if user is not None:
        u = await _users.fetch_user(user.id, user.username)
        if u is not None:
            try:
                from ....database import get_pool  # type: ignore
                pool = get_pool()
                interval = "7 days" if range_key == "week" else "30 days"
                async with pool.acquire() as conn:
                    rows = await conn.fetch(
                        """
                        SELECT COALESCE(pnl_usdc, 0) AS pnl
                        FROM positions
                        WHERE user_id=$1 AND status='closed'
                          AND closed_at >= NOW() - INTERVAL '""" + interval + """'
                        """,
                        u["id"],
                    )
                    if rows:
                        pnl_vals = [float(r["pnl"]) for r in rows]
                        trades = len(pnl_vals)
                        pnl_val = sum(pnl_vals)
                        wins = sum(1 for v in pnl_vals if v > 0)
                        win_rate = int(wins / trades * 100) if trades else 0
            except Exception as exc:  # noqa: BLE001
                log.debug("performance range fetch failed: %s", exc)
    label = "7-Day" if range_key == "week" else "30-Day"
    from ...keyboards.mvp.portfolio import performance_range_kb  # type: ignore
    await send_or_edit(
        update,
        mvp.render_performance(today_pnl=pnl_val, week_pnl=pnl_val, win_rate=win_rate, trades=trades),
        performance_range_kb(range_key),
    )


async def show_balance(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    p = await _read_portfolio(user) if user else {"balance": 0.0, "allocated": 0.0}
    await send_or_edit(
        update,
        mvp.render_balance(available=p["balance"], allocated=p["allocated"]),
        kb.balance_kb(),
    )


async def show_position_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE, position_id: str) -> None:
    user = update.effective_user
    if user is None:
        await show_home(update, ctx)
        return
    u = await _users.fetch_user(user.id, user.username)
    if u is None:
        await show_home(update, ctx)
        return
    try:
        from ....database import get_pool  # type: ignore
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT p.id, p.side, p.entry_price, p.size_usdc,
                       COALESCE(p.pnl_usdc, 0.0) AS pnl,
                       p.status,
                       m.question AS market_title, m.id AS market_id
                FROM positions p
                LEFT JOIN markets m ON m.id = p.market_id
                WHERE p.id=$1::uuid AND p.user_id=$2::uuid
                """,
                position_id, u["id"],
            )
    except Exception as exc:  # noqa: BLE001
        log.debug("position detail fetch failed: %s", exc)
        row = None
    if row is None:
        await show_positions(update, ctx)
        return
    side_raw = str(row["side"] or "").upper()
    side = "🟢 YES" if side_raw in {"YES", "BUY"} else "🔴 NO"
    text = mvp.render_position_detail(
        market_title=str(row["market_title"] or "Market"),
        side=side,
        entry=f"{float(row['entry_price'] or 0) * 100:.1f}",
        current="—",
        pnl_value=float(row["pnl"] or 0),
        status=str(row["status"] or "open").title(),
    )
    from ...keyboards.mvp.portfolio import position_detail_kb  # type: ignore
    await send_or_edit(update, text, position_detail_kb(str(row["market_id"] or "")))


async def _port_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    parts = callback_parts(update)
    screen = parts[1] if len(parts) > 1 else "home"
    if screen == "home":
        await show_home(update, ctx); return
    if screen == "positions":
        await show_positions(update, ctx); return
    if screen == "position":
        position_id = parts[2] if len(parts) > 2 else ""
        await show_position_detail(update, ctx, position_id); return
    if screen == "history":
        sub = parts[2] if len(parts) > 2 else None
        if sub in {"today", "week", "all"}:
            await show_history_range(update, ctx, sub); return
        await show_history(update, ctx); return
    if screen == "performance":
        sub = parts[2] if len(parts) > 2 else None
        if sub in {"week", "month"}:
            await show_performance_range(update, ctx, sub); return
        await show_performance(update, ctx); return
    if screen == "balance":
        await show_balance(update, ctx); return
    await show_home(update, ctx)


def attach(app: Application) -> None:
    app.add_handler(CallbackQueryHandler(
        show_positions_page, pattern=r"^portfolio:positions:page:\d+$"
    ))
    app.add_handler(CallbackQueryHandler(_port_cb, pattern=r"^portfolio:"))
