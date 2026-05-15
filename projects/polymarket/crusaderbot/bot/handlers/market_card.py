"""Rich market card handler — /market {slug} command and inline callbacks."""
from __future__ import annotations

import html
import logging
from typing import Optional

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...integrations.polymarket import get_market_by_slug
from ..keyboards.market_card import market_card_kb

logger = logging.getLogger(__name__)

_SEP = "──────────────────"


def _fmt_price(p: Optional[float]) -> str:
    if p is None:
        return "—"
    return f"${p:.3f}"


def _fmt_volume(v: object) -> str:
    try:
        n = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "—"
    if n >= 1_000_000:
        return f"${n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"${n / 1_000:.1f}K"
    return f"${n:.2f}"


def _fmt_date(d: Optional[str]) -> str:
    if not d:
        return "—"
    return d[:10]


def _build_market_card(
    market: dict,
    *,
    signal_type: Optional[str] = None,
    strategy_name: Optional[str] = None,
    confidence_pct: Optional[float] = None,
) -> str:
    raw_title = (market.get("question") or market.get("title") or "Unknown")[:80]
    title = html.escape(raw_title)

    yes_price: Optional[float] = None
    no_price: Optional[float] = None
    for token in market.get("tokens", []):
        outcome = (token.get("outcome") or "").upper()
        try:
            p = float(token.get("price", 0))
        except (TypeError, ValueError):
            p = 0.0
        if outcome == "YES":
            yes_price = p
        elif outcome == "NO":
            no_price = p

    volume = _fmt_volume(market.get("volume_num") or market.get("volumeNum") or market.get("volume"))
    liquidity = _fmt_volume(market.get("liquidity_num") or market.get("liquidityNum") or market.get("liquidity"))
    end_date = _fmt_date(market.get("end_date_iso") or market.get("endDateIso"))

    lines = [
        f"<b>{title}</b>",
        _SEP,
        "<b>Price</b>",
        f"· YES: {_fmt_price(yes_price)}",
        f"· NO:  {_fmt_price(no_price)}",
        "",
        f"Volume 24h: {volume}",
        f"Liquidity:  {liquidity}",
        f"Ends: {end_date}",
    ]

    if signal_type or strategy_name or confidence_pct is not None:
        lines.append("")
        if signal_type:
            strat_str = f" ({html.escape(strategy_name)})" if strategy_name else ""
            lines.append(f"Signal: {html.escape(signal_type)}{strat_str}")
        if confidence_pct is not None:
            lines.append(f"Confidence: {confidence_pct:.0f}%")

    lines.append(_SEP)
    return "\n".join(lines)


async def market_command(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle /market {slug} — fetch and display rich market card."""
    if update.message is None or update.effective_user is None:
        return

    args = ctx.args or []
    if not args:
        await update.message.reply_text(
            "Usage: <code>/market &lt;slug&gt;</code>\nExample: <code>/market will-trump-win-2024</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    slug = args[0].strip().lower()
    status_msg = await update.message.reply_text("🔍 Loading market data...")

    market = await get_market_by_slug(slug)
    if market is None:
        await status_msg.edit_text(
            f"❌ Market <code>{html.escape(slug)}</code> not found. Check the slug and try again.",
            parse_mode=ParseMode.HTML,
        )
        return

    card = _build_market_card(market)
    await status_msg.edit_text(
        card,
        parse_mode=ParseMode.HTML,
        reply_markup=market_card_kb(slug),
    )


async def market_callback(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle inline button callbacks from market cards."""
    q = update.callback_query
    if q is None:
        return

    data = q.data or ""
    parts = data.split(":", 2)
    if len(parts) < 3:
        await q.answer()
        return

    action = parts[1]
    slug = parts[2]

    if action in ("y", "n"):
        side = "YES" if action == "y" else "NO"
        await q.answer(
            f"Auto-trade {side} via /preset. The bot will trade automatically "
            "when a matching signal arrives.",
            show_alert=True,
        )
    elif action == "a":
        await q.answer(
            "Price alerts coming soon. Stay tuned.",
            show_alert=True,
        )
    elif action == "d":
        market = await get_market_by_slug(slug)
        url = f"https://polymarket.com/event/{slug}"
        await q.answer(url if market else "Market not found.", show_alert=True)
    else:
        await q.answer()
