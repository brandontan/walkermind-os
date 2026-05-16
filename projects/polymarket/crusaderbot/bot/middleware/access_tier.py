"""String-tier access gate decorator for Telegram command handlers.

Usage:
    from ..middleware.access_tier import require_access_tier

    @require_access_tier('PREMIUM')
    async def my_premium_handler(update, context):
        ...

Two roles only: `user` (default — full paper access) and `admin`
(OPERATOR_CHAT_ID or ADMIN). This decorator gates admin-only handlers;
non-admin features are open to every user.
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
    TIER_PREMIUM: "This feature is not available.",
    TIER_ADMIN: "Admin access required.",
}

HandlerFn = Callable[..., Awaitable[Any]]


def require_access_tier(min_tier: str) -> Callable[[HandlerFn], HandlerFn]:
    """Decorator: gate a Telegram handler on the caller's string tier.

    Raises ValueError at decoration time if min_tier is not a known tier,
    so typos are caught when the module is imported, not at runtime.
    """
    from ...services.tiers import VALID_TIERS  # local import avoids circular at module level
    if min_tier not in VALID_TIERS:
        raise ValueError(
            f"require_access_tier: unknown tier {min_tier!r}. Valid: {sorted(VALID_TIERS)}"
        )

    def decorator(handler: HandlerFn) -> HandlerFn:
        @wraps(handler)
        async def wrapper(
            update: Update,
            context: ContextTypes.DEFAULT_TYPE,
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            if update.effective_user is None or update.effective_message is None:
                return None
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
                    min_tier, "This feature is not available."
                )
                await update.effective_message.reply_text(
                    msg, parse_mode="Markdown"
                )
                return None
            return await handler(update, context, *args, **kwargs)

        return wrapper

    return decorator
