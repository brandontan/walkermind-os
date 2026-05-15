"""Phase 5 UX Rebuild — Emergency menu (always accessible from any state).

Per spec: emergency close uses the FORCE-CLOSE MARKER FLOW — sets
force_close_intent=true on each open position via position registry.
"""
from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from ... import audit
from ...users import set_locked, set_paused, upsert_user
from ..keyboards import emergency_confirm_p5_kb, emergency_done_p5_kb, emergency_p5_kb
from ..messages import EMERGENCY_TEXT, emergency_confirm_text, emergency_feedback_text

logger = logging.getLogger(__name__)


async def _safe_edit(q, text: str, **kwargs) -> None:
    try:
        await q.edit_message_text(text, **kwargs)
    except BadRequest as exc:
        if "Message is not modified" not in str(exc):
            await q.message.reply_text(text, **kwargs)


async def _render_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q is not None and q.message is not None:
        await _safe_edit(
            q, EMERGENCY_TEXT,
            parse_mode=ParseMode.HTML, reply_markup=emergency_p5_kb(),
        )
    elif update.message is not None:
        await update.message.reply_text(
            EMERGENCY_TEXT, parse_mode=ParseMode.HTML, reply_markup=emergency_p5_kb(),
        )


async def emergency_root(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Command handler /emergency."""
    await _render_menu(update, ctx)


async def emergency_root_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback handler — menu:emergency."""
    q = update.callback_query
    if q is not None:
        await q.answer()
    await _render_menu(update, ctx)


async def emergency_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Routes all p5:emergency:* callbacks."""
    q = update.callback_query
    if q is None or update.effective_user is None:
        return
    await q.answer()
    data = q.data or ""

    if data.startswith("p5:emergency:ask:"):
        action = data[len("p5:emergency:ask:"):]
        text = emergency_confirm_text(action)
        await _safe_edit(
            q, text,
            parse_mode=ParseMode.HTML,
            reply_markup=emergency_confirm_p5_kb(action),
        )
        return

    if data.startswith("p5:emergency:confirm:"):
        action = data[len("p5:emergency:confirm:"):]
        await _execute_action(update, ctx, action)
        return

    # Legacy emergency:* pattern callbacks (backward compat)
    if data.startswith("emergency:"):
        await _handle_legacy_emergency(update, ctx, data)
        return


async def _execute_action(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE, action: str,
) -> None:
    q = update.callback_query
    if update.effective_user is None:
        return
    user = await upsert_user(update.effective_user.id, update.effective_user.username)

    try:
        if action == "pause":
            await set_paused(user["id"], True)
            await audit.write(actor_role="user", action="emergency_pause", user_id=user["id"])

        elif action == "pause_close":
            await set_paused(user["id"], True)
            try:
                from ...domain.positions import registry as position_registry
                from ...database import get_pool
                pool = get_pool()
                async with pool.acquire() as conn:
                    pos_ids = await conn.fetch(
                        "SELECT id FROM positions WHERE user_id=$1 AND status='open'",
                        user["id"],
                    )
                for row in pos_ids:
                    await position_registry.mark_force_close_intent_for_position(
                        row["id"], user["id"],
                    )
            except Exception as exc:
                logger.error("pause_close position marking failed: %s", exc)
            await audit.write(actor_role="user", action="emergency_pause_close_all", user_id=user["id"])

        elif action == "lock":
            await set_locked(user["id"], True)
            await audit.write(actor_role="user", action="emergency_lock", user_id=user["id"])

    except Exception as exc:
        logger.error("emergency action=%s failed: %s", action, exc)
        if q is not None and q.message is not None:
            await _safe_edit(
                q, "⚠️ Action failed. Please try again.",
                parse_mode=ParseMode.HTML, reply_markup=emergency_done_p5_kb(),
            )
        return

    text = emergency_feedback_text(action)
    if q is not None and q.message is not None:
        await _safe_edit(
            q, text, parse_mode=ParseMode.HTML, reply_markup=emergency_done_p5_kb(),
        )
    elif update.message is not None:
        await update.message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=emergency_done_p5_kb(),
        )


async def _handle_legacy_emergency(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE, data: str,
) -> None:
    """Backward compat for legacy emergency:pause / emergency:pause_close / emergency:lock."""
    q = update.callback_query
    sub = data.split(":", 1)[-1]

    if sub in ("pause", "pause_close", "lock"):
        text = emergency_confirm_text(sub)
        if q is not None and q.message is not None:
            await _safe_edit(
                q, text,
                parse_mode=ParseMode.HTML,
                reply_markup=emergency_confirm_p5_kb(sub),
            )
    elif sub.startswith("confirm:"):
        action = sub[len("confirm:"):]
        await _execute_action(update, ctx, action)
    elif sub in ("back", "cancel"):
        from .dashboard import show_dashboard_for_cb
        await show_dashboard_for_cb(update, ctx)
