"""Persistent paper account boundary for paper-only execution state."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Final

from projects.polymarket.polyquantbot.server.core.public_beta_state import PaperAccount, PaperOrder, PaperPosition


class PaperAccountStoreError(RuntimeError):
    """Raised when paper account storage cannot be loaded or saved."""


class PersistentPaperAccountStore:
    _FORMAT_VERSION: Final[int] = 1

    def __init__(self, storage_path: Path) -> None:
        self._storage_path = storage_path

    def load(self) -> tuple[PaperAccount, list[PaperPosition], list[PaperOrder]]:
        if not self._storage_path.exists():
            return PaperAccount(), [], []
        try:
            payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PaperAccountStoreError("paper account store contains invalid JSON") from exc
        if not isinstance(payload, dict):
            raise PaperAccountStoreError("paper account store payload must be a JSON object")
        if payload.get("version") != self._FORMAT_VERSION:
            raise PaperAccountStoreError("unsupported paper account store version")
        account = PaperAccount(**payload.get("account", {}))
        positions = [PaperPosition(**item) for item in payload.get("positions", [])]
        orders = [PaperOrder(**item) for item in payload.get("orders", [])]
        return account, positions, orders

    def save(self, *, account: PaperAccount, positions: list[PaperPosition], orders: list[PaperOrder]) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self._FORMAT_VERSION,
            "account": asdict(account),
            "positions": [asdict(position) for position in positions],
            "orders": [asdict(order) for order in orders],
        }
        temp_path = self._storage_path.with_suffix(f"{self._storage_path.suffix}.tmp")
        temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(self._storage_path)
