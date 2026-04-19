"""Wallet-link service — user-owned wallet address record management."""
from __future__ import annotations

import structlog

from projects.polymarket.polyquantbot.server.schemas.auth_session import AuthenticatedScope
from projects.polymarket.polyquantbot.server.schemas.multi_user import new_id, now_utc
from projects.polymarket.polyquantbot.server.schemas.wallet_link import WalletLinkCreateRequest, WalletLinkRecord
from projects.polymarket.polyquantbot.server.storage.wallet_link_store import WalletLinkStore

log = structlog.get_logger(__name__)


class WalletLinkNotFoundError(LookupError):
    """Raised when a wallet link record cannot be found."""


class WalletLinkOwnershipError(PermissionError):
    """Raised when the authenticated user does not own the referenced wallet link."""


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

    def unlink_link(self, scope: AuthenticatedScope, link_id: str) -> WalletLinkRecord:
        record = self._store.get_link(link_id)
        if record is None:
            raise WalletLinkNotFoundError(f"wallet link not found: {link_id}")
        if record.tenant_id != scope.tenant_id or record.user_id != scope.user_id:
            raise WalletLinkOwnershipError(
                "wallet link does not belong to authenticated user"
            )
        updated = self._store.set_link_status(link_id, "unlinked")
        log.info(
            "wallet_link_unlinked",
            link_id=link_id,
            user_id=scope.user_id,
            tenant_id=scope.tenant_id,
        )
        return updated
