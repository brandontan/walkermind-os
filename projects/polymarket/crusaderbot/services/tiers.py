"""Access tier CRUD for the user_tiers table.

String tiers: FREE < PREMIUM < ADMIN.
Parallel to the legacy integer access_tier column — does not replace it.
"""
from __future__ import annotations

import structlog

from ..database import get_pool

log = structlog.get_logger(__name__)

TIER_FREE = "FREE"
TIER_PREMIUM = "PREMIUM"
TIER_ADMIN = "ADMIN"

VALID_TIERS: frozenset[str] = frozenset({TIER_FREE, TIER_PREMIUM, TIER_ADMIN})

_RANK: dict[str, int] = {TIER_FREE: 0, TIER_PREMIUM: 1, TIER_ADMIN: 2}


def tier_rank(tier: str) -> int:
    return _RANK.get(tier, 0)


def meets_tier(user_tier: str, required: str) -> bool:
    return tier_rank(user_tier) >= tier_rank(required)


async def get_user_tier(telegram_user_id: int) -> str:
    """Return the tier for a user, defaulting to FREE if not in user_tiers."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT tier FROM user_tiers WHERE user_id = $1",
            telegram_user_id,
        )
    return str(row["tier"]) if row else TIER_FREE


async def set_user_tier(
    telegram_user_id: int,
    tier: str,
    assigned_by: int,
) -> None:
    """Upsert tier for a user. Raises ValueError on invalid tier string."""
    if tier not in VALID_TIERS:
        raise ValueError(f"Invalid tier '{tier}'. Valid: {sorted(VALID_TIERS)}")
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_tiers (user_id, tier, assigned_by, assigned_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (user_id) DO UPDATE
                SET tier        = EXCLUDED.tier,
                    assigned_by = EXCLUDED.assigned_by,
                    assigned_at = NOW()
            """,
            telegram_user_id,
            tier,
            assigned_by,
        )
    log.info(
        "tiers.set",
        telegram_user_id=telegram_user_id,
        tier=tier,
        assigned_by=assigned_by,
    )


async def list_all_user_tiers(limit: int = 50) -> list[dict]:
    """Return rows from user_tiers, most recently assigned first."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT user_id, tier, assigned_by, assigned_at "
            "FROM user_tiers ORDER BY assigned_at DESC LIMIT $1",
            limit,
        )
    return [dict(r) for r in rows]
