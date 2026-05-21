"""Role-based access gate decorator for Telegram command handlers.

Usage:
    from ..middleware.access_tier import require_role

    @require_role('admin')
    async def my_admin_handler(update, context):
        ...

Two roles only: `user` (default — full paper access) and `admin`
(OPERATOR_CHAT_ID or ADMIN). This decorator gates admin-only handlers;
non-admin features are open to every user (paper trading is unrestricted).

The file name is retained as `access_tier.py` for import-path stability;
the legacy integer access_tier scheme has been removed.
"""
from __future__ import annotations

from functools import wraps
from typing import Any, Awaitable, Callable

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from ...database import get_pool

log = structlog.get_logger(__name__)

VALID_ROLES: frozenset[str] = frozenset({"admin", "user"})

HandlerFn = Callable[..., Awaitable[Any]]


async def _get_role(telegram_user_id: int) -> str:
    """Return the user's role; defaults to 'user' when row or column is missing.

    Fail-open to 'user' (not 'admin') so a missing column never grants
    elevated access. Admin handlers are still safe because the role check
    requires equality with 'admin'.
    """
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT role FROM users WHERE telegram_user_id=$1",
                telegram_user_id,
            )
    except Exception as exc:  # noqa: BLE001 — never crash a handler on a role read
        log.warning("role_read_failed", telegram_user_id=telegram_user_id, err=str(exc))
        return "user"
    if row is None or row["role"] is None:
        return "user"
    return str(row["role"])


def require_role(required_role: str) -> Callable[[HandlerFn], HandlerFn]:
    """Decorator: gate a Telegram handler on the caller's role.

    Raises ValueError at decoration time if required_role is unknown so
    typos are caught at import, not at runtime.
    """
    if required_role not in VALID_ROLES:
        raise ValueError(
            f"require_role: unknown role {required_role!r}. Valid: {sorted(VALID_ROLES)}"
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
            user_role = await _get_role(telegram_user_id)
            if user_role != required_role and required_role == "admin":
                log.info(
                    "role.denied",
                    telegram_user_id=telegram_user_id,
                    user_role=user_role,
                    required=required_role,
                    handler=handler.__name__,
                )
                await update.effective_message.reply_text(
                    "Admin access required.", parse_mode="Markdown"
                )
                return None
            return await handler(update, context, *args, **kwargs)

        return wrapper

    return decorator
