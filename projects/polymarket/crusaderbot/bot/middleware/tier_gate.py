"""Tier-gate decorator for Telegram command handlers.

Usage:
    from ...services.allowlist import TIER_ALLOWLISTED
    from ..middleware.tier_gate import require_tier

    @require_tier(TIER_ALLOWLISTED)
    async def my_tier2_handler(update, context, ...):
        ...

The wrapped handler is invoked only when the caller's effective tier is at
least `min_tier`; otherwise a friendly gate message is sent and the wrapped
handler is short-circuited.
"""
from __future__ import annotations

from functools import wraps
from typing import Any, Awaitable, Callable

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from ...services.allowlist import get_user_tier

log = structlog.get_logger(__name__)

TIER_DENIED_MESSAGE = (
    "🔒 This feature requires Tier 2 access (Community allowlist).\n"
    "Contact the operator to request access."
)

HandlerFn = Callable[..., Awaitable[Any]]


def require_tier(min_tier: int) -> Callable[[HandlerFn], HandlerFn]:
    """Return a decorator that gates a Telegram handler on the caller's tier."""

    def decorator(handler: HandlerFn) -> HandlerFn:
        @wraps(handler)
        async def wrapper(
            update: Update,
            context: ContextTypes.DEFAULT_TYPE,
            *args: Any,
            **kwargs: Any,
        ) -> None:
            if update.effective_user is None or update.effective_message is None:
                return
            telegram_user_id = update.effective_user.id
            current_tier = await get_user_tier(telegram_user_id)
            if current_tier < min_tier:
                log.info(
                    "tier_gate.denied",
                    telegram_user_id=telegram_user_id,
                    current_tier=current_tier,
                    required_tier=min_tier,
                    handler=handler.__name__,
                )
                await update.effective_message.reply_text(TIER_DENIED_MESSAGE)
                return
            await handler(update, context, *args, **kwargs)

        return wrapper

    return decorator
