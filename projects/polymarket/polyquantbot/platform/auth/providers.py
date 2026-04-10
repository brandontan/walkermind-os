from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class WalletProvider(str, Enum):
    LEGACY = "legacy"
    POLYMARKET = "polymarket"


class WalletType(str, Enum):
    LEGACY_SESSION = "LEGACY_SESSION"
    EOA = "EOA"


class SignatureType(str, Enum):
    SESSION = "SESSION"
    EIP712 = "EIP712"


class AuthState(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    PENDING = "PENDING"
    READY = "READY"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class AuthContext:
    provider: WalletProvider
    wallet_type: WalletType
    signature_type: SignatureType
    auth_state: AuthState
    funder_address: str


class AuthProvider(Protocol):
    def bootstrap_l1_context(self, *, user_id: str, wallet_hint: str | None = None) -> AuthContext: ...

    def derive_or_load_l2_context(self, *, user_id: str, l1_context: AuthContext) -> AuthContext: ...

    def validate_auth_state(self, *, auth_context: AuthContext) -> AuthState: ...

    def normalize_funder_address(self, *, funder_address: str) -> str: ...


class PolymarketAuthProviderSkeleton:
    """Foundation-only scaffold with no live network calls."""

    def bootstrap_l1_context(self, *, user_id: str, wallet_hint: str | None = None) -> AuthContext:
        _ = user_id
        normalized_hint = self.normalize_funder_address(funder_address=wallet_hint or "0x0000000000000000000000000000000000000000")
        return AuthContext(
            provider=WalletProvider.POLYMARKET,
            wallet_type=WalletType.EOA,
            signature_type=SignatureType.EIP712,
            auth_state=AuthState.UNVERIFIED,
            funder_address=normalized_hint,
        )

    def derive_or_load_l2_context(self, *, user_id: str, l1_context: AuthContext) -> AuthContext:
        _ = user_id
        return l1_context

    def validate_auth_state(self, *, auth_context: AuthContext) -> AuthState:
        _ = auth_context
        return AuthState.UNVERIFIED

    def normalize_funder_address(self, *, funder_address: str) -> str:
        value = funder_address.strip().lower()
        if not value.startswith("0x"):
            return f"0x{value}" if value else "0x0000000000000000000000000000000000000000"
        return value


def resolve_auth_provider_from_env() -> AuthProvider:
    provider = os.getenv("PLATFORM_AUTH_PROVIDER", "skeleton").strip().lower()
    if provider in {"polymarket", "skeleton", "none"}:
        return PolymarketAuthProviderSkeleton()
    return PolymarketAuthProviderSkeleton()
