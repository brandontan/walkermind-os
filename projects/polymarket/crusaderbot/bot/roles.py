"""Binary Admin/User role system — replaces legacy Tier gating.

Admin  = OPERATOR_CHAT_ID (root) OR has 'ADMIN' tier in user_tiers table.
User   = any registered user. All registered users can access all standard
         features. No allowlist, no tier gates, no "waitlist" blocking.
"""
from __future__ import annotations

from ..database import get_pool
from ..config import get_settings


def is_admin(user: dict) -> bool:
    """Sync check — True if user is the root operator."""
    return int(user.get("telegram_user_id", 0)) == get_settings().OPERATOR_CHAT_ID


async def is_admin_full(user: dict) -> bool:
    """Full async check — root operator OR ADMIN tier in user_tiers DB."""
    if is_admin(user):
        return True
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT tier FROM user_tiers WHERE user_id = $1",
            user.get("id"),
        )
    return row is not None and row["tier"] == "ADMIN"


def is_registered(user: dict | None) -> bool:
    """True for any user in the DB — replaces has_tier(…, Tier.ALLOWLISTED)."""
    return user is not None and bool(user.get("id"))


async def _get_user(update) -> tuple[dict | None, bool]:
    """Unified user resolver.  Returns (user, True) for any registered user.
    Only returns False when the Telegram context carries no user object."""
    from ..users import upsert_user

    tg = update.effective_user
    if tg is None:
        return None, False
    user = await upsert_user(tg.id, tg.username)
    return user, True
