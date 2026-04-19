"""Wallet service foundation for tenant/user/account ownership boundaries."""
from __future__ import annotations

from projects.polymarket.polyquantbot.server.core.scope import ResourceOwnership, ScopeResolutionError, require_ownership
from projects.polymarket.polyquantbot.server.schemas.multi_user import ScopeContext, WalletCreate, WalletRecord, new_id, now_utc
from projects.polymarket.polyquantbot.server.storage.in_memory_store import InMemoryMultiUserStore


class WalletService:
    def __init__(self, store: InMemoryMultiUserStore) -> None:
        self._store = store

    def create_wallet(self, payload: WalletCreate) -> WalletRecord:
        account = self._store.get_account(payload.account_id)
        if account is None:
            raise ScopeResolutionError(f"account not found: {payload.account_id}")
        if account.tenant_id != payload.tenant_id:
            raise ScopeResolutionError("wallet tenant_id must match owner account tenant_id")
        if account.user_id != payload.user_id:
            raise ScopeResolutionError("wallet user_id must match owner account user_id")

        wallet = WalletRecord(
            wallet_id=new_id("wlt"),
            tenant_id=payload.tenant_id,
            user_id=payload.user_id,
            account_id=payload.account_id,
            address=payload.address,
            created_at=now_utc(),
        )
        self._store.put_wallet(wallet)
        return wallet

    def get_wallet_for_scope(self, scope: ScopeContext, wallet_id: str) -> WalletRecord:
        wallet = self._store.get_wallet(wallet_id)
        if wallet is None:
            raise ScopeResolutionError(f"wallet not found: {wallet_id}")

        require_ownership(
            scope=scope,
            ownership=ResourceOwnership(
                resource_type="wallet",
                resource_id=wallet_id,
                tenant_id=wallet.tenant_id,
                user_id=wallet.user_id,
            ),
        )
        return wallet
