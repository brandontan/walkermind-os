"""In-memory Tier 2 allowlist + tier resolution.

Storage is a module-level singleton guarded by an asyncio.Lock for concurrent
safety. Persistence to Postgres is deferred (tracked in ROADMAP).
"""
from __future__ import annotations

import asyncio

import structlog

log = structlog.get_logger(__name__)

# Tier constants — keep in sync with blueprint v3.1 §1 Access Tiers.
TIER_BROWSE = 1
TIER_ALLOWLISTED = 2

_TIER_LABELS: dict[int, str] = {
    TIER_BROWSE: "User",
    TIER_ALLOWLISTED: "User",
}


class AllowlistStore:
    """Async-safe in-memory allowlist of telegram_user_id values."""

    def __init__(self) -> None:
        self._members: set[int] = set()
        self._lock = asyncio.Lock()

    async def add(self, telegram_user_id: int) -> bool:
        """Add a user. Returns True if newly added, False if already present."""
        async with self._lock:
            if telegram_user_id in self._members:
                return False
            self._members.add(telegram_user_id)
        log.info("allowlist.add", telegram_user_id=telegram_user_id)
        return True

    async def remove(self, telegram_user_id: int) -> bool:
        """Remove a user. Returns True if removed, False if not present."""
        async with self._lock:
            if telegram_user_id not in self._members:
                return False
            self._members.remove(telegram_user_id)
        log.info("allowlist.remove", telegram_user_id=telegram_user_id)
        return True

    async def contains(self, telegram_user_id: int) -> bool:
        async with self._lock:
            return telegram_user_id in self._members

    async def list_all(self) -> list[int]:
        async with self._lock:
            return sorted(self._members)


# Module-level singleton — imported by dispatcher, admin handler, tier gate.
allowlist = AllowlistStore()


# Module-level helpers (per task spec naming) -----------------------------------

async def add_to_allowlist(telegram_user_id: int) -> bool:
    return await allowlist.add(telegram_user_id)


async def remove_from_allowlist(telegram_user_id: int) -> bool:
    return await allowlist.remove(telegram_user_id)


async def is_allowlisted(telegram_user_id: int) -> bool:
    return await allowlist.contains(telegram_user_id)


async def get_user_tier(telegram_user_id: int) -> int:
    """Resolve a user's effective tier at read time.

    Tier 2 if `telegram_user_id` is in the allowlist; Tier 1 otherwise.
    Tier 3/4 (funded beta, live auto-trade) are reserved for later lanes.
    """
    if await allowlist.contains(telegram_user_id):
        return TIER_ALLOWLISTED
    return TIER_BROWSE


def tier_label(tier: int) -> str:
    """Human-readable tier label. Falls back to 'Tier {N}' for unknown values."""
    return _TIER_LABELS.get(tier, f"Tier {tier}")
