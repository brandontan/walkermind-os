from __future__ import annotations

from ..auth import resolve_auth_provider_from_env
from ..storage.models import WalletBindingRecord, utc_now
from ..storage.repositories import WalletBindingRepository
from .models import WalletBinding, WalletContext


class WalletAuthService:
    """Wallet/auth resolver with optional persistence and non-live auth skeleton.

    Read/write separation:
    - resolve_wallet_binding: pure read — returns existing record or in-memory default, NEVER writes.
    - ensure_wallet_binding: write path — returns existing record or creates + persists a new one.
    """

    def __init__(self, repository: WalletBindingRepository | None = None) -> None:
        self._repository = repository
        self._auth_provider = resolve_auth_provider_from_env()

    def resolve_wallet_binding(
        self,
        *,
        user_id: str,
        wallet_binding_id: str,
        wallet_type: str,
        signature_type: str,
        funder_address: str,
        auth_state: str,
        mode: str,
    ) -> WalletBinding:
        """Read-only: return existing binding or transient default. Never writes."""
        if self._repository is not None:
            existing = self._repository.get_by_id(wallet_binding_id=wallet_binding_id)
            if existing is not None:
                return WalletBinding(**existing.__dict__)
        l1_context = self._auth_provider.bootstrap_l1_context(user_id=user_id, wallet_hint=funder_address)
        validated_state = self._auth_provider.validate_auth_state(auth_context=l1_context)
        now = utc_now()
        record = WalletBindingRecord(
            wallet_binding_id=wallet_binding_id,
            user_id=user_id,
            wallet_type=wallet_type,
            signature_type=signature_type,
            funder_address=self._auth_provider.normalize_funder_address(funder_address=funder_address),
            auth_state=validated_state.value if auth_state == "UNVERIFIED" else auth_state,
            mode=mode,
            auth_provider=l1_context.provider.value,
            created_at=now,
            updated_at=now,
        )
        return WalletBinding(**record.__dict__)

    def ensure_wallet_binding(
        self,
        *,
        user_id: str,
        wallet_binding_id: str,
        wallet_type: str,
        signature_type: str,
        funder_address: str,
        auth_state: str,
        mode: str,
    ) -> WalletBinding:
        """Write path: return existing binding or create + persist a new one."""
        if self._repository is not None:
            existing = self._repository.get_by_id(wallet_binding_id=wallet_binding_id)
            if existing is not None:
                return WalletBinding(**existing.__dict__)
        l1_context = self._auth_provider.bootstrap_l1_context(user_id=user_id, wallet_hint=funder_address)
        validated_state = self._auth_provider.validate_auth_state(auth_context=l1_context)
        now = utc_now()
        record = WalletBindingRecord(
            wallet_binding_id=wallet_binding_id,
            user_id=user_id,
            wallet_type=wallet_type,
            signature_type=signature_type,
            funder_address=self._auth_provider.normalize_funder_address(funder_address=funder_address),
            auth_state=validated_state.value if auth_state == "UNVERIFIED" else auth_state,
            mode=mode,
            auth_provider=l1_context.provider.value,
            created_at=now,
            updated_at=now,
        )
        if self._repository is not None:
            self._repository.upsert(record)
        return WalletBinding(**record.__dict__)

    def to_wallet_context(self, binding: WalletBinding) -> WalletContext:
        return WalletContext(
            user_id=binding.user_id,
            wallet_binding_id=binding.wallet_binding_id,
            wallet_type=binding.wallet_type,
            signature_type=binding.signature_type,
            auth_state=binding.auth_state,
            funder_address=binding.funder_address,
            mode=binding.mode,
            auth_provider=binding.auth_provider,
        )
