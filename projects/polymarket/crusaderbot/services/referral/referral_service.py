"""Referral code service — generate, lookup, record, and query referrals.

Rules:
- One code per user, generated on first /start if not present.
- Code: 8-char alphanumeric, URL-safe, unique (retry on collision).
- Deep link: t.me/CrusaderBot?start=ref_{CODE}
- On new user join with ref param: record referral_event + increment uses.
- Referral payout logic is written but gated behind REFERRAL_PAYOUT_ENABLED.
"""
from __future__ import annotations

import logging
import random
import string
from typing import Optional
from uuid import UUID

import structlog

from ...config import get_settings
from ...database import get_pool

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_CODE_ALPHABET = string.ascii_uppercase + string.digits
_CODE_LENGTH = 8
_BOT_USERNAME = "CrusaderBot"
_MAX_COLLISION_RETRIES = 5


def _generate_code() -> str:
    return "".join(random.choices(_CODE_ALPHABET, k=_CODE_LENGTH))


def build_deep_link(code: str) -> str:
    return f"https://t.me/{_BOT_USERNAME}?start=ref_{code}"


async def get_or_create_referral_code(user_id: UUID) -> str:
    """Return the user's referral code, creating it if absent.

    Retries up to _MAX_COLLISION_RETRIES times on UNIQUE violation.
    Raises RuntimeError if all retries fail (extremely unlikely).
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT code FROM referral_codes WHERE user_id=$1", user_id,
        )
        if row:
            return str(row["code"])

        for attempt in range(_MAX_COLLISION_RETRIES):
            code = _generate_code()
            try:
                await conn.execute(
                    "INSERT INTO referral_codes (user_id, code) VALUES ($1, $2)",
                    user_id, code,
                )
                return code
            except Exception as exc:
                if "unique" in str(exc).lower() and attempt < _MAX_COLLISION_RETRIES - 1:
                    logger.warning(
                        "referral_code.collision attempt=%d user_id=%s", attempt, user_id,
                    )
                    continue
                raise
    raise RuntimeError(f"referral code generation failed for user_id={user_id}")


async def get_referral_code(user_id: UUID) -> Optional[str]:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT code FROM referral_codes WHERE user_id=$1", user_id,
        )
        return str(row["code"]) if row else None


async def get_referral_stats(user_id: UUID) -> dict:
    """Return dict: code, deep_link, total_referrals, total_earnings."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT code, uses, referred_users FROM referral_codes WHERE user_id=$1",
            user_id,
        )
    if row is None:
        return {
            "code": None,
            "deep_link": None,
            "total_referrals": 0,
            "total_earnings": 0.0,
        }

    code = str(row["code"])
    earnings = await _calculate_referral_earnings(user_id)
    return {
        "code": code,
        "deep_link": build_deep_link(code),
        "total_referrals": int(row["referred_users"]),
        "total_earnings": earnings,
    }


async def _calculate_referral_earnings(user_id: UUID) -> float:
    """Calculate referral earnings. Gated behind REFERRAL_PAYOUT_ENABLED."""
    settings = get_settings()
    if not settings.REFERRAL_PAYOUT_ENABLED:
        return 0.0

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT COALESCE(SUM(f.fee_amount * 0.20), 0.0) AS earnings
            FROM referral_events re
            JOIN fees f ON f.user_id = re.referred_id
            WHERE re.referrer_id = $1
            """,
            user_id,
        )
        return float(row["earnings"]) if row else 0.0


async def record_referral(
    *,
    referrer_code: str,
    referred_user_id: UUID,
) -> bool:
    """Record a referral event for a new user who joined via deep link.

    Returns True if the referral was recorded, False if code not found
    or user already has a referral record.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        referrer_row = await conn.fetchrow(
            "SELECT id, user_id FROM referral_codes WHERE code=$1", referrer_code,
        )
        if referrer_row is None:
            logger.warning("referral.record.unknown_code code=%s", referrer_code)
            return False

        referrer_user_id: UUID = referrer_row["user_id"]

        if referrer_user_id == referred_user_id:
            return False

        try:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO referral_events (referrer_id, referred_id, code)
                    VALUES ($1, $2, $3)
                    """,
                    referrer_user_id, referred_user_id, referrer_code,
                )
                await conn.execute(
                    """
                    UPDATE referral_codes
                    SET uses = uses + 1, referred_users = referred_users + 1
                    WHERE user_id = $1
                    """,
                    referrer_user_id,
                )
        except Exception as exc:
            if "unique" in str(exc).lower():
                return False
            raise

    logger.info(
        "referral.recorded referrer=%s referred=%s code=%s",
        referrer_user_id, referred_user_id, referrer_code,
    )
    return True


def parse_ref_param(start_param: Optional[str]) -> Optional[str]:
    """Extract referral code from /start deep-link param.

    Telegram passes ``?start=ref_ABCD1234`` as the ``start_param``.
    Returns the code string or None if param is absent / wrong format.
    """
    if not start_param:
        return None
    if start_param.startswith("ref_"):
        code = start_param[4:]
        if len(code) == _CODE_LENGTH and all(c in _CODE_ALPHABET for c in code):
            return code
    return None
