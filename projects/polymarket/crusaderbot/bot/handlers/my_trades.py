"""My Trades combined view — Phase 5I redesign.

Surfaces:
  my_trades(update, ctx)       — text 📈 My Trades: combined positions + activity
  close_ask_cb(update, ctx)    — callback mytrades:close_ask:<uuid>
  close_confirm_cb(update, ctx)— callback mytrades:close_yes|close_no:<uuid>
  history_cb(update, ctx)      — callback mytrades:hist:<page>
  back_cb(update, ctx)         — callback mytrades:back (re-render from inline)

Message structure:
  My Trades
  ─────────────────────
  Open Positions (N)

  1. <market title>
     Side: YES at $0.42
     Size: $5.00
     Current: $0.48 (+14.3%)

  [Close 1]  [Close 2]
  [📋 Full History]  [📊 Dashboard]
  ─────────────────────
  Recent Activity (last 5)
  ✅ <market>: +$2.10
  ❌ <market>: -$1.80
  …

Per-position close flow:
  tap Close N → confirmation dialog → Confirm / Cancel
  Confirm → paper.close_position → success with realized PnL
  Cancel  → "Cancelled." + [My Trades]
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import math
from decimal import Decimal
from typing import Optional
from uuid import UUID

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...domain.execution import paper as paper_exec
from ...domain.trading import repository as repo
from ...integrations.polymarket import get_book
from ...monitoring import alerts as monitoring_alerts
from ...users import get_settings_for, upsert_user
from ..keyboards import nav_row
from ..keyboards.my_trades import (
    close_confirm_kb,
    close_success_kb,
    history_nav_kb,
    my_trades_main_kb,
)
from ..tier import Tier, has_tier, tier_block_message

logger = logging.getLogger(__name__)

_PRICE_TIMEOUT = 3.0
_MARKET_MAX = 40
_HISTORY_PER_PAGE = 10
_SEP = "─" * 20


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


async def _ensure_tier(update: Update, min_tier: int) -> tuple[Optional[dict], bool]:
    if update.effective_user is None:
        return None, False
    user = await upsert_user(
        update.effective_user.id, update.effective_user.username
    )
    if not has_tier(user["access_tier"], min_tier):
        msg = tier_block_message(min_tier)
        if update.callback_query is not None:
            await update.callback_query.answer(msg, show_alert=True)
        elif update.message is not None:
            await update.message.reply_text(msg)
        return None, False
    return user, True


async def _fetch_mark(token_id: Optional[str]) -> Optional[float]:
    if not token_id:
        return None
    try:
        book = await asyncio.wait_for(get_book(token_id), timeout=_PRICE_TIMEOUT)
    except (asyncio.TimeoutError, Exception):
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


def _pnl(side: str, entry: float, mark: float, size: float) -> tuple[float, float]:
    """Return (pnl_usdc, pnl_pct). size is USDC notional at entry."""
    if entry <= 0:
        return 0.0, 0.0
    shares = size / entry
    raw = (mark - entry) * shares if side == "yes" else (entry - mark) * shares
    pct = (raw / size) * 100.0 if size > 0 else 0.0
    return raw, pct


def _fmt_current(mark: Optional[float], side: str, entry: float,
                 size: float) -> str:
    if mark is None:
        return "N/A"
    pnl, pct = _pnl(side, entry, mark, size)
    sign = "+" if pnl >= 0 else ""
    return f"${mark:.3f} ({sign}{pct:.1f}%)"


# ---------------------------------------------------------------------------
# Message formatters
# ---------------------------------------------------------------------------


def _format_positions_section(
    positions: list[dict],
    marks: list[Optional[float]],
    tp_pct: Optional[float],
    sl_pct: Optional[float],
) -> str:
    count = len(positions)
    if count == 0:
        return "Open Positions\n\nNo open positions."
    tp_str = f"+{tp_pct * 100:.0f}%" if tp_pct is not None else "—"
    sl_str = f"-{sl_pct * 100:.0f}%" if sl_pct is not None else "—"
    lines = [f"Open Positions ({count})\n"]
    for i, (pos, mark) in enumerate(zip(positions, marks), start=1):
        title = _truncate(pos["question"] or pos["market_id"], _MARKET_MAX)
        entry = float(pos["entry_price"])
        size = float(pos["size_usdc"])
        side_label = pos["side"].upper()
        current_str = _fmt_current(mark, pos["side"], entry, size)
        lines.append(
            f"{i}. {title}\n"
            f"   {side_label} @ ${entry:.3f} → {current_str}\n"
            f"   TP: {tp_str} | SL: {sl_str}"
        )
    return "\n\n".join(lines)


def _format_activity_section(activity: list[dict]) -> str:
    if not activity:
        return "Recent Activity (last 5)\n\nNo closed positions yet."
    lines = [f"Recent Activity (last {len(activity)})\n"]
    for row in activity:
        title = _truncate(row["question"] or row["market_id"], _MARKET_MAX)
        pnl = float(row["pnl_usdc"])
        emoji = "✅" if pnl >= 0 else "❌"
        sign = "+" if pnl >= 0 else ""
        lines.append(f"{emoji} {title}: {sign}${abs(pnl):.2f}")
    return "\n".join(lines)


def _build_main_text(
    positions: list[dict],
    marks: list[Optional[float]],
    activity: list[dict],
    tp_pct: Optional[float] = None,
    sl_pct: Optional[float] = None,
) -> str:
    pos_section = _format_positions_section(positions, marks, tp_pct, sl_pct)
    act_section = _format_activity_section(activity)
    today_count = len([a for a in activity if a.get("closed_at") and
                       a["closed_at"].date() == datetime.date.today()])
    today_pnl = sum(float(a.get("pnl_usdc", 0)) for a in activity
                    if a.get("closed_at") and
                    a["closed_at"].date() == datetime.date.today())
    today_sign = "+" if today_pnl >= 0 else ""
    today_line = f"Today: {today_count} trades · {today_sign}${abs(today_pnl):.2f}"
    return (
        f"*📈 My Trades*\n"
        f"{_SEP}\n"
        f"_{today_line}_\n\n"
        f"{pos_section}\n\n"
        f"{_SEP}\n\n"
        f"{act_section}"
    )


def _format_history_page(rows: list[dict], page: int, total: int) -> str:
    per_page = _HISTORY_PER_PAGE
    total_pages = max(1, math.ceil(total / per_page))
    if not rows:
        return "*Full History*\n\nNo closed positions yet."
    lines = [f"*Full History* — page {page + 1}/{total_pages}\n"]
    for row in rows:
        title = _truncate(row["question"] or row["market_id"], _MARKET_MAX)
        pnl = float(row["pnl_usdc"])
        emoji = "✅" if pnl >= 0 else "❌"
        sign = "+" if pnl >= 0 else ""
        date = (
            row["closed_at"].strftime("%m-%d")
            if row.get("closed_at") else "?"
        )
        lines.append(f"{emoji} [{date}] {title}: {sign}${abs(pnl):.2f}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public handler entry points
# ---------------------------------------------------------------------------


async def my_trades(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Combined My Trades view (Tier 2+): open positions + recent activity."""
    user, ok = await _ensure_tier(update, Tier.ALLOWLISTED)
    if not ok or update.message is None:
        return

    positions = await repo.get_open_positions(user["id"])
    activity = await repo.get_recent_activity(user["id"], limit=5)
    s = await get_settings_for(user["id"])

    tp_pct = float(s["tp_pct"]) if s.get("tp_pct") is not None else None
    sl_pct = float(s["sl_pct"]) if s.get("sl_pct") is not None else None

    token_ids: list[Optional[str]] = [
        (p["yes_token_id"] if p["side"] == "yes" else p["no_token_id"])
        for p in positions
    ]
    marks: list[Optional[float]] = list(
        await asyncio.gather(*(_fetch_mark(tid) for tid in token_ids))
    ) if token_ids else []

    text = _build_main_text(positions, marks, activity, tp_pct, sl_pct)
    kb = my_trades_main_kb([p["id"] for p in positions])
    await update.message.reply_text(
        text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb
    )


async def close_ask_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """First tap on [Close N] — show confirmation dialog (Tier 2+)."""
    q = update.callback_query
    if q is None:
        return
    user, ok = await _ensure_tier(update, Tier.ALLOWLISTED)
    if not ok:
        return
    await q.answer()

    raw_id = (q.data or "").split(":", 2)[-1]
    try:
        position_id = UUID(raw_id)
    except ValueError:
        await q.message.reply_text("Invalid position ID.")
        return

    pos = await repo.get_open_position_for_user(user["id"], position_id)
    if pos is None:
        await q.message.reply_text("Position not found or already closed.")
        return

    title = _truncate(pos["question"] or pos["market_id"], _MARKET_MAX)
    entry = float(pos["entry_price"])
    size = float(pos["size_usdc"])
    side_label = pos["side"].upper()

    token_id = (
        pos["yes_token_id"] if pos["side"] == "yes" else pos["no_token_id"]
    )
    mark = await _fetch_mark(token_id)
    if mark is not None:
        _, pct = _pnl(pos["side"], entry, mark, size)
        sign = "+" if pct >= 0 else ""
        pnl_str = f"{sign}{pct:.1f}%"
    else:
        pnl_str = "N/A"

    confirm_text = (
        f"*Close position:* {title}\n"
        f"Side: {side_label}, Size: ${size:.2f}, Current PnL: {pnl_str}\n"
        f"This will sell at market price."
    )
    await q.message.reply_text(
        confirm_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=close_confirm_kb(position_id),
    )


async def close_confirm_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle [Confirm Close] / [Cancel] (Tier 2+)."""
    q = update.callback_query
    if q is None:
        return
    data = q.data or ""
    parts = data.split(":", 2)
    if len(parts) != 3:
        await q.answer()
        return

    action = parts[1]    # "close_yes" or "close_no"
    raw_id = parts[2]

    if action == "close_no":
        await q.answer()
        await q.message.reply_text(
            "Position close cancelled.",
            reply_markup=close_success_kb(),
        )
        return

    # action == "close_yes"
    user, ok = await _ensure_tier(update, Tier.ALLOWLISTED)
    if not ok:
        return
    await q.answer("Closing…")

    try:
        position_id = UUID(raw_id)
    except ValueError:
        await q.message.reply_text("Invalid position ID.")
        return

    pos = await repo.get_open_position_for_user(user["id"], position_id)
    if pos is None:
        await q.message.reply_text("Position not found or already closed.")
        return

    if pos["mode"] != "paper":
        await q.message.reply_text(
            "Live positions cannot be closed here. Use /positions for force-close."
        )
        return

    token_id = (
        pos["yes_token_id"] if pos["side"] == "yes" else pos["no_token_id"]
    )
    mark = await _fetch_mark(token_id)
    exit_price = mark if mark is not None else float(pos["entry_price"])

    result = await paper_exec.close_position(
        position=pos,
        exit_price=exit_price,
        exit_reason="manual",
    )

    realized = float(result.get("pnl_usdc", Decimal("0")))
    sign = "+" if realized >= 0 else ""
    await q.message.reply_text(
        f"Position closed. Realized PnL: {sign}${abs(realized):.2f}",
        reply_markup=close_success_kb(),
    )

    # Only notify on a real state transition; skip if position was already closed.
    if result.get("exit_reason") != "already_closed":
        try:
            await monitoring_alerts.alert_user_manual_close(
                telegram_user_id=user["telegram_user_id"],
                market_id=pos["market_id"],
                market_question=pos.get("market_question"),
                side=pos["side"],
                exit_price=exit_price,
                pnl_usdc=realized,
                mode=pos.get("mode", "paper"),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("manual_close notification failed: %s", exc)


async def history_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show paginated Full History (10 per page). Edits the existing message."""
    q = update.callback_query
    if q is None:
        return
    user, ok = await _ensure_tier(update, Tier.ALLOWLISTED)
    if not ok:
        return
    await q.answer()

    raw_page = (q.data or "").split(":")[-1]
    try:
        page = max(0, int(raw_page))
    except ValueError:
        page = 0

    rows, total = await repo.get_activity_page(
        user["id"], page, _HISTORY_PER_PAGE
    )
    total_pages = max(1, math.ceil(total / _HISTORY_PER_PAGE))
    page = min(page, total_pages - 1)
    # Re-fetch if the original request was out of range (stale/crafted callback).
    if not rows and total > 0:
        rows, _ = await repo.get_activity_page(user["id"], page, _HISTORY_PER_PAGE)

    text = _format_history_page(rows, page, total)
    kb = history_nav_kb(
        page,
        has_prev=page > 0,
        has_next=(page + 1) < total_pages,
    )
    await q.message.edit_text(
        text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb
    )


async def trade_detail_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle mytrades:open:<uuid> — show brief trade detail card."""
    q = update.callback_query
    if q is None:
        return
    user, ok = await _ensure_tier(update, Tier.ALLOWLISTED)
    if not ok:
        return
    await q.answer()

    raw_id = (q.data or "").split(":", 2)[-1]
    try:
        position_id = UUID(raw_id)
    except ValueError:
        await q.message.reply_text("Invalid trade ID.")
        return

    pos = await repo.get_open_position_for_user(user["id"], position_id)
    if pos is None:
        from telegram import InlineKeyboardMarkup as _IKM2
        await q.message.reply_text(
            "Position closed or not found. Check 📋 Full History.",
            reply_markup=_IKM2([nav_row("mytrades:back")]),
        )
        return

    title = _truncate(pos["question"] or pos["market_id"], _MARKET_MAX)
    entry = float(pos["entry_price"])
    size = float(pos["size_usdc"])
    token_id = pos["yes_token_id"] if pos["side"] == "yes" else pos["no_token_id"]
    mark = await _fetch_mark(token_id)
    pnl_str = _fmt_current(mark, pos["side"], entry, size)

    from telegram import InlineKeyboardMarkup as _IKM
    await q.message.reply_text(
        f"*Trade Detail*\n"
        f"_{title}_\n\n"
        f"Side: *{pos['side'].upper()}*\n"
        f"Size: ${size:.2f}\n"
        f"Entry: ${entry:.3f}\n"
        f"Current: {pnl_str}\n"
        f"Mode: {pos.get('mode', 'paper').title()}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_IKM([nav_row("mytrades:back")]),
    )


async def back_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Re-render My Trades from an inline callback surface."""
    q = update.callback_query
    if q is None:
        return
    user, ok = await _ensure_tier(update, Tier.ALLOWLISTED)
    if not ok:
        return
    await q.answer()

    positions = await repo.get_open_positions(user["id"])
    activity = await repo.get_recent_activity(user["id"], limit=5)
    s = await get_settings_for(user["id"])

    tp_pct = float(s["tp_pct"]) if s.get("tp_pct") is not None else None
    sl_pct = float(s["sl_pct"]) if s.get("sl_pct") is not None else None

    token_ids: list[Optional[str]] = [
        (p["yes_token_id"] if p["side"] == "yes" else p["no_token_id"])
        for p in positions
    ]
    marks: list[Optional[float]] = list(
        await asyncio.gather(*(_fetch_mark(tid) for tid in token_ids))
    ) if token_ids else []

    text = _build_main_text(positions, marks, activity, tp_pct, sl_pct)
    kb = my_trades_main_kb([p["id"] for p in positions])
    await q.message.reply_text(
        text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb
    )
