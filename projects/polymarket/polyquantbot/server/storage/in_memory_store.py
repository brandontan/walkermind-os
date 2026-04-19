"""In-memory storage boundary for multi-user foundation entities."""
from __future__ import annotations

from projects.polymarket.polyquantbot.server.schemas.auth_session import SessionContext
from projects.polymarket.polyquantbot.server.schemas.multi_user import (
    AccountRecord,
    UserRecord,
    UserSettingsRecord,
    WalletRecord,
)
from projects.polymarket.polyquantbot.server.storage.multi_user_store import MultiUserStore


class InMemoryMultiUserStore(MultiUserStore):
    def __init__(self) -> None:
        self.users: dict[str, UserRecord] = {}
        self.user_settings: dict[str, UserSettingsRecord] = {}
        self.accounts: dict[str, AccountRecord] = {}
        self.wallets: dict[str, WalletRecord] = {}
        self.sessions: dict[str, SessionContext] = {}

    def put_user(self, user: UserRecord) -> None:
        self.users[user.user_id] = user

    def put_user_settings(self, settings: UserSettingsRecord) -> None:
        self.user_settings[settings.settings_id] = settings

    def get_user_settings_for_user(self, user_id: str) -> UserSettingsRecord | None:
        for s in self.user_settings.values():
            if s.user_id == user_id:
                return s
        return None

    def put_account(self, account: AccountRecord) -> None:
        self.accounts[account.account_id] = account

    def put_wallet(self, wallet: WalletRecord) -> None:
        self.wallets[wallet.wallet_id] = wallet

    def put_session(self, session: SessionContext) -> None:
        self.sessions[session.session_id] = session

    def get_user(self, user_id: str) -> UserRecord | None:
        return self.users.get(user_id)

    def get_account(self, account_id: str) -> AccountRecord | None:
        return self.accounts.get(account_id)

    def list_accounts_for_user(self, tenant_id: str, user_id: str) -> list[AccountRecord]:
        return [
            a for a in self.accounts.values()
            if a.tenant_id == tenant_id and a.user_id == user_id
        ]

    def get_wallet(self, wallet_id: str) -> WalletRecord | None:
        return self.wallets.get(wallet_id)

    def list_wallets_for_account(self, tenant_id: str, account_id: str) -> list[WalletRecord]:
        return [
            w for w in self.wallets.values()
            if w.tenant_id == tenant_id and w.account_id == account_id
        ]

    def get_session(self, session_id: str) -> SessionContext | None:
        return self.sessions.get(session_id)

    def get_user_by_external_id(self, tenant_id: str, external_id: str) -> UserRecord | None:
        for user in self.users.values():
            if user.tenant_id == tenant_id and user.external_id == external_id:
                return user
        return None
