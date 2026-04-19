"""In-memory storage boundary for multi-user foundation entities."""
from __future__ import annotations

from projects.polymarket.polyquantbot.server.schemas.multi_user import (
    AccountRecord,
    UserRecord,
    UserSettingsRecord,
    WalletRecord,
)


class InMemoryMultiUserStore:
    def __init__(self) -> None:
        self.users: dict[str, UserRecord] = {}
        self.user_settings: dict[str, UserSettingsRecord] = {}
        self.accounts: dict[str, AccountRecord] = {}
        self.wallets: dict[str, WalletRecord] = {}

    def put_user(self, user: UserRecord) -> None:
        self.users[user.user_id] = user

    def put_user_settings(self, settings: UserSettingsRecord) -> None:
        self.user_settings[settings.settings_id] = settings

    def put_account(self, account: AccountRecord) -> None:
        self.accounts[account.account_id] = account

    def put_wallet(self, wallet: WalletRecord) -> None:
        self.wallets[wallet.wallet_id] = wallet

    def get_user(self, user_id: str) -> UserRecord | None:
        return self.users.get(user_id)

    def get_account(self, account_id: str) -> AccountRecord | None:
        return self.accounts.get(account_id)

    def get_wallet(self, wallet_id: str) -> WalletRecord | None:
        return self.wallets.get(wallet_id)
