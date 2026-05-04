"""Operator-only admin commands. Requires update.effective_user.id == OPERATOR_CHAT_ID."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ... import audit
from ...config import get_settings
from ...database import get_pool, is_kill_switch_active, set_kill_switch
from ...users import force_set_tier, get_user_by_username
from ..keyboards import admin_menu
from ..tier import Tier

logger = logging.getLogger(__name__)


def _is_operator(update: Update) -> bool:
    if update.effective_user is None:
        return False
    return update.effective_user.id == get_settings().OPERATOR_CHAT_ID


async def admin_root(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_operator(update) or update.message is None:
        if update.message:
            await update.message.reply_text("⛔ Operator only.")
        return
    active = await is_kill_switch_active()
    await update.message.reply_text(
        f"*⚙️ Admin*\n\nKill switch: {'🔴 ACTIVE' if active else '🟢 inactive'}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=admin_menu(active),
    )


async def admin_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q is None or not _is_operator(update):
        if q:
            await q.answer("Operator only.", show_alert=True)
        return
    await q.answer()
    sub = (q.data or "").split(":", 1)[-1]

    if sub == "kill":
        active = await is_kill_switch_active()
        await set_kill_switch(not active, reason="operator_toggle",
                              changed_by=None)
        await audit.write(actor_role="operator",
                          action="kill_switch_" + ("on" if not active else "off"))
        await q.message.reply_text(
            f"Kill switch is now *{'ON 🔴' if not active else 'OFF 🟢'}*.",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif sub == "status":
        await _send_status(q.message)
    elif sub == "force_redeem":
        from ...scheduler import redeem_hourly
        await redeem_hourly()
        await q.message.reply_text("✅ Force-redeem run dispatched.")


async def _send_status(message) -> None:
    from ...cache import ping_cache
    from ...database import ping
    pool = get_pool()
    db_ok = await ping()
    cache_ok = await ping_cache()
    async with pool.acquire() as conn:
        users_n = await conn.fetchval("SELECT COUNT(*) FROM users")
        funded_n = await conn.fetchval("SELECT COUNT(*) FROM users WHERE access_tier>=3")
        live_n = await conn.fetchval("SELECT COUNT(*) FROM users WHERE access_tier>=4")
        open_paper = await conn.fetchval(
            "SELECT COUNT(*) FROM positions WHERE status='open' AND mode='paper'")
        open_live = await conn.fetchval(
            "SELECT COUNT(*) FROM positions WHERE status='open' AND mode='live'")
    s = get_settings()
    await message.reply_text(
        "*🩺 System status*\n\n"
        f"DB: {'✅' if db_ok else '❌'}  Cache: {'✅' if cache_ok else '❌'}\n"
        f"Users: {users_n} · Funded: {funded_n} · Live: {live_n}\n"
        f"Open positions: {open_paper} paper · {open_live} live\n\n"
        f"Guards:\n"
        f"  ENABLE_LIVE_TRADING={s.ENABLE_LIVE_TRADING}\n"
        f"  EXECUTION_PATH_VALIDATED={s.EXECUTION_PATH_VALIDATED}\n"
        f"  CAPITAL_MODE_CONFIRMED={s.CAPITAL_MODE_CONFIRMED}\n"
        f"  AUTO_REDEEM_ENABLED={s.AUTO_REDEEM_ENABLED}\n",
        parse_mode=ParseMode.MARKDOWN,
    )


async def allowlist_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_operator(update) or update.message is None:
        if update.message:
            await update.message.reply_text("⛔ Operator only.")
        return
    args = ctx.args or []
    if not args:
        await update.message.reply_text(
            "Usage: `/allowlist @username` or `/allowlist <telegram_user_id> [tier]`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    target = args[0]
    tier = int(args[1]) if len(args) > 1 else Tier.ALLOWLISTED
    user = None
    if target.startswith("@"):
        user = await get_user_by_username(target)
    else:
        try:
            from ...users import get_user_by_telegram_id
            user = await get_user_by_telegram_id(int(target))
        except ValueError:
            user = None
    if user is None:
        await update.message.reply_text(
            f"User {target} not found. They must /start first."
        )
        return
    await force_set_tier(user["id"], tier)
    await audit.write(actor_role="operator", action="allowlist", user_id=user["id"],
                      payload={"new_tier": tier})
    await update.message.reply_text(
        f"✅ {target} promoted to Tier {tier}."
    )
    # Route through notifications.send so the call inherits R12's
    # tenacity retry+backoff and consistent ERROR-on-final-failure logging.
    from ... import notifications
    await notifications.send(
        user["telegram_user_id"],
        f"🎉 You've been promoted to Tier {tier}. New features unlocked!",
    )
