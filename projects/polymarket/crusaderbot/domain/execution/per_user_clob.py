"""Per-user CLOB client resolver with the cross-user isolation assertion.

Step 4 of the per-user execution lane (the on-chain isolation piece).

Step 1 (#1731) built ``get_user_clob_client``: every user gets a CLOB
client constructed from their OWN private key + OWN deposit wallet, cached
per ``user_id`` with single-flight build + LRU eviction.

Step 2 (#1736) persisted the resolved deposit wallet on
``wallets.polymarket_deposit_wallet`` so Step 4 has a stable anchor.

Step 3 (#1740) widened the deposit watcher to scan the same column.

Step 4 (this module) is the SAFETY-CRITICAL piece: every per-user order
build asserts ``resolved_wallet == wallets.polymarket_deposit_wallet``
BEFORE the client touches the broker. The assertion is the in-code
enforcement of the #1730 §4 cross-user isolation invariant:

    a keying bug here = user A's order built with user B's funds.

The assertion REFUSES to sign on drift. There is no automatic JIT
backfill of the column — the operator runs
``backfill_deposit_wallets()`` after migration 094 so EVERY row has the
canonical address before per-user execution flips on. A NULL column
therefore signals a configuration error (Step 2 backfill skipped or
failed for this user) rather than a transient state we should silently
fix on the trading hot path.

Gated by ``USE_PER_USER_EXECUTION`` (default OFF). When OFF, the
single-wallet ``get_clob_client(s)`` path is byte-unchanged.
"""
from __future__ import annotations

import logging
from typing import Optional, Protocol
from uuid import UUID

from ...config import Settings, get_settings
from ...integrations.clob.exceptions import ClobConfigError
from ...integrations.clob.user_client import (
    PerUserClobError,
    PerUserClobIsolationError,
    get_user_clob_client_with_wallet,
)

logger = logging.getLogger(__name__)

__all__ = [
    "WalletIdentityMismatch",
    "resolve_user_clob_client",
]


class _ClobClientLike(Protocol):
    """Narrow protocol — anything that quacks like a ClobV2Client."""

    async def post_order(self, **kwargs) -> dict: ...
    async def cancel_order(self, order_id: str) -> dict: ...


class WalletIdentityMismatch(PerUserClobError):
    """The SDK-resolved deposit wallet does NOT match the persisted column.

    Raised before any broker call so a misrouted key cannot sign for the
    wrong funder. ALWAYS treat as SAFETY-CRITICAL — kill the order, alert
    the operator, audit the diff, do NOT auto-repair the column.
    """


async def resolve_user_clob_client(
    *,
    user_id: UUID,
    conn,
    settings: Optional[Settings] = None,
) -> _ClobClientLike:
    """Return the user's CLOB client after asserting wallet identity.

    Reads ``wallets.polymarket_deposit_wallet`` for ``user_id`` on the
    provided connection (the caller should already be inside the
    idempotency-claim transaction, so the wallet read sees the same
    snapshot), compares against the SDK-resolved address from the
    per-user cache (#1731 + #1732), and returns the client only on
    match (case-insensitive — Ethereum checksums vs lowercase storage).

    Raises:
        PerUserClobIsolationError: ``user_id`` is not a UUID.
        ClobConfigError: ``wallets.polymarket_deposit_wallet`` is NULL
            (Step 2 backfill missed this row — operator must fix before
            per-user execution can be used for this user).
        WalletIdentityMismatch: the column value disagrees with the SDK
            resolution — keying bug or wallet migration; refuse to sign.
    """
    if not isinstance(user_id, UUID):
        # Mirror user_client's structured warning so a SAFETY-CRITICAL
        # routing bug surfaces in logs even if the caller swallows.
        logger.warning(
            "resolve_user_clob_client: ISOLATION VIOLATION — user_id "
            "missing or wrong type (value=%r, type=%s); refusing",
            user_id, type(user_id).__name__,
        )
        raise PerUserClobIsolationError(
            "resolve_user_clob_client requires a UUID user_id"
        )

    s = settings or get_settings()
    client, resolved = await get_user_clob_client_with_wallet(user_id, s)

    row = await conn.fetchrow(
        "SELECT polymarket_deposit_wallet FROM wallets WHERE user_id = $1",
        user_id,
    )
    if row is None:
        raise ClobConfigError(
            f"resolve_user_clob_client: no wallets row for user_id={user_id} "
            "(create_wallet_for_user must run before any live order)"
        )
    stored = row["polymarket_deposit_wallet"]
    if not stored:
        raise ClobConfigError(
            f"resolve_user_clob_client: wallets.polymarket_deposit_wallet "
            f"is NULL for user_id={user_id} — run backfill_deposit_wallets() "
            "after migration 094 before flipping USE_PER_USER_EXECUTION"
        )

    if str(resolved).lower() != str(stored).lower():
        logger.warning(
            "resolve_user_clob_client: WALLET IDENTITY MISMATCH "
            "user_id=%s resolved=%s stored=%s — refusing to sign",
            user_id, resolved, stored,
        )
        raise WalletIdentityMismatch(
            f"deposit wallet drift for user_id={user_id}: "
            f"sdk={resolved!s} stored={stored!s}"
        )

    return client
