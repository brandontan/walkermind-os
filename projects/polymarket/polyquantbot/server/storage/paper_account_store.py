"""Persistent paper-account storage boundary for paper-only runtime state."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from projects.polymarket.polyquantbot.server.core.public_beta_state import PaperAccount


class PaperAccountStorageError(RuntimeError):
    """Raised when paper account state cannot be loaded or persisted."""


class PaperAccountStore:
    def get_account(self) -> PaperAccount:
        raise NotImplementedError

    def put_account(self, account: PaperAccount) -> None:
        raise NotImplementedError


class PersistentPaperAccountStore(PaperAccountStore):
    _FORMAT_VERSION: Final[int] = 1

    def __init__(self, storage_path: Path) -> None:
        self._storage_path = storage_path
        self._account = PaperAccount()
        self._load_from_disk()

    def get_account(self) -> PaperAccount:
        return self._account

    def put_account(self, account: PaperAccount) -> None:
        self._account = account
        self._persist_to_disk()

    def _load_from_disk(self) -> None:
        if not self._storage_path.exists():
            return
        try:
            payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PaperAccountStorageError("paper account store contains invalid JSON") from exc

        if not isinstance(payload, dict):
            raise PaperAccountStorageError("paper account store payload must be an object")
        if payload.get("version") != self._FORMAT_VERSION:
            raise PaperAccountStorageError(
                f"unsupported paper account store version: {payload.get('version')}"
            )
        raw_account = payload.get("account")
        if not isinstance(raw_account, dict):
            raise PaperAccountStorageError("paper account store account field must be an object")
        self._account = PaperAccount(**raw_account)

    def _persist_to_disk(self) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self._FORMAT_VERSION,
            "account": {
                "account_id": self._account.account_id,
                "starting_balance": self._account.starting_balance,
                "cash_balance": self._account.cash_balance,
                "realized_pnl": self._account.realized_pnl,
                "unrealized_pnl": self._account.unrealized_pnl,
                "daily_realized_pnl": self._account.daily_realized_pnl,
                "daily_trade_count": self._account.daily_trade_count,
            },
        }
        temp_path = self._storage_path.with_suffix(f"{self._storage_path.suffix}.tmp")
        temp_path.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
        temp_path.replace(self._storage_path)
