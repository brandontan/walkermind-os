"""Polymarket deposit-wallet persistence (per-user execution Step 2).

Step 1 (#1731) shipped ``integrations/clob/user_client.resolve_deposit_wallet_creds``
which builds an ``AsyncSecureClient`` against the user's HD private key — the
polymarket SDK runs an on-chain factory check to pick the deterministic deposit
wallet (beacon vs UUPS). That resolution is what every per-user order will sign
against.

This module persists that resolved address on the ``wallets`` row so:

* the per-user CLOB client built in Step 4 can assert
  ``resolved_wallet == wallets.polymarket_deposit_wallet`` on every order build,
  enforcing the #1730 §4 cross-user isolation invariant in code (refuse to sign
  if the SDK-resolved wallet drifts from the stored one — that drift means a
  keying bug or a wallet migration, never a normal state);
* Step 4 / the deposit watcher do not re-derive on every read;
* the existing ``wallet/safe.py`` Safe-proxy address column gets a sibling for
  the EIP-7702 deposit-wallet path.

Mirrors ``wallet/safe.py`` shape:

* ``resolve_deposit_wallet(signer_pk)`` — pure SDK resolution, no credentials
  (delegates to ``integrations/clob/user_client.resolve_deposit_wallet`` to
  keep the SDK touch surface in one place).
* ``set_deposit_wallet_in_conn(...)`` — store on a connection (called inline
  by ``vault.create_wallet_for_user`` so new users get the column from day 1).
* ``backfill_deposit_wallets()`` — populate ``polymarket_deposit_wallet`` for
  every wallet still missing it. Idempotent. SEQUENTIAL per the #1730 Gemini
  advisory: backfill drives the polymarket SDK once per user and asyncio.gather
  would stampede both the local DB pool AND the Polymarket API.
"""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from ..config import get_settings
from ..database import get_pool
from ..integrations.clob.user_client import (
    PerUserClobError,
    resolve_deposit_wallet,
)
from .generator import decrypt_pk

# Sentinel cursor lower bound for the backfill loop. ``user_id > $cursor`` with
# this start value sweeps the whole table once; subsequent fetches advance the
# cursor past the last row seen so transient-fail rows (stay NULL on this run)
# cannot infinitely re-appear in the next fetch.
_UUID_MIN = UUID(int=0)

logger = logging.getLogger(__name__)


class DepositWalletDerivationUnavailable(RuntimeError):
    """The polymarket SDK is missing, so deposit-wallet derivation cannot run.

    Distinct from ``SafeDerivationUnavailable`` (Builder relayer SDK) — that one
    is for the Safe-proxy address derivation. This one is for the Polymarket
    deposit-wallet derivation that the per-user CLOB client signs against.
    """


async def _resolve(signer_pk: str) -> str:
    """Wallet-only SDK resolution. Maps a missing-SDK ImportError to the typed
    ``DepositWalletDerivationUnavailable`` sentinel so callers can degrade
    gracefully in environments without the polymarket SDK installed (CI smoke
    tests, paper-only runs). Empty-key + other resolution errors propagate via
    the upstream ``user_client.resolve_deposit_wallet`` (PerUserClobError for
    empty key — programmer bug, not environment-shaped — is preserved).
    """
    try:
        return await resolve_deposit_wallet(signer_pk)
    except ImportError as exc:
        raise DepositWalletDerivationUnavailable(
            f"polymarket SDK not installed or import failed: {exc}"
        ) from exc


async def set_deposit_wallet_in_conn(
    conn, user_id: UUID, signer_pk: str,
) -> Optional[str]:
    """Resolve and store the deposit wallet for a user on an open connection.

    Called inline from ``vault.create_wallet_for_user`` so new rows get the
    column populated atomically with the wallet insert. Returns the address,
    or None if the SDK is unavailable in this environment (the column stays
    NULL and the backfill can fill it later).

    Any other resolution failure (network, on-chain factory error) is logged
    and returns None — the wallet insert MUST land regardless of whether the
    Polymarket SDK can reach the chain right now. The backfill is the safety
    net for transient failures.
    """
    try:
        addr = await _resolve(signer_pk)
    except DepositWalletDerivationUnavailable as exc:
        logger.warning(
            "polymarket_deposit_wallet_skip user=%s (SDK unavailable): %s",
            user_id, exc,
        )
        return None
    except PerUserClobError:
        raise
    except Exception as exc:  # noqa: BLE001
        # Transient resolve failure during signup must not block wallet creation.
        # backfill_deposit_wallets is the safety net — logs the user_id so the
        # operator can target a retry.
        logger.warning(
            "polymarket_deposit_wallet_resolve_failed user=%s error=%s",
            user_id, exc,
        )
        return None
    await conn.execute(
        "UPDATE wallets SET polymarket_deposit_wallet = $2 WHERE user_id = $1 "
        "AND polymarket_deposit_wallet IS NULL",
        user_id, addr,
    )
    return addr


async def backfill_deposit_wallets(batch_size: int = 200) -> dict[str, int]:
    """Populate ``wallets.polymarket_deposit_wallet`` for every wallet missing it.

    Idempotent: only touches rows where ``polymarket_deposit_wallet IS NULL``.
    Decrypts the user's HD private key, resolves the deposit wallet via the
    polymarket SDK, writes it.

    **SEQUENTIAL by design** (#1730 Gemini advisory): no ``asyncio.gather`` —
    every iteration drives one polymarket API call AND one DB write; parallel
    fan-out would stampede the local DB pool and the Polymarket SDK's HTTP
    client at the same time. The Safe backfill (``wallet/safe.py``) follows
    the same pattern.

    Returns a summary ``{scanned, filled, skipped}``. On SDK unavailability,
    aborts the run and returns the partial counts so the operator can see how
    far it got before the missing dependency was detected.
    """
    settings = get_settings()
    pool = get_pool()
    scanned = filled = skipped = 0
    # Cursor-based pagination on user_id. WHERE IS NULL alone is unsafe here:
    # a skipped row (transient resolve failure) stays NULL on this run, so the
    # next fetch would return the same row — if ≥ batch_size rows fail in one
    # batch the loop never terminates. The cursor advances past every row seen
    # this run (including skipped rows); the WHERE IS NULL filter still skips
    # rows already filled by a previous backfill. Identified by gemini-code-
    # assist on PR #1736.
    last_user_id: UUID = _UUID_MIN
    while True:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT user_id, encrypted_key FROM wallets "
                "WHERE polymarket_deposit_wallet IS NULL AND user_id > $1 "
                "ORDER BY user_id LIMIT $2",
                last_user_id, batch_size,
            )
        if not rows:
            break
        for row in rows:
            scanned += 1
            try:
                pk = decrypt_pk(row["encrypted_key"], settings.WALLET_ENCRYPTION_KEY)
                addr = await _resolve(pk)
            except DepositWalletDerivationUnavailable as exc:
                logger.error("backfill_deposit_wallets aborted: %s", exc)
                return {"scanned": scanned, "filled": filled, "skipped": skipped}
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "backfill_deposit_wallet_failed user=%s error=%s",
                    row["user_id"], exc,
                )
                skipped += 1
                continue
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE wallets SET polymarket_deposit_wallet = $2 "
                    "WHERE user_id = $1 AND polymarket_deposit_wallet IS NULL",
                    row["user_id"], addr,
                )
            filled += 1
        last_user_id = rows[-1]["user_id"]
        if len(rows) < batch_size:
            break
    logger.info(
        "backfill_deposit_wallets scanned=%s filled=%s skipped=%s",
        scanned, filled, skipped,
    )
    return {"scanned": scanned, "filled": filled, "skipped": skipped}
