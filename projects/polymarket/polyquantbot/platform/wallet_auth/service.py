from __future__ import annotations

from datetime import datetime, timezone

from .models import WalletBinding, WalletContext


class WalletAuthService:
    """Read-only wallet/auth context resolver for legacy bridge compatibility."""

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
        now = datetime.now(tz=timezone.utc)
        return WalletBinding(
            wallet_binding_id=wallet_binding_id,
            user_id=user_id,
            wallet_type=wallet_type,
            signature_type=signature_type,
            funder_address=funder_address,
            auth_state=auth_state,
            mode=mode,
            created_at=now,
            updated_at=now,
        )

    def to_wallet_context(self, binding: WalletBinding) -> WalletContext:
        return WalletContext(
            user_id=binding.user_id,
            wallet_binding_id=binding.wallet_binding_id,
            wallet_type=binding.wallet_type,
            signature_type=binding.signature_type,
            auth_state=binding.auth_state,
            funder_address=binding.funder_address,
            mode=binding.mode,
        )
