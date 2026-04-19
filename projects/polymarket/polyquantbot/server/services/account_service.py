"""Account service foundation for multi-user ownership mapping."""
from __future__ import annotations

from projects.polymarket.polyquantbot.server.core.scope import ScopeResolutionError
from projects.polymarket.polyquantbot.server.schemas.multi_user import AccountCreate, AccountRecord, new_id, now_utc
from projects.polymarket.polyquantbot.server.storage.multi_user_store import MultiUserStore


class AccountService:
    def __init__(self, store: MultiUserStore) -> None:
        self._store = store

    def create_account(self, payload: AccountCreate) -> AccountRecord:
        user = self._store.get_user(payload.user_id)
        if user is None:
            raise ScopeResolutionError(f"user not found: {payload.user_id}")
        if user.tenant_id != payload.tenant_id:
            raise ScopeResolutionError("account tenant_id must match owner user tenant_id")

        account = AccountRecord(
            account_id=new_id("acct"),
            tenant_id=payload.tenant_id,
            user_id=payload.user_id,
            label=payload.label,
            created_at=now_utc(),
        )
        self._store.put_account(account)
        return account

    def get_account(self, account_id: str) -> AccountRecord | None:
        return self._store.get_account(account_id)
