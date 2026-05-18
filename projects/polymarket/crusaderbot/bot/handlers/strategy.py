"""R5 strategy config commands: /strategy /risk /paper /config."""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...database import get_pool
from ...users import upsert_user

logger = logging.getLogger(__name__)

_STRATEGIES = ["signal_following", "copy_trade", "momentum_reversal"]
_RISK_PROFILES = ["conservative", "balanced", "aggressive"]


async def _resolve_user(update: Update) -> dict | None:
    if update.effective_user is None:
        return None
    return await upsert_user(update.effective_user.id, update.effective_user.username)


async def _get_r5_settings(user_id: object) -> dict:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT active_strategy, risk_profile, paper_mode_override, capital_alloc_pct"
            " FROM user_settings WHERE user_id=$1",
            user_id,
        )
    if row is None:
        return {
            "active_strategy": "signal_following",
            "risk_profile": "balanced",
            "paper_mode_override": True,
            "capital_alloc_pct": 0.10,
        }
    return dict(row)


def _strategy_kb(current: str) -> InlineKeyboardMarkup:
    rows = []
    for s in _STRATEGIES:
        label = ("✅ " if s == current else "") + s.replace("_", " ").title()
        rows.append([InlineKeyboardButton(label, callback_data=f"r5cfg:strategy:{s}")])
    return InlineKeyboardMarkup(rows)


def _risk_kb(current: str) -> InlineKeyboardMarkup:
    rows = []
    for r in _RISK_PROFILES:
        label = ("✅ " if r == current else "") + r.title()
        rows.append([InlineKeyboardButton(label, callback_data=f"r5cfg:risk:{r}")])
    return InlineKeyboardMarkup(rows)


def _paper_kb(current: bool) -> InlineKeyboardMarkup:
    label = "Turn OFF (go live)" if current else "Turn ON (paper)"
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(label, callback_data="r5cfg:paper:toggle"),
    ]])


async def strategy_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _resolve_user(update)
    if user is None or update.message is None:
        return
    s = await _get_r5_settings(user["id"])
    current = s.get("active_strategy") or "signal_following"
    await update.message.reply_text(
        f"<b>📡 Active Strategy</b>\nCurrent: <code>{current}</code>\n\nSelect strategy:",
        parse_mode=ParseMode.HTML,
        reply_markup=_strategy_kb(current),
    )


async def risk_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _resolve_user(update)
    if user is None or update.message is None:
        return
    s = await _get_r5_settings(user["id"])
    current = s.get("risk_profile") or "balanced"
    await update.message.reply_text(
        f"<b>⚖️ Risk Profile</b>\nCurrent: <code>{current}</code>\n\nSelect profile:",
        parse_mode=ParseMode.HTML,
        reply_markup=_risk_kb(current),
    )


async def paper_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _resolve_user(update)
    if user is None or update.message is None:
        return
    s = await _get_r5_settings(user["id"])
    current = bool(s.get("paper_mode_override", True))
    status = "ON (paper)" if current else "OFF (live)"
    await update.message.reply_text(
        f"<b>📄 Paper Mode Override</b>\nCurrent: <code>{status}</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=_paper_kb(current),
    )


async def config_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _resolve_user(update)
    if user is None or update.message is None:
        return
    s = await _get_r5_settings(user["id"])
    paper_status = "ON" if s.get("paper_mode_override", True) else "OFF"
    capital_pct = float(s.get("capital_alloc_pct") or 0.10) * 100
    await update.message.reply_text(
        "<b>⚙️ Strategy Config</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Strategy:     <code>{s.get('active_strategy', 'signal_following')}</code>\n"
        f"Risk profile: <code>{s.get('risk_profile', 'balanced')}</code>\n"
        f"Paper mode:   <code>{paper_status}</code>\n"
        f"Capital alloc:<code>{capital_pct:.0f}%</code>\n\n"
        "<i>Use /strategy, /risk, /paper to change settings.</i>",
        parse_mode=ParseMode.HTML,
    )


async def strategy_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q is None:
        return
    await q.answer()
    user = await _resolve_user(update)
    if user is None:
        return

    parts = (q.data or "").split(":", 2)
    if len(parts) < 3:
        return
    _, action, value = parts
    pool = get_pool()

    if action == "strategy":
        if value not in _STRATEGIES:
            return
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE user_settings SET active_strategy=$1 WHERE user_id=$2",
                value, user["id"],
            )
        s = await _get_r5_settings(user["id"])
        await q.message.edit_text(
            f"<b>📡 Active Strategy</b>\nCurrent: <code>{value}</code>\n\nSelect strategy:",
            parse_mode=ParseMode.HTML,
            reply_markup=_strategy_kb(value),
        )

    elif action == "risk":
        if value not in _RISK_PROFILES:
            return
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE user_settings SET risk_profile=$1 WHERE user_id=$2",
                value, user["id"],
            )
        await q.message.edit_text(
            f"<b>⚖️ Risk Profile</b>\nCurrent: <code>{value}</code>\n\nSelect profile:",
            parse_mode=ParseMode.HTML,
            reply_markup=_risk_kb(value),
        )

    elif action == "paper" and value == "toggle":
        async with pool.acquire() as conn:
            new_val = await conn.fetchval(
                "UPDATE user_settings SET paper_mode_override=NOT paper_mode_override"
                " WHERE user_id=$1 RETURNING paper_mode_override",
                user["id"],
            )
        new_val = bool(new_val)
        status = "ON (paper)" if new_val else "OFF (live)"
        await q.message.edit_text(
            f"<b>📄 Paper Mode Override</b>\nCurrent: <code>{status}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=_paper_kb(new_val),
        )
