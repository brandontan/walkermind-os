"""Reverse Telegram-link — account unification (WebTrader + Telegram = one account).

A Telegram-first user can already reach WebTrader (Telegram Login Widget or
link_email). This module adds the REVERSE: an EMAIL-first WebTrader user links
their Telegram so both surfaces resolve to ONE canonical account (one user_id,
one user_settings row → LIVE/PAPER state always in sync).

Flow (one-time code):
  1. WebTrader (authenticated email account) calls generate_link_code(user_id).
  2. The user sends `/link <code>` to the bot.
  3. redeem_link_code(code, telegram_user_id, username) attaches the Telegram
     identity to the canonical (email) account.

Duplicate handling: if the user already pressed /start, a SEPARATE fresh
Telegram account exists. We MOVE its telegram_user_id onto the canonical
account and TOMBSTONE the fresh duplicate (synthetic unreachable email +
merged_into pointer) — non-destructive, because several user FKs lack
ON DELETE CASCADE so deletion is unsafe on this money schema. If the Telegram
account has real trading history we BLOCK and defer to an operator merge so no
trades are ever silently orphaned.
"""
from __future__ import annotations

import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional
from uuid import UUID

from ... import audit
from ...database import get_pool

logger = logging.getLogger(__name__)

# Unambiguous alphabet (no 0/O/1/I/L) for human-typed codes.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LEN = 8
CODE_TTL_MINUTES = 15

_NORMALISE_RE = re.compile(r"[^A-Z0-9]")

# Money-bearing tables that mark a Telegram account as "not fresh" (i.e. it has
# real activity that must not be silently orphaned by a merge).
_ACTIVITY_TABLES = ("positions", "orders", "deposits", "withdrawals")


class LinkOutcome(str, Enum):
    OK_LINKED = "ok_linked"            # clean attach (no duplicate existed)
    OK_MERGED = "ok_merged"            # fresh duplicate tombstoned + reassigned
    OK_ALREADY = "ok_already"          # this Telegram is already on the account
    INVALID_CODE = "invalid_code"
    EXPIRED = "expired"
    PRIMARY_ALREADY_LINKED = "primary_already_linked"  # account has another TG
    TG_HAS_HISTORY = "tg_has_history"  # duplicate TG account has real activity


@dataclass
class LinkResult:
    outcome: LinkOutcome
    message: str
    canonical_user_id: Optional[UUID] = None


class AccountLinkError(Exception):
    """Raised by generate_link_code when a code cannot be minted."""


def _normalise(code: str) -> str:
    return _NORMALISE_RE.sub("", (code or "").strip().upper())


def format_code_for_display(code: str) -> str:
    """ABCDEFGH -> ABCD-EFGH (cosmetic; redeem normalises either way)."""
    c = _normalise(code)
    return f"{c[:4]}-{c[4:]}" if len(c) == _CODE_LEN else c


async def generate_link_code(user_id: UUID) -> str:
    """Mint a fresh one-time link code for an EMAIL account with no Telegram.

    Invalidates any prior unconsumed codes for the user (one active code at a
    time). Raises AccountLinkError if the account already has a Telegram linked.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        linked = await conn.fetchval(
            "SELECT telegram_user_id FROM users WHERE id = $1", user_id,
        )
        if linked is not None:
            raise AccountLinkError("This account already has a Telegram linked.")

        # One active code per user — drop older unconsumed ones.
        await conn.execute(
            "DELETE FROM account_link_codes "
            "WHERE user_id = $1 AND consumed_at IS NULL",
            user_id,
        )

        expires_at = datetime.now(timezone.utc) + timedelta(minutes=CODE_TTL_MINUTES)
        # Retry a few times on the astronomically unlikely PK collision.
        for _ in range(5):
            code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LEN))
            try:
                await conn.execute(
                    "INSERT INTO account_link_codes (code, user_id, expires_at) "
                    "VALUES ($1, $2, $3)",
                    code, user_id, expires_at,
                )
                return code
            except Exception:  # noqa: BLE001 — PK collision, regenerate
                continue
        raise AccountLinkError("Could not generate a link code, please retry.")


async def _is_fresh(conn, user_id: UUID) -> bool:
    """A Telegram account is fresh if it is paper-mode and has zero money
    activity. Table names are fixed literals (no user input)."""
    mode = await conn.fetchval(
        "SELECT trading_mode FROM user_settings WHERE user_id = $1", user_id,
    )
    if mode == "live":
        return False
    for table in _ACTIVITY_TABLES:
        n = await conn.fetchval(
            f"SELECT COUNT(*) FROM {table} WHERE user_id = $1", user_id,  # noqa: S608
        )
        if n:
            return False
    return True


async def redeem_link_code(
    code: str,
    telegram_user_id: int,
    telegram_username: Optional[str],
) -> LinkResult:
    """Redeem a link code in the bot and attach the Telegram identity to the
    canonical (email) account. See module docstring for duplicate handling."""
    norm = _normalise(code)
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT user_id, expires_at, consumed_at "
                "FROM account_link_codes WHERE code = $1 FOR UPDATE",
                norm,
            )
            if row is None or row["consumed_at"] is not None:
                return LinkResult(LinkOutcome.INVALID_CODE,
                                  "That link code is invalid or already used.")
            if row["expires_at"] < datetime.now(timezone.utc):
                return LinkResult(LinkOutcome.EXPIRED,
                                  "That link code has expired — generate a new one in WebTrader.")

            primary_id: UUID = row["user_id"]
            primary = await conn.fetchrow(
                "SELECT id, telegram_user_id FROM users WHERE id = $1", primary_id,
            )
            if primary is None:
                return LinkResult(LinkOutcome.INVALID_CODE, "Account not found.")

            # Canonical account already has a Telegram?
            if primary["telegram_user_id"] is not None:
                if primary["telegram_user_id"] == telegram_user_id:
                    await _consume(conn, norm)
                    return LinkResult(LinkOutcome.OK_ALREADY,
                                      "This Telegram is already linked to your account.",
                                      primary_id)
                return LinkResult(
                    LinkOutcome.PRIMARY_ALREADY_LINKED,
                    "Your WebTrader account is already linked to a different Telegram.",
                )

            # Does a duplicate Telegram account already exist for this tg id?
            dup = await conn.fetchrow(
                "SELECT id FROM users WHERE telegram_user_id = $1", telegram_user_id,
            )

            if dup is None:
                await conn.execute(
                    "UPDATE users SET telegram_user_id = $1, "
                    "username = COALESCE(username, $2) WHERE id = $3",
                    telegram_user_id, telegram_username, primary_id,
                )
                await _consume(conn, norm)
                await _audit_merge(primary_id, None, telegram_user_id, "linked")
                return LinkResult(LinkOutcome.OK_LINKED,
                                  "✅ Telegram linked to your account.", primary_id)

            dup_id: UUID = dup["id"]
            if dup_id == primary_id:
                await _consume(conn, norm)
                return LinkResult(LinkOutcome.OK_ALREADY,
                                  "This Telegram is already linked to your account.",
                                  primary_id)

            # Duplicate exists — only absorb it if it is fresh (no history).
            if not await _is_fresh(conn, dup_id):
                return LinkResult(
                    LinkOutcome.TG_HAS_HISTORY,
                    "Your Telegram already has an active account with trading history. "
                    "Account merge with history needs manual review — please contact support.",
                )

            # Tombstone the fresh duplicate (free its UNIQUE telegram_user_id +
            # satisfy users_identity_required via a synthetic unreachable email),
            # then move the Telegram identity onto the canonical account.
            synthetic_email = f"merged-{dup_id}@telegram.local"
            await conn.execute(
                "UPDATE users SET telegram_user_id = NULL, "
                "email = COALESCE(email, $2), merged_into = $3 WHERE id = $1",
                dup_id, synthetic_email, primary_id,
            )
            await conn.execute(
                "UPDATE users SET telegram_user_id = $1, "
                "username = COALESCE(username, $2) WHERE id = $3",
                telegram_user_id, telegram_username, primary_id,
            )
            await _consume(conn, norm)
            await _audit_merge(primary_id, dup_id, telegram_user_id, "merged")
            return LinkResult(LinkOutcome.OK_MERGED,
                              "✅ Telegram linked. Your accounts are now unified.",
                              primary_id)


async def _consume(conn, code: str) -> None:
    await conn.execute(
        "UPDATE account_link_codes SET consumed_at = NOW() WHERE code = $1", code,
    )


async def _audit_merge(
    canonical_id: UUID,
    tombstoned_id: Optional[UUID],
    telegram_user_id: int,
    kind: str,
) -> None:
    await audit.write(
        actor_role="user",
        action="account_link_telegram",
        user_id=canonical_id,
        payload={
            "kind": kind,
            "telegram_user_id": telegram_user_id,
            "tombstoned_user_id": str(tombstoned_id) if tombstoned_id else None,
        },
    )
