"""Telegram Power Mode — callback handlers for inline buttons on trade notifications.

Handles tgnotif:* callback_data emitted by notification_service.py keyboard builders:
    tgnotif:pause_copy:{copy_task_id}  — pause a copy-trade task
    tgnotif:dashboard                  — send dashboard URL link
"""
from __future__ import annotations

import logging
from uuid import UUID

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...config import get_settings
from ...database import get_pool
from ...users import upsert_user

logger = logging.getLogger(__name__)


async def _send_or_answer(update: Update, text: str, show_alert: bool = False) -> None:
    q = update.callback_query
    if q is not None:
        try:
            await q.answer(text[:200] if show_alert else None, show_alert=show_alert)
        except Exception as exc:
            logger.debug("tg_power_mode: q.answer() failed (harmless): %s", exc)
        if not show_alert and update.effective_chat:
            try:
                await update.effective_chat.send_message(text, parse_mode=ParseMode.MARKDOWN_V2)
            except Exception as exc:
                logger.error("tg_power_mode send failed: %s", exc)
    elif update.message is not None:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)


async def pause_copy_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """tgnotif:pause_copy:{copy_task_id} — set copy_trade_task status to 'paused'."""
    q = update.callback_query
    if q is None or update.effective_user is None:
        return
    await q.answer()

    data = q.data or ""
    copy_task_id = data[len("tgnotif:pause_copy:"):]
    if not copy_task_id:
        await _send_or_answer(update, "⚠️ Invalid task reference.", show_alert=True)
        return

    user = await upsert_user(update.effective_user.id, update.effective_user.username)

    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            updated = await conn.fetchval(
                "UPDATE copy_trade_tasks SET status='paused', updated_at=NOW()"
                " WHERE id=$1::uuid AND user_id=$2 AND status='active'"
                " RETURNING 1",
                copy_task_id,
                user["id"],
            )
    except Exception as exc:
        logger.error("pause_copy_cb db failed task=%s err=%s", copy_task_id, exc)
        await _send_or_answer(update, "⚠️ Could not pause copy task. Please try again.", show_alert=True)
        return

    if updated:
        await _send_or_answer(
            update,
            "⏸ *Copy trade paused\\.*\n"
            "No new trades will be copied for this leader\\.\n"
            "Resume via /copytrade\\.",
        )
    else:
        await _send_or_answer(
            update,
            "ℹ️ Copy task not found or already paused.",
            show_alert=True,
        )


async def dashboard_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """tgnotif:dashboard — send the WebTrader dashboard URL."""
    q = update.callback_query
    if q is None or update.effective_user is None:
        return
    await q.answer()

    settings = get_settings()
    url = settings.WEBTRADER_URL
    if url:
        text = f"🌐 *Dashboard*\n`{url}`"
    else:
        text = "🌐 *Dashboard*\nWeb dashboard URL not configured\\."

    if update.effective_chat:
        try:
            await update.effective_chat.send_message(text, parse_mode=ParseMode.MARKDOWN_V2)
        except Exception as exc:
            logger.error("dashboard_cb send failed: %s", exc)


async def tg_power_mode_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Router for all tgnotif:* callbacks."""
    q = update.callback_query
    if q is None:
        return
    data = q.data or ""

    if data.startswith("tgnotif:pause_copy:"):
        await pause_copy_cb(update, ctx)
    elif data == "tgnotif:dashboard":
        await dashboard_cb(update, ctx)
    else:
        await q.answer()
