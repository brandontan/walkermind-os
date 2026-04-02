"""Telegram message cleanup utilities.

Provides a non-blocking helper to delete user messages after a short delay,
keeping the chat UI clean without affecting the inline message system.
"""
from __future__ import annotations

import asyncio

import aiohttp
import structlog

log = structlog.get_logger(__name__)


async def delete_user_message_later(
    tg_api: str,
    chat_id: int,
    message_id: int,
    delay: float = 0.4,
) -> None:
    """Delete a user message after a short delay.

    Runs as a background asyncio task — never blocks the caller.
    All errors are silently swallowed so a failed delete never crashes the bot.

    Args:
        tg_api: Telegram Bot API base URL (``https://api.telegram.org/botTOKEN``).
        chat_id: Telegram chat ID of the message to delete.
        message_id: Message ID to delete.
        delay: Seconds to wait before deleting (default 0.4 s).
    """
    try:
        await asyncio.sleep(delay)
        async with aiohttp.ClientSession() as session:
            await session.post(
                f"{tg_api}/deleteMessage",
                json={"chat_id": chat_id, "message_id": message_id},
            )
        log.info(
            "user_message_deleted",
            chat_id=chat_id,
            message_id=message_id,
        )
    except Exception:  # noqa: BLE001
        pass
