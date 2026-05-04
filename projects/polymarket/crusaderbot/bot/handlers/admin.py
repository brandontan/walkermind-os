"""Admin/operator command handlers — currently the /allowlist subcommand router."""
from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from ...config import Settings
from ...services.allowlist import (
    add_to_allowlist,
    allowlist,
    remove_from_allowlist,
)

log = structlog.get_logger(__name__)

UNAUTHORIZED_MESSAGE = "⛔ Unauthorized."

USAGE_MESSAGE = (
    "Usage:\n"
    "  /allowlist add <telegram_user_id>\n"
    "  /allowlist remove <telegram_user_id>\n"
    "  /allowlist list"
)


def _is_operator(telegram_user_id: int, config: Settings) -> bool:
    return telegram_user_id == config.OPERATOR_CHAT_ID


async def handle_allowlist(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    config: Settings,
) -> None:
    """Handle /allowlist [add|remove|list] subcommands. Operator-only."""
    if update.effective_user is None or update.effective_message is None:
        return

    caller_id = update.effective_user.id
    if not _is_operator(caller_id, config):
        log.warning(
            "allowlist.unauthorized_attempt",
            caller_id=caller_id,
            operator_id=config.OPERATOR_CHAT_ID,
        )
        await update.effective_message.reply_text(UNAUTHORIZED_MESSAGE)
        return

    args = context.args or []
    if not args:
        await update.effective_message.reply_text(USAGE_MESSAGE)
        return

    subcommand = args[0].lower()

    if subcommand == "list":
        members = await allowlist.list_all()
        if not members:
            await update.effective_message.reply_text("📋 Allowlist is empty.")
            return
        formatted = "\n".join(f"- `{uid}`" for uid in members)
        plural = "s" if len(members) != 1 else ""
        await update.effective_message.reply_text(
            f"📋 Tier 2 allowlist ({len(members)} member{plural}):\n{formatted}",
            parse_mode="Markdown",
        )
        return

    if subcommand in ("add", "remove"):
        if len(args) < 2:
            await update.effective_message.reply_text(USAGE_MESSAGE)
            return
        try:
            target_id = int(args[1])
        except ValueError:
            await update.effective_message.reply_text(
                f"⚠️ Invalid user_id: `{args[1]}` (must be an integer).",
                parse_mode="Markdown",
            )
            return

        if subcommand == "add":
            added = await add_to_allowlist(target_id)
            msg = (
                f"✅ User {target_id} added to Tier 2 allowlist."
                if added
                else f"ℹ️ User {target_id} is already on the allowlist."
            )
            log.info(
                "allowlist.command_add",
                caller_id=caller_id,
                target=target_id,
                newly_added=added,
            )
            await update.effective_message.reply_text(msg)
            return

        removed = await remove_from_allowlist(target_id)
        msg = (
            f"✅ User {target_id} removed from allowlist."
            if removed
            else f"ℹ️ User {target_id} was not on the allowlist."
        )
        log.info(
            "allowlist.command_remove",
            caller_id=caller_id,
            target=target_id,
            removed=removed,
        )
        await update.effective_message.reply_text(msg)
        return

    await update.effective_message.reply_text(
        f"⚠️ Unknown subcommand: `{subcommand}`.\n\n{USAGE_MESSAGE}",
        parse_mode="Markdown",
    )
