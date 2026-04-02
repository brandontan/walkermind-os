"""Reply-keyboard text message handler.

Handles user text messages that arrive from Telegram reply keyboards.
Schedules automatic deletion of the user message after a short delay to
keep the chat UI clean, then dispatches the action to the CallbackRouter.

Integration point in main.py polling loop:

    from .telegram.handlers.text_handler import schedule_user_message_delete

    # After identifying a reply-keyboard tap:
    msg_id = msg.get("message_id")
    if reply_chat and msg_id:
        asyncio.create_task(
            schedule_user_message_delete(
                tg_api=_tg_api,
                chat_id=reply_chat,
                message_id=msg_id,
            )
        )

Design:
    - asyncio only — no blocking calls.
    - Errors silently swallowed — delete failure must never crash the bot.
    - Inline UI (editMessageText) is NOT affected.
    - Only user messages are deleted; bot messages are never touched.
"""
from __future__ import annotations

import asyncio

from ..utils.message_cleanup import delete_user_message_later


async def schedule_user_message_delete(
    tg_api: str,
    chat_id: int,
    message_id: int,
) -> None:
    """Fire-and-forget: schedule deletion of a user reply-keyboard message.

    Creates a background asyncio task so the caller is never blocked.

    Args:
        tg_api: Telegram Bot API base URL.
        chat_id: Chat containing the message.
        message_id: ID of the user message to delete.
    """
    asyncio.create_task(
        delete_user_message_later(
            tg_api=tg_api,
            chat_id=chat_id,
            message_id=message_id,
        )
    )
