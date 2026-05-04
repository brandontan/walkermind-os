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

Effective tier = max(in-memory allowlist tier, DB-backed `users.access_tier`).
The DB tier is consulted only when the allowlist tier alone falls short, so
the common (allowlisted) path adds zero DB overhead. This keeps the gate
consistent with `/wallet`'s effective-tier display: a user promoted to
Tier 3 by a confirmed deposit must not be denied a Tier 2-gated command
just because they were never added to the in-memory allowlist.
"""
from __future__ import annotations

from functools import wraps
from typing import Any, Awaitable, Callable

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from ...services.allowlist import get_user_tier
from ...services.user_service import get_user_by_telegram_id

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
            allowlist_tier = await get_user_tier(telegram_user_id)
            effective_tier = allowlist_tier
            if allowlist_tier < min_tier:
                pool = kwargs.get("pool")
                if pool is not None:
                    user = await get_user_by_telegram_id(pool, telegram_user_id)
                    db_tier = (
                        int(user.get("access_tier", 1)) if user else 1
                    )
                    effective_tier = max(allowlist_tier, db_tier)
            if effective_tier < min_tier:
                log.info(
                    "tier_gate.denied",
                    telegram_user_id=telegram_user_id,
                    allowlist_tier=allowlist_tier,
                    effective_tier=effective_tier,
                    required_tier=min_tier,
                    handler=handler.__name__,
                )
                await update.effective_message.reply_text(TIER_DENIED_MESSAGE)
                return
            await handler(update, context, *args, **kwargs)

        return wrapper

    return decorator
