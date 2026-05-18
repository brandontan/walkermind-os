"""Access tier definitions + gate helper."""
from __future__ import annotations


class Tier:
    BROWSE = 1
    ALLOWLISTED = 2
    FUNDED = 3
    LIVE = 4


TIER_MSG = {
    2: "This feature is not available.",
    3: "This feature is not available.",
    4: "This feature is not available.",
}


def has_tier(user_tier: int, min_tier: int) -> bool:
    return user_tier >= min_tier


def tier_block_message(min_tier: int) -> str:
    return TIER_MSG.get(min_tier, "This feature is not available.")
