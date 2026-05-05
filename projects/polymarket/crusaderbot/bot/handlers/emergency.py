"""Emergency menu — pause / pause+close-all (per-user).

Per spec: emergency close uses the FORCE-CLOSE MARKER FLOW rather than
liquidating directly. We set `force_close_intent=true` on each open position
via the position registry and then trigger the exit watcher inline so the
priority chain (force_close_intent > tp_hit > sl_hit > strategy_exit > hold)
drives the close.
"""
from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ... import audit
from ...domain.positions import registry as position_registry
from ...users import set_paused, upsert_user
from ..keyboards import emergency_menu

logger = logging.getLogger(__name__)


async def emergency_root(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(
        "*🛑 Emergency*\n\nUse with care. All actions are audited.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=emergency_menu(),
    )


async def emergency_callback(update: Update,
                             ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q is None or update.effective_user is None:
        return
    await q.answer()
    user = await upsert_user(update.effective_user.id, update.effective_user.username)
    sub = (q.data or "").split(":", 1)[-1]

    if sub == "pause":
        await set_paused(user["id"], True)
        await audit.write(actor_role="user", action="self_pause", user_id=user["id"])
        await q.message.reply_text("⏸ Paused — no new trades will be opened.")
    elif sub == "resume":
        await set_paused(user["id"], False)
        await audit.write(actor_role="user", action="self_resume", user_id=user["id"])
        await q.message.reply_text("▶️ Resumed.")
    elif sub == "pause_close":
        await set_paused(user["id"], True)
        marked = await position_registry.mark_force_close_intent_for_user(
            user["id"],
        )
        await audit.write(actor_role="user", action="self_pause_close",
                          user_id=user["id"],
                          payload={"marked_force_close_intent": marked})
        # Drain the priority chain immediately so the user sees results now
        # instead of waiting for the next EXIT_WATCH_INTERVAL tick.
        try:
            from ...scheduler import check_exits
            await check_exits()
        except Exception as exc:
            logger.error("emergency inline check_exits failed: %s", exc)
        await q.message.reply_text(
            f"🛑 Paused + flagged {marked} position(s) for force-close.\n"
            "Exit watcher just ran — see your dashboard for results.",
            parse_mode=ParseMode.MARKDOWN,
        )
