"""String-tier access gate decorator for Telegram command handlers.

Usage:
    from ..middleware.access_tier import require_access_tier

    @require_access_tier('PREMIUM')
    async def my_premium_handler(update, context):
        ...

FREE  — only /start, /status, /help
PREMIUM — all trading commands
ADMIN   — all commands + admin panel
"""
from __future__ import annotations

from functools import wraps
from typing import Any, Awaitable, Callable

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from ...services.tiers import TIER_ADMIN, TIER_PREMIUM, get_user_tier, meets_tier

log = structlog.get_logger(__name__)

_UPGRADE_MESSAGES: dict[str, str] = {
    TIER_PREMIUM: (
        "🔒 This feature requires *PREMIUM* access.\n"
        "Contact the admin to upgrade your account."
    ),
    TIER_ADMIN: "⛔ Admin access required.",
}

HandlerFn = Callable[..., Awaitable[Any]]


def require_access_tier(min_tier: str) -> Callable[[HandlerFn], HandlerFn]:
    """Decorator: gate a Telegram handler on the caller's string tier."""

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
            user_tier = await get_user_tier(telegram_user_id)
            if not meets_tier(user_tier, min_tier):
                log.info(
                    "access_tier.denied",
                    telegram_user_id=telegram_user_id,
                    user_tier=user_tier,
                    required=min_tier,
                    handler=handler.__name__,
                )
                msg = _UPGRADE_MESSAGES.get(
                    min_tier, f"Access requires {min_tier} tier."
                )
                await update.effective_message.reply_text(
                    msg, parse_mode="Markdown"
                )
                return
            await handler(update, context, *args, **kwargs)

        return wrapper

    return decorator
