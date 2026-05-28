"""Polymarket Safe-proxy address derivation + idempotent backfill.

The Safe proxy address for an EOA is deterministic — CREATE2 from the
Polymarket Safe factory keyed on the signer address — so it can be computed
LOCALLY without any Builder Program credentials and stored well before the
custody migration cuts over. That is exactly what this module does:

  * ``compute_safe_address(signer_pk)`` — pure local derivation.
  * ``backfill_safe_addresses()``       — populate ``wallets.safe_address`` for
                                          every wallet missing it. Idempotent.
  * ``set_safe_address_in_conn(...)``   — store on a connection (called inline
                                          by vault.create_wallet_for_user so
                                          new users get the column from day 1).

The Builder relayer is NOT touched here — credentialed calls (Safe deploy,
gasless transfers) belong to later chunks. This lane only writes a
pre-computed address that is harmless in EOA mode and ready in Safe mode.
"""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from ..config import get_settings
from ..database import get_pool
from .generator import decrypt_pk

logger = logging.getLogger(__name__)


class SafeDerivationUnavailable(RuntimeError):
    """The relayer SDK is missing, so Safe derivation cannot run.

    Distinct from BuilderRelayerUnavailable (credentials/flag) because address
    derivation needs only the SDK import, not the Builder Program creds.
    """


def compute_safe_address(signer_pk: str) -> str:
    """Return the deterministic Polymarket Safe-proxy address for a signer key.

    Pure local CREATE2 derivation via ``RelayClient.get_expected_safe`` — no
    network call, no credentials. Constructs the RelayClient WITHOUT a builder
    config (only the signer is required for derivation) so this works in any
    environment that has the SDK installed.
    """
    if not signer_pk:
        raise ValueError("compute_safe_address: empty signer key")
    try:
        from py_builder_relayer_client.client import RelayClient
    except Exception as exc:
        raise SafeDerivationUnavailable(
            f"py-builder-relayer-client not installed or import failed: {exc}"
        ) from exc
    settings = get_settings()
    client = RelayClient(settings.POLY_RELAYER_URL, 137, private_key=signer_pk)
    return str(client.get_expected_safe())


async def set_safe_address_in_conn(
    conn, user_id: UUID, signer_pk: str,
) -> Optional[str]:
    """Compute and store the Safe address for a user on an open connection.

    Called inline from wallet creation so new rows get the column populated
    atomically with the wallet insert. Returns the address, or None if
    derivation is unavailable in this environment (the column stays NULL and
    the backfill can fill it later).
    """
    try:
        addr = compute_safe_address(signer_pk)
    except SafeDerivationUnavailable as exc:
        logger.warning(
            "safe_address_skip user=%s (SDK unavailable): %s", user_id, exc
        )
        return None
    await conn.execute(
        "UPDATE wallets SET safe_address = $2 WHERE user_id = $1 "
        "AND safe_address IS NULL",
        user_id, addr,
    )
    return addr


async def backfill_safe_addresses(batch_size: int = 200) -> dict[str, int]:
    """Populate ``wallets.safe_address`` for every wallet still missing it.

    Idempotent: only touches rows where ``safe_address IS NULL``. Decrypts the
    user's HD private key, derives the Safe address locally, and writes it.
    Safe to call at boot or as a manual backfill — no on-chain effect.

    Returns a summary ``{scanned, filled, skipped}``.
    """
    settings = get_settings()
    pool = get_pool()
    scanned = filled = skipped = 0
    while True:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT user_id, encrypted_key FROM wallets "
                "WHERE safe_address IS NULL "
                "ORDER BY user_id LIMIT $1",
                batch_size,
            )
        if not rows:
            break
        for row in rows:
            scanned += 1
            try:
                pk = decrypt_pk(row["encrypted_key"], settings.WALLET_ENCRYPTION_KEY)
                addr = compute_safe_address(pk)
            except SafeDerivationUnavailable as exc:
                logger.error("backfill_safe_address aborted: %s", exc)
                return {"scanned": scanned, "filled": filled, "skipped": skipped}
            except Exception as exc:
                logger.error(
                    "backfill_safe_address_failed user=%s error=%s",
                    row["user_id"], exc,
                )
                skipped += 1
                continue
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE wallets SET safe_address = $2 "
                    "WHERE user_id = $1 AND safe_address IS NULL",
                    row["user_id"], addr,
                )
            filled += 1
        if len(rows) < batch_size:
            break
    logger.info(
        "backfill_safe_addresses scanned=%s filled=%s skipped=%s",
        scanned, filled, skipped,
    )
    return {"scanned": scanned, "filled": filled, "skipped": skipped}
