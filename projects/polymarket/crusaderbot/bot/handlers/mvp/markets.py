"""MVP Markets handler — intelligence-only, no manual trade buttons."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

from ... import messages_mvp as mvp
from ...keyboards.mvp import markets as kb
from . import _users
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
    from ._send import nav_push
    nav_push(ctx, "markets")
    await send_or_edit(update, mvp.render_markets_home(), kb.home_kb())


async def show_trending(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    items = await _read_markets()
    if not items:
        await send_or_edit(update, mvp.render_error_api(), kb.home_kb())
        return
    await send_or_edit(update, mvp.render_markets_trending(items), kb.trending_list_kb(items))


async def show_new(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show recently created markets sorted by created_at desc."""
    try:
        from ....database import get_pool  # type: ignore
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, question FROM markets"
                " WHERE active=true ORDER BY created_at DESC LIMIT 5"
            )
            items = [{"id": str(r["id"]), "title": str(r["question"])} for r in rows]
    except Exception as exc:  # noqa: BLE001
        log.debug("new markets fetch failed: %s", exc)
        items = []
    if not items:
        await send_or_edit(update, mvp.render_markets_empty(), kb.home_kb())
        return
    titles = [m["title"] for m in items]
    await send_or_edit(update, mvp.render_markets_new(items=titles), kb.home_kb())


async def show_insights(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    items = await _read_markets()
    if not items:
        await send_or_edit(update, mvp.render_error_api(), kb.home_kb())
        return
    top = items[0]
    # Fetch real signal confidence from signal_scan results if available
    confidence = "—"
    reason = "Insufficient data"
    try:
        from ....database import get_pool  # type: ignore
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT confidence_score, signal_reason
                FROM signal_scan_results
                WHERE market_id=$1
                ORDER BY created_at DESC LIMIT 1
                """,
                top["id"],
            )
            if row:
                score = row["confidence_score"]
                if score is not None:
                    confidence = f"{int(float(score) * 100)}%"
                if row["signal_reason"]:
                    reason = str(row["signal_reason"])
    except Exception as exc:  # noqa: BLE001
        log.debug("signal confidence fetch failed: %s", exc)
    text = mvp.render_markets_ai_insight(
        market_title=top["title"],
        confidence=confidence,
        reason=reason,
    )
    await send_or_edit(update, text, kb.ai_insight_kb(top["id"]))


async def show_watchlist(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user watchlist from DB, or empty state."""
    user = update.effective_user
    items: list[dict] = []
    if user is not None:
        u = await _users.fetch_user(user.id, user.username)
        if u is not None:
            try:
                from ....database import get_pool  # type: ignore
                pool = get_pool()
                async with pool.acquire() as conn:
                    rows = await conn.fetch(
                        """
                        SELECT m.id, m.question AS title
                        FROM user_watchlist w
                        JOIN markets m ON m.id = w.market_id
                        WHERE w.user_id=$1 ORDER BY w.created_at DESC LIMIT 10
                        """,
                        u["id"],
                    )
                    items = [{"id": str(r["id"]), "title": str(r["title"])} for r in rows]
            except Exception as exc:  # noqa: BLE001
                log.debug("watchlist fetch failed: %s", exc)
    if not items:
        await send_or_edit(update, mvp.render_watchlist_empty(), kb.watchlist_empty_kb())
        return
    titles = [m["title"] for m in items]
    await send_or_edit(update, mvp.render_watchlist(items=titles), kb.home_kb())


async def show_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if ctx.user_data is not None:
        ctx.user_data["mvp_markets_flow"] = {"step": "await_search"}
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
        sub = parts[2] if len(parts) > 2 else None
        if sub == "add":
            market_id = parts[3] if len(parts) > 3 else ""
            await _add_to_watchlist(update, ctx, market_id); return
        await show_watchlist(update, ctx); return
    if screen == "search":
        await show_search(update, ctx); return
    if screen == "detail":
        market_id = parts[2] if len(parts) > 2 else ""
        await show_detail(update, ctx, market_id); return
    if screen == "similar":
        await show_trending(update, ctx); return
    await show_home(update, ctx)


async def _add_to_watchlist(update: Update, ctx: ContextTypes.DEFAULT_TYPE, market_id: str) -> None:
    user = update.effective_user
    if user is not None and market_id:
        u = await _users.fetch_user(user.id, user.username)
        if u is not None:
            try:
                from ....database import get_pool  # type: ignore
                pool = get_pool()
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO user_watchlist (user_id, market_id)
                        VALUES ($1, $2::uuid)
                        ON CONFLICT DO NOTHING
                        """,
                        u["id"], market_id,
                    )
            except Exception as exc:  # noqa: BLE001
                log.debug("watchlist add failed: %s", exc)
    await show_watchlist(update, ctx)


async def text_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """Capture search query when markets flow is awaiting input."""
    if update.message is None:
        return False
    f = (ctx.user_data or {}).get("mvp_markets_flow")
    if not f or f.get("step") != "await_search":
        return False
    query = (update.message.text or "").strip()
    if ctx.user_data is not None:
        ctx.user_data["mvp_markets_flow"] = {}
    if not query:
        await update.message.reply_text("❌ Empty search. Try again.", parse_mode="HTML")
        return True
    try:
        from ....database import get_pool  # type: ignore
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, question FROM markets"
                " WHERE active=true AND question ILIKE $1 ORDER BY volume DESC LIMIT 5",
                f"%{query}%",
            )
            items = [{"id": str(r["id"]), "title": str(r["question"])} for r in rows]
    except Exception as exc:  # noqa: BLE001
        log.debug("market search failed: %s", exc)
        items = []
    if not items:
        await update.message.reply_text(
            f"🔍 No markets found for <code>{query}</code>.",
            parse_mode="HTML",
            reply_markup=kb.home_kb(),
        )
        return True
    titles = [m["title"] for m in items]
    await update.message.reply_text(
        mvp.render_markets_search_results(query=query, items=titles),
        parse_mode="HTML",
        reply_markup=kb.home_kb(),
    )
    return True


def attach(app: Application) -> None:
    app.add_handler(CallbackQueryHandler(_markets_cb, pattern=r"^markets:"))
