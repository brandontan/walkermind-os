"""Lightweight Telegram notification helper used by background jobs.

Retries transient Telegram errors with exponential backoff. Final failures
are logged at ERROR (not silently swallowed).
"""
from __future__ import annotations

import logging
from typing import Optional

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import NetworkError, RetryAfter, TimedOut
from tenacity import (
    AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential,
)

from .config import get_settings

logger = logging.getLogger(__name__)

_bot: Optional[Bot] = None


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(token=get_settings().TELEGRAM_BOT_TOKEN)
    return _bot


def set_bot(bot: Bot) -> None:
    """Allow main.py to share the Application's bot instance."""
    global _bot
    _bot = bot


def _retry():
    return AsyncRetrying(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((NetworkError, TimedOut, RetryAfter)),
    )


async def send(chat_id: int, text: str, parse_mode: str = ParseMode.MARKDOWN) -> None:
    try:
        async for attempt in _retry():
            with attempt:
                await get_bot().send_message(
                    chat_id=chat_id, text=text, parse_mode=parse_mode,
                )
    except Exception as exc:
        # Final failure (after retries) — surface as ERROR, never swallow silently.
        logger.error("Telegram send permanently failed chat=%s err=%s", chat_id, exc)


async def notify_operator(text: str) -> None:
    await send(get_settings().OPERATOR_CHAT_ID, text)


async def notify_user_by_telegram_id(telegram_user_id: int, text: str) -> None:
    await send(telegram_user_id, text)
