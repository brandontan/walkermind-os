"""MVP Markets handler — intelligence-only, no manual trade buttons."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

from ... import messages_mvp as mvp
from ...keyboards.mvp import markets as kb
from ._send import callback_parts, send_or_edit

log = logging.getLogger(__name__)

_RANK_ICONS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣"]


async def _read_markets() -> list[dict]:
    try:
        from ....jobs.market_signal_scanner import get_scanner_state  # type: ignore
        state = await get_scanner_state()
        rows = (state or {}).get("recent_signals", [])[:6]
        out: list[dict] = []
        for idx, sig in enumerate(rows):
            out.append({
                "id": str(sig.get("market_id") or sig.get("id") or idx),
                "rank": _RANK_ICONS[idx],
                "title": str(sig.get("title") or sig.get("question") or "Market")[:36],
                "yes": sig.get("yes_price") or 50,
                "no": sig.get("no_price") or 50,
                "volume": sig.get("volume_label") or "⚡ Medium",
                "sentiment": sig.get("sentiment") or "🟡 Neutral",
            })
        return out
    except Exception as exc:  # noqa: BLE001
        log.debug("markets scanner unavailable: %s", exc)
        return []


async def show_home(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await send_or_edit(update, mvp.render_markets_home(), kb.home_kb())


async def show_trending(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    items = await _read_markets()
    if not items:
        await send_or_edit(update, mvp.render_error_api(), kb.home_kb())
        return
    await send_or_edit(update, mvp.render_markets_trending(items), kb.trending_list_kb(items))


async def show_new(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    # MVP — same data source as trending; future: separate new-markets feed.
    await show_trending(update, ctx)


async def show_insights(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    items = await _read_markets()
    if not items:
        await send_or_edit(update, mvp.render_error_api(), kb.home_kb())
        return
    top = items[0]
    text = mvp.render_markets_ai_insight(
        market_title=top["title"],
        confidence="81%",
        reason="Momentum + volume strength",
    )
    await send_or_edit(update, text, kb.ai_insight_kb(top["id"]))


async def show_watchlist(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await send_or_edit(update, mvp.render_watchlist_empty(), kb.watchlist_empty_kb())


async def show_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await send_or_edit(update, mvp.render_markets_search_prompt(), kb.search_prompt_kb())


async def show_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE, market_id: str) -> None:
    items = await _read_markets()
    match = next((m for m in items if m["id"] == market_id), None)
    if match is None:
        await send_or_edit(update, mvp.render_error_api(), kb.home_kb())
        return
    text = mvp.render_markets_detail(
        market_title=match["title"],
        yes_price=str(match["yes"]),
        no_price=str(match["no"]),
        sentiment=match["sentiment"],
        ai_confidence="81%",
    )
    await send_or_edit(update, text, kb.detail_kb(market_id))


async def _markets_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    parts = callback_parts(update)
    screen = parts[1] if len(parts) > 1 else "home"
    if screen == "home":
        await show_home(update, ctx); return
    if screen == "trending":
        await show_trending(update, ctx); return
    if screen == "new":
        await show_new(update, ctx); return
    if screen == "insights":
        await show_insights(update, ctx); return
    if screen == "watchlist":
        await show_watchlist(update, ctx); return
    if screen == "search":
        await show_search(update, ctx); return
    if screen == "detail":
        market_id = parts[2] if len(parts) > 2 else ""
        await show_detail(update, ctx, market_id); return
    if screen == "similar":
        await show_trending(update, ctx); return
    await show_home(update, ctx)


def attach(app: Application) -> None:
    app.add_handler(CallbackQueryHandler(_markets_cb, pattern=r"^markets:"))
