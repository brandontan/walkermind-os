"""Multi-user storage boundary — abstract base and persistent implementation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Final

import structlog

from projects.polymarket.polyquantbot.server.schemas.multi_user import (
    AccountRecord,
    UserRecord,
    UserSettingsRecord,
    WalletRecord,
)

log = structlog.get_logger(__name__)


class MultiUserStoreError(RuntimeError):
    """Raised when multi-user store data cannot be read or written."""


class MultiUserStore:
    def put_user(self, user: UserRecord) -> None:
        raise NotImplementedError

    def get_user(self, user_id: str) -> UserRecord | None:
        raise NotImplementedError

    def put_user_settings(self, settings: UserSettingsRecord) -> None:
        raise NotImplementedError

    def get_user_settings_for_user(self, user_id: str) -> UserSettingsRecord | None:
        raise NotImplementedError

    def put_account(self, account: AccountRecord) -> None:
        raise NotImplementedError

    def get_account(self, account_id: str) -> AccountRecord | None:
        raise NotImplementedError

    def list_accounts_for_user(self, tenant_id: str, user_id: str) -> list[AccountRecord]:
        raise NotImplementedError

    def put_wallet(self, wallet: WalletRecord) -> None:
        raise NotImplementedError

    def get_wallet(self, wallet_id: str) -> WalletRecord | None:
        raise NotImplementedError

    def list_wallets_for_account(self, tenant_id: str, account_id: str) -> list[WalletRecord]:
        raise NotImplementedError


class PersistentMultiUserStore(MultiUserStore):
    """Local-file JSON multi-user store with deterministic overwrite semantics."""

    _FORMAT_VERSION: Final[int] = 1

    def __init__(self, storage_path: Path) -> None:
        self._storage_path = storage_path
        self._users: dict[str, UserRecord] = {}
        self._user_settings: dict[str, UserSettingsRecord] = {}
        self._accounts: dict[str, AccountRecord] = {}
        self._wallets: dict[str, WalletRecord] = {}
        self._load_from_disk()

    def put_user(self, user: UserRecord) -> None:
        self._users[user.user_id] = user
        self._persist_to_disk()
        log.debug("multi_user_store_user_persisted", user_id=user.user_id)

    def get_user(self, user_id: str) -> UserRecord | None:
        return self._users.get(user_id)

    def put_user_settings(self, settings: UserSettingsRecord) -> None:
        self._user_settings[settings.settings_id] = settings
        self._persist_to_disk()

    def get_user_settings_for_user(self, user_id: str) -> UserSettingsRecord | None:
        for s in self._user_settings.values():
            if s.user_id == user_id:
                return s
        return None

    def put_account(self, account: AccountRecord) -> None:
        self._accounts[account.account_id] = account
        self._persist_to_disk()
        log.debug("multi_user_store_account_persisted", account_id=account.account_id)

    def get_account(self, account_id: str) -> AccountRecord | None:
        return self._accounts.get(account_id)

    def list_accounts_for_user(self, tenant_id: str, user_id: str) -> list[AccountRecord]:
        return [
            a for a in self._accounts.values()
            if a.tenant_id == tenant_id and a.user_id == user_id
        ]

    def put_wallet(self, wallet: WalletRecord) -> None:
        self._wallets[wallet.wallet_id] = wallet
        self._persist_to_disk()
        log.debug("multi_user_store_wallet_persisted", wallet_id=wallet.wallet_id)

    def get_wallet(self, wallet_id: str) -> WalletRecord | None:
        return self._wallets.get(wallet_id)

    def list_wallets_for_account(self, tenant_id: str, account_id: str) -> list[WalletRecord]:
        return [
            w for w in self._wallets.values()
            if w.tenant_id == tenant_id and w.account_id == account_id
        ]

    def _load_from_disk(self) -> None:
        if not self._storage_path.exists():
            return

        try:
            raw_payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise MultiUserStoreError(
                "persistent multi-user store contains invalid JSON"
            ) from exc

        if not isinstance(raw_payload, dict):
            raise MultiUserStoreError(
                "persistent multi-user store payload must be an object"
            )

        version = raw_payload.get("version")
        if version != self._FORMAT_VERSION:
            raise MultiUserStoreError(
                f"unsupported persistent multi-user store version: {version}"
            )

        for item in raw_payload.get("users") or []:
            record = UserRecord.model_validate(item)
            self._users[record.user_id] = record

        for item in raw_payload.get("user_settings") or []:
            record = UserSettingsRecord.model_validate(item)
            self._user_settings[record.settings_id] = record

        for item in raw_payload.get("accounts") or []:
            record = AccountRecord.model_validate(item)
            self._accounts[record.account_id] = record

        for item in raw_payload.get("wallets") or []:
            record = WalletRecord.model_validate(item)
            self._wallets[record.wallet_id] = record

    def _persist_to_disk(self) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self._FORMAT_VERSION,
            "users": [
                u.model_dump(mode="json")
                for u in sorted(self._users.values(), key=lambda r: r.user_id)
            ],
            "user_settings": [
                s.model_dump(mode="json")
                for s in sorted(self._user_settings.values(), key=lambda r: r.settings_id)
            ],
            "accounts": [
                a.model_dump(mode="json")
                for a in sorted(self._accounts.values(), key=lambda r: r.account_id)
            ],
            "wallets": [
                w.model_dump(mode="json")
                for w in sorted(self._wallets.values(), key=lambda r: r.wallet_id)
            ],
        }

        temp_path = self._storage_path.with_suffix(f"{self._storage_path.suffix}.tmp")
        temp_path.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
        temp_path.replace(self._storage_path)
