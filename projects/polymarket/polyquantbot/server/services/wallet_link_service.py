"""Wallet-link service — user-owned wallet address record management."""
from __future__ import annotations

import structlog

from projects.polymarket.polyquantbot.server.schemas.auth_session import AuthenticatedScope
from projects.polymarket.polyquantbot.server.schemas.multi_user import new_id, now_utc
from projects.polymarket.polyquantbot.server.schemas.wallet_link import WalletLinkCreateRequest, WalletLinkRecord
from projects.polymarket.polyquantbot.server.storage.wallet_link_store import WalletLinkStore

log = structlog.get_logger(__name__)


class WalletLinkService:
    def __init__(self, store: WalletLinkStore) -> None:
        self._store = store

    def create_link(
        self,
        scope: AuthenticatedScope,
        request: WalletLinkCreateRequest,
    ) -> WalletLinkRecord:
        record = WalletLinkRecord(
            link_id=new_id("wlink"),
            tenant_id=scope.tenant_id,
            user_id=scope.user_id,
            wallet_address=request.wallet_address,
            chain_id=request.chain_id,
            link_type=request.link_type,
            linked_at=now_utc(),
            status="active",
        )
        self._store.put_link(record)
        log.info(
            "wallet_link_created",
            link_id=record.link_id,
            user_id=scope.user_id,
            tenant_id=scope.tenant_id,
        )
        return record

    def list_links(self, scope: AuthenticatedScope) -> list[WalletLinkRecord]:
        return self._store.list_links_for_user(
            tenant_id=scope.tenant_id,
            user_id=scope.user_id,
        )
