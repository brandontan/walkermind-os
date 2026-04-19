"""Wallet-link storage boundary — abstract base and persistent implementation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Final

import structlog

from projects.polymarket.polyquantbot.server.schemas.wallet_link import WalletLinkRecord, WalletLinkStatus

log = structlog.get_logger(__name__)


class WalletLinkStorageError(RuntimeError):
    """Raised when wallet-link data cannot be read or written."""


class WalletLinkStore:
    def put_link(self, record: WalletLinkRecord) -> None:
        raise NotImplementedError

    def get_link(self, link_id: str) -> WalletLinkRecord | None:
        raise NotImplementedError

    def list_links_for_user(self, tenant_id: str, user_id: str) -> list[WalletLinkRecord]:
        raise NotImplementedError

    def set_link_status(self, link_id: str, status: WalletLinkStatus) -> WalletLinkRecord:
        raise NotImplementedError


class PersistentWalletLinkStore(WalletLinkStore):
    """Local-file JSON wallet-link storage with deterministic overwrite semantics."""

    _FORMAT_VERSION: Final[int] = 1

    def __init__(self, storage_path: Path) -> None:
        self._storage_path = storage_path
        self._records: dict[str, WalletLinkRecord] = {}
        self._load_from_disk()

    def put_link(self, record: WalletLinkRecord) -> None:
        self._records[record.link_id] = record
        self._persist_to_disk()
        log.debug("wallet_link_persisted", link_id=record.link_id, user_id=record.user_id)

    def get_link(self, link_id: str) -> WalletLinkRecord | None:
        return self._records.get(link_id)

    def list_links_for_user(self, tenant_id: str, user_id: str) -> list[WalletLinkRecord]:
        return [
            r for r in self._records.values()
            if r.tenant_id == tenant_id and r.user_id == user_id
        ]

    def set_link_status(self, link_id: str, status: WalletLinkStatus) -> WalletLinkRecord:
        record = self._records.get(link_id)
        if record is None:
            raise WalletLinkStorageError(f"wallet link not found: {link_id}")
        updated = record.model_copy(update={"status": status})
        self._records[link_id] = updated
        self._persist_to_disk()
        return updated

    def _load_from_disk(self) -> None:
        if not self._storage_path.exists():
            return

        try:
            raw_payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise WalletLinkStorageError(
                "persistent wallet link store contains invalid JSON"
            ) from exc

        if not isinstance(raw_payload, dict):
            raise WalletLinkStorageError(
                "persistent wallet link store payload must be an object"
            )

        version = raw_payload.get("version")
        if version != self._FORMAT_VERSION:
            raise WalletLinkStorageError(
                f"unsupported persistent wallet link store version: {version}"
            )

        raw_records = raw_payload.get("records")
        if not isinstance(raw_records, list):
            raise WalletLinkStorageError(
                "persistent wallet link store records field must be a list"
            )

        for item in raw_records:
            record = WalletLinkRecord.model_validate(item)
            self._records[record.link_id] = record

    def _persist_to_disk(self) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self._FORMAT_VERSION,
            "records": [
                record.model_dump(mode="json")
                for record in sorted(self._records.values(), key=lambda r: r.link_id)
            ],
        }

        temp_path = self._storage_path.with_suffix(f"{self._storage_path.suffix}.tmp")
        temp_path.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
        temp_path.replace(self._storage_path)
