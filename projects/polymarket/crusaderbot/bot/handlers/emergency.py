"""Phase 5 UX Rebuild — Emergency menu (always accessible from any state).

Per spec: emergency close uses the FORCE-CLOSE MARKER FLOW — sets
force_close_intent=true on each open position via position registry.
"""
from __future__ import annotations

import logging
from uuid import UUID

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from ... import audit
from ...database import get_pool
from ...users import set_auto_trade, set_locked, set_paused, upsert_user
from ..keyboards.emergency import (
    emergency_confirm_kb as emergency_confirm_p5_kb,
    emergency_done_kb as emergency_done_p5_kb,
    emergency_home_kb as emergency_p5_kb,
    emergency_more_kb,
)
from ..messages import (
    EMERGENCY_TEXT,
    emergency_confirm_text,
    emergency_feedback_text,
    emergency_system_status_text,
)

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


async def _system_status_text(user_id: UUID | str) -> str:
    """Build a system status snapshot for the current user."""
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT auto_trade_on, paused, locked,"
                " (SELECT COUNT(*) FROM positions"
                "   WHERE user_id=$1 AND status='open') AS open_count,"
                " (SELECT COUNT(*) FROM copy_trade_tasks"
                "   WHERE user_id=$1 AND status='active') AS copy_active"
                " FROM users WHERE id=$1",
                user_id,
            )
    except Exception as exc:
        logger.error("system_status query failed: %s", exc)
        return "⚠️ Could not retrieve system status."

    auto_on = row["auto_trade_on"] if row else False
    paused = row["paused"] if row else False
    locked = row["locked"] if row else False

    auto_icon = "🟢" if (auto_on and not paused and not locked) else "🔴"
    lock_icon = "🔒" if locked else "🔓"

    return emergency_system_status_text(
        auto_icon=auto_icon,
        auto_on=auto_on,
        paused=paused,
        lock_icon=lock_icon,
        locked=locked,
        open_positions=int(row["open_count"] if row else 0),
        copy_active=int(row["copy_active"] if row else 0),
    )


async def _execute_action(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE, action: str,
) -> None:
    q = update.callback_query
    if update.effective_user is None:
        return

    user = await upsert_user(update.effective_user.id, update.effective_user.username)

    # system_status is read-only — skip the try/except confirm flow
    if action == "system_status":
        text = await _system_status_text(user["id"])
        if q is not None and q.message is not None:
            await _safe_edit(
                q, text, parse_mode=ParseMode.HTML, reply_markup=emergency_done_p5_kb(),
            )
        elif update.message is not None:
            await update.message.reply_text(
                text, parse_mode=ParseMode.HTML, reply_markup=emergency_done_p5_kb(),
            )
        return

    try:
        if action == "pause":
            await set_paused(user["id"], True)
            await audit.write(actor_role="user", action="emergency_pause", user_id=user["id"])

        elif action == "pause_close":
            await set_paused(user["id"], True)
            try:
                pool = get_pool()
                async with pool.acquire() as conn:
                    pos_ids = await conn.fetch(
                        "SELECT id FROM positions WHERE user_id=$1 AND status='open'",
                        user["id"],
                    )
                for row in pos_ids:
                    await mark_force_close_intent_for_position(
                        row["id"], user["id"],
                    )
            except Exception as exc:
                logger.error("pause_close position marking failed: %s", exc)
            await audit.write(actor_role="user", action="emergency_pause_close_all", user_id=user["id"])

        elif action == "lock":
            await set_paused(user["id"], True)
            await set_locked(user["id"], True)
            await audit.write(actor_role="user", action="self_lock_account", user_id=user["id"])

        elif action == "stop_auto_trade":
            await set_auto_trade(user["id"], False)
            await audit.write(
                actor_role="user", action="emergency_stop_auto_trade", user_id=user["id"],
            )

        elif action == "kill_all_positions":
            try:
                pool = get_pool()
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE positions SET force_close_intent = TRUE"
                        " WHERE user_id = $1 AND status = 'open'"
                        " AND force_close_intent = FALSE",
                        user["id"],
                    )
            except Exception as exc:
                logger.error("kill_all_positions bulk update failed: %s", exc)
            await audit.write(
                actor_role="user", action="emergency_kill_all_positions", user_id=user["id"],
            )

        elif action == "lock_bot":
            await set_paused(user["id"], True)
            await set_auto_trade(user["id"], False)
            await set_locked(user["id"], True)
            await audit.write(
                actor_role="user", action="emergency_lock_bot", user_id=user["id"],
            )

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
    """Route emergency:* callbacks (v2 progressive-disclosure surface + legacy)."""
    q = update.callback_query
    sub = data.split(":", 1)[-1]

    if sub == "more":
        # Level 2 — secondary emergency actions.
        if q is not None and q.message is not None:
            await _safe_edit(
                q,
                "⚠️ <b>Additional Emergency Actions</b>\n\n"
                "These are high-impact actions. Use with caution.",
                parse_mode=ParseMode.HTML, reply_markup=emergency_more_kb(),
            )
        return
    if sub in ("home", "back", "cancel"):
        # Return to the primary emergency menu (Level 1).
        await _render_menu(update, ctx)
        return
    if sub == "status":
        await _execute_action(update, ctx, "system_status")
        return
    if sub.startswith("ask:"):
        action = sub[len("ask:"):]
        text = emergency_confirm_text(action)
        if q is not None and q.message is not None:
            await _safe_edit(
                q, text, parse_mode=ParseMode.HTML,
                reply_markup=emergency_confirm_p5_kb(action),
            )
        return
    if sub.startswith("confirm:"):
        action = sub[len("confirm:"):]
        await _execute_action(update, ctx, action)
        return
    if sub in ("pause", "pause_close", "lock"):
        # Legacy bare actions → confirm dialog.
        text = emergency_confirm_text(sub)
        if q is not None and q.message is not None:
            await _safe_edit(
                q, text, parse_mode=ParseMode.HTML,
                reply_markup=emergency_confirm_p5_kb(sub),
            )


async def mark_force_close_intent_for_position(
    position_id: UUID | str,
    user_id: UUID | str,
) -> int:
    """Set force_close_intent=TRUE on a single open position owned by user_id.

    Returns 1 if newly flagged, 0 if already flagged, missing, closed, or
    owned by a different user. Imported by positions.py for per-position
    force-close button. Same priority chain as the pause+close-all path.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        marked = await conn.fetchval(
            "WITH upd AS ("
            "  UPDATE positions SET force_close_intent = TRUE"
            "   WHERE id = $1 AND user_id = $2 AND status = 'open'"
            "     AND force_close_intent = FALSE"
            "   RETURNING 1"
            ") SELECT COUNT(*) FROM upd",
            position_id, user_id,
        )
    flipped = int(marked or 0)
    if flipped:
        await audit.write(
            actor_role="user",
            action="self_force_close_position",
            user_id=user_id,
            payload={"position_id": str(position_id)},
        )
    return flipped
