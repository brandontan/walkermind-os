"""In-memory wallet-link storage boundary."""
from __future__ import annotations

import structlog

from projects.polymarket.polyquantbot.server.schemas.wallet_link import WalletLinkRecord

log = structlog.get_logger(__name__)


class WalletLinkStore:
    def __init__(self) -> None:
        self._records: dict[str, WalletLinkRecord] = {}

    def put_link(self, record: WalletLinkRecord) -> None:
        self._records[record.link_id] = record
        log.debug("wallet_link_stored", link_id=record.link_id, user_id=record.user_id)

    def get_link(self, link_id: str) -> WalletLinkRecord | None:
        return self._records.get(link_id)

    def list_links_for_user(self, tenant_id: str, user_id: str) -> list[WalletLinkRecord]:
        return [
            r for r in self._records.values()
            if r.tenant_id == tenant_id and r.user_id == user_id
        ]
