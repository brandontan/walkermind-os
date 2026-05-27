"""Lightweight Telegram notification helper used by background jobs.

Retries transient Telegram errors with exponential backoff. Final failures
are logged at ERROR (not silently swallowed).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import BadRequest, NetworkError, RetryAfter, TimedOut
from tenacity import (
    AsyncRetrying, retry_if_exception_type, retry_if_not_exception_type,
    stop_after_attempt, wait_exponential,
)
from tenacity.wait import wait_base

from .config import get_settings

logger = logging.getLogger(__name__)

_bot: Optional[Bot] = None

# Cap how long we honor a Telegram 429 RetryAfter on a single attempt.
# Telegram occasionally returns very large retry_after values (minutes);
# capping at 30s keeps overall wall-clock bounded while still respecting
# the server-mandated wait on typical rate limits.
_MAX_RETRY_AFTER_SECONDS: float = 30.0

# 4 attempts so a single 429 with retry_after does not exhaust the budget
# before a fresh attempt gets through. Worst-case wait is dominated by one
# capped retry_after (~30s) plus exponential backoff (1-8s).
_MAX_SEND_ATTEMPTS: int = 4


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(token=get_settings().TELEGRAM_BOT_TOKEN)
    return _bot


def set_bot(bot: Bot) -> None:
    """Allow main.py to share the Application's bot instance."""
    global _bot
    _bot = bot


class _wait_telegram(wait_base):
    """Wait strategy that honors Telegram's RetryAfter.retry_after on 429.

    Falls back to exponential backoff for other retryable errors (NetworkError,
    TimedOut). Without this, tenacity's wait_exponential would burn the attempt
    budget at sub-second intervals while Telegram explicitly asked for a longer
    pause, producing a permanent send-failure on transient rate limits.
    """

    def __init__(self) -> None:
        self._exp = wait_exponential(multiplier=1, min=1, max=8)

    def __call__(self, retry_state: Any) -> float:
        exc: Optional[BaseException] = None
        outcome = retry_state.outcome
        if outcome is not None and outcome.failed:
            exc = outcome.exception()
        if isinstance(exc, RetryAfter):
            # python-telegram-bot exposes retry_after as int seconds.
            try:
                wait = float(exc.retry_after)
            except (TypeError, ValueError):
                wait = self._exp(retry_state)
            return min(max(wait, 0.0), _MAX_RETRY_AFTER_SECONDS)
        return self._exp(retry_state)


def _retry() -> AsyncRetrying:
    # Note: BadRequest inherits from NetworkError in python-telegram-bot, but
    # it is non-transient (malformed payload, missing chat) — retrying it
    # only burns latency. Combine the retry predicate with a "not BadRequest"
    # filter so HTML parse errors fall through immediately to the plain-text
    # fallback in ``send()`` instead of consuming the attempt budget.
    return AsyncRetrying(
        reraise=True,
        stop=stop_after_attempt(_MAX_SEND_ATTEMPTS),
        wait=_wait_telegram(),
        retry=(
            retry_if_exception_type((NetworkError, TimedOut, RetryAfter))
            & retry_if_not_exception_type(BadRequest)
        ),
    )


async def send(
    chat_id: int,
    text: str,
    parse_mode: str = ParseMode.HTML,
    reply_markup: Optional[Any] = None,
) -> bool:
    """Send a Telegram message with retry, swallowing permanent failures.

    Returns ``True`` on successful delivery and ``False`` on permanent
    failure (after retries). Existing call sites that ignore the return
    value continue to work; the alert dispatcher uses it to avoid
    arming the cooldown when delivery did not actually happen.

    ``BadRequest`` (typically malformed HTML in ``text``) is non-transient
    and not in the retry set. When it surfaces on an HTML-mode send, we
    retry exactly once with ``parse_mode=None`` so a stray angle bracket
    cannot silently drop a trade-lifecycle receipt. Plain text is the
    fail-safe path — guaranteed to render even if the original markup
    was malformed.
    """
    try:
        async for attempt in _retry():
            with attempt:
                await get_bot().send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                )
        return True
    except BadRequest as exc:
        if parse_mode is None:
            logger.error(
                "Telegram send permanently failed (plain text) chat=%s err=%s",
                chat_id, exc,
            )
            return False
        logger.warning(
            "Telegram send BadRequest (parse_mode=%s) chat=%s err=%s — "
            "retrying as plain text",
            parse_mode, chat_id, exc,
        )
        try:
            async for attempt in _retry():
                with attempt:
                    await get_bot().send_message(
                        chat_id=chat_id,
                        text=text,
                        parse_mode=None,
                        reply_markup=reply_markup,
                    )
            return True
        except Exception as exc2:
            logger.error(
                "Telegram send permanently failed after plain-text fallback "
                "chat=%s err=%s",
                chat_id, exc2,
            )
            return False
    except Exception as exc:
        # Final failure (after retries) — surface as ERROR, never swallow silently.
        logger.error("Telegram send permanently failed chat=%s err=%s", chat_id, exc)
        return False


async def notify_operator(text: str, parse_mode: str = ParseMode.HTML) -> None:
    await send(get_settings().OPERATOR_CHAT_ID, text, parse_mode=parse_mode)


async def notify_user_by_telegram_id(telegram_user_id: int, text: str) -> None:
    await send(telegram_user_id, text)
