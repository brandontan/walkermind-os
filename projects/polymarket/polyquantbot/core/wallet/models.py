"""core/wallet/models.py — WalletModel: per-user real wallet record.

Stores the user identity, the on-chain Ethereum/Polygon wallet address, and
the AES-256-GCM-encrypted private key blob.

Rules:
    - ``encrypted_private_key`` is ALWAYS a ciphertext blob (Base64 string).
    - NEVER store plaintext private keys.
    - NEVER expose ``encrypted_private_key`` to any log or UI layer.
    - ``address`` is a checksummed 0x… hex string (42 chars).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class WalletModel:
    """Immutable per-user real wallet record.

    Attributes:
        user_id: Telegram user ID (int) — primary key.
        address: Ethereum/Polygon wallet address (``0x…``, 42 chars).
        encrypted_private_key: AES-256-GCM Base64 ciphertext of the 32-byte
            private key.  Never logged, never returned to callers.
        created_at: Unix timestamp (float) of wallet creation.
    """

    user_id: int
    address: str
    encrypted_private_key: str
    created_at: float = field(default_factory=time.time)

    def __repr__(self) -> str:
        """Safe repr — omits encrypted_private_key."""
        return (
            f"WalletModel(user_id={self.user_id!r}, "
            f"address={self.address!r}, "
            f"created_at={self.created_at!r})"
        )

    def public_dict(self) -> dict:
        """Return a safe public-facing dict (no private key material).

        Returns:
            Dict with ``user_id``, ``address``, ``created_at`` only.
        """
        return {
            "user_id": self.user_id,
            "address": self.address,
            "created_at": self.created_at,
        }
