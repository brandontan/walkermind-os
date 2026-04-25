"""Wallet lifecycle service — FSM transitions with ownership enforcement."""
from __future__ import annotations

from typing import Optional

import structlog

from projects.polymarket.polyquantbot.server.schemas.wallet_lifecycle import (
    WalletAuditEntry,
    WalletLifecycleRecord,
    WalletLifecycleStatus,
    WalletLifecycleTransitionResult,
    is_valid_transition,
    new_log_id,
    new_wallet_id,
    requires_admin,
    utc_now,
)
from projects.polymarket.polyquantbot.server.storage.wallet_lifecycle_store import (
    WalletLifecycleStore,
)

log = structlog.get_logger(__name__)


class WalletLifecycleService:
    """Full wallet lifecycle FSM.

    State machine (section 26):
        unlinked → linked → active → deactivated
        active/linked → blocked  (admin only)
        blocked → linked          (admin only — unblock)
        deactivated → linked      (re-link / recovery)

    Ownership rules (section 28):
        - Every non-admin transition verifies tenant_id + user_id match the wallet record.
        - Admin transitions require is_admin=True and log changed_by as "admin:{user_id}".
        - Cross-user access returns privilege_error — never leaks wallet data to wrong user.
    """

    def __init__(self, store: WalletLifecycleStore) -> None:
        self._store = store

    # ── Section 26: create / link / activate / deactivate ────────────────────

    async def create_wallet(
        self,
        *,
        tenant_id: str,
        user_id: str,
        address: str,
        chain_id: str = "polygon",
        changed_by: str,
    ) -> WalletLifecycleTransitionResult:
        """Register a new wallet in UNLINKED status. Fails on duplicate address."""
        try:
            existing = await self._store.get_wallet_by_address(tenant_id, address)
            if existing:
                return WalletLifecycleTransitionResult(
                    outcome="duplicate_address",
                    wallet=existing,
                    audit_entry=None,
                    reason=f"address already registered for tenant: {address[:10]}...",
                )
            now = utc_now()
            record = WalletLifecycleRecord(
                wallet_id=new_wallet_id(),
                tenant_id=tenant_id,
                user_id=user_id,
                address=address,
                status=WalletLifecycleStatus.UNLINKED,
                previous_status=None,
                status_changed_at=now,
                changed_by=changed_by,
                created_at=now,
                chain_id=chain_id,
            )
            ok = await self._store.upsert_wallet(record)
            if not ok:
                return WalletLifecycleTransitionResult(
                    outcome="error",
                    wallet=None,
                    audit_entry=None,
                    reason="storage write failed",
                )
            audit = WalletAuditEntry(
                log_id=new_log_id(),
                wallet_id=record.wallet_id,
                from_status=None,
                to_status=WalletLifecycleStatus.UNLINKED,
                changed_at=now,
                changed_by=changed_by,
                reason="wallet_created",
            )
            await self._store.append_audit(audit)
            log.info("wallet_created", wallet_id=record.wallet_id, user_id=user_id)
            return WalletLifecycleTransitionResult(
                outcome="ok", wallet=record, audit_entry=audit, reason=""
            )
        except Exception as exc:
            log.error("wallet_create_error", error=str(exc), user_id=user_id)
            return WalletLifecycleTransitionResult(
                outcome="error", wallet=None, audit_entry=None, reason=str(exc)
            )

    async def link_wallet(
        self,
        *,
        wallet_id: str,
        user_id: str,
        tenant_id: str,
        changed_by: str,
    ) -> WalletLifecycleTransitionResult:
        return await self._transition(
            wallet_id=wallet_id,
            requesting_user_id=user_id,
            tenant_id=tenant_id,
            to_status=WalletLifecycleStatus.LINKED,
            changed_by=changed_by,
            reason="user_linked_wallet",
        )

    async def activate_wallet(
        self,
        *,
        wallet_id: str,
        user_id: str,
        tenant_id: str,
        changed_by: str,
    ) -> WalletLifecycleTransitionResult:
        return await self._transition(
            wallet_id=wallet_id,
            requesting_user_id=user_id,
            tenant_id=tenant_id,
            to_status=WalletLifecycleStatus.ACTIVE,
            changed_by=changed_by,
            reason="user_activated_wallet",
        )

    async def deactivate_wallet(
        self,
        *,
        wallet_id: str,
        user_id: str,
        tenant_id: str,
        changed_by: str,
    ) -> WalletLifecycleTransitionResult:
        return await self._transition(
            wallet_id=wallet_id,
            requesting_user_id=user_id,
            tenant_id=tenant_id,
            to_status=WalletLifecycleStatus.DEACTIVATED,
            changed_by=changed_by,
            reason="user_deactivated_wallet",
        )

    # ── Admin-only transitions (section 28) ───────────────────────────────────

    async def block_wallet(
        self,
        *,
        wallet_id: str,
        admin_user_id: str,
        tenant_id: str,
        reason: str = "admin_block",
    ) -> WalletLifecycleTransitionResult:
        return await self._transition(
            wallet_id=wallet_id,
            requesting_user_id=admin_user_id,
            tenant_id=tenant_id,
            to_status=WalletLifecycleStatus.BLOCKED,
            changed_by=f"admin:{admin_user_id}",
            reason=reason,
            is_admin=True,
        )

    async def unblock_wallet(
        self,
        *,
        wallet_id: str,
        admin_user_id: str,
        tenant_id: str,
        reason: str = "admin_unblock",
    ) -> WalletLifecycleTransitionResult:
        return await self._transition(
            wallet_id=wallet_id,
            requesting_user_id=admin_user_id,
            tenant_id=tenant_id,
            to_status=WalletLifecycleStatus.LINKED,
            changed_by=f"admin:{admin_user_id}",
            reason=reason,
            is_admin=True,
        )

    # ── Section 30: recovery ──────────────────────────────────────────────────

    async def recover_wallet(
        self,
        *,
        wallet_id: str,
        user_id: str,
        tenant_id: str,
        changed_by: str,
    ) -> WalletLifecycleTransitionResult:
        """Recover a DEACTIVATED wallet back to LINKED (re-link path)."""
        try:
            wallet = await self._store.get_wallet(wallet_id)
            if not wallet:
                return WalletLifecycleTransitionResult(
                    outcome="not_found", wallet=None, audit_entry=None,
                    reason=f"wallet {wallet_id!r} not found",
                )
            if wallet.status != WalletLifecycleStatus.DEACTIVATED:
                return WalletLifecycleTransitionResult(
                    outcome="stale_recovery", wallet=wallet, audit_entry=None,
                    reason=f"wallet is {wallet.status.value} — not deactivated, no recovery needed",
                )
            return await self._transition(
                wallet_id=wallet_id,
                requesting_user_id=user_id,
                tenant_id=tenant_id,
                to_status=WalletLifecycleStatus.LINKED,
                changed_by=changed_by,
                reason="user_recovered_wallet",
            )
        except Exception as exc:
            log.error("wallet_recover_error", error=str(exc), wallet_id=wallet_id)
            return WalletLifecycleTransitionResult(
                outcome="error", wallet=None, audit_entry=None, reason=str(exc)
            )

    # ── Read operations ───────────────────────────────────────────────────────

    async def get_wallet(self, wallet_id: str) -> Optional[WalletLifecycleRecord]:
        return await self._store.get_wallet(wallet_id)

    async def list_wallets(
        self,
        *,
        tenant_id: str,
        user_id: str,
        status: Optional[WalletLifecycleStatus] = None,
    ) -> list[WalletLifecycleRecord]:
        return await self._store.list_wallets_for_user(tenant_id, user_id, status)

    async def get_audit_trail(
        self, wallet_id: str, limit: int = 50
    ) -> list[WalletAuditEntry]:
        return await self._store.list_audit_for_wallet(wallet_id, limit)

    # ── Internal FSM engine ───────────────────────────────────────────────────

    async def _transition(
        self,
        *,
        wallet_id: str,
        requesting_user_id: str,
        tenant_id: str,
        to_status: WalletLifecycleStatus,
        changed_by: str,
        reason: str,
        is_admin: bool = False,
    ) -> WalletLifecycleTransitionResult:
        try:
            wallet = await self._store.get_wallet(wallet_id)
            if not wallet:
                return WalletLifecycleTransitionResult(
                    outcome="not_found", wallet=None, audit_entry=None,
                    reason=f"wallet {wallet_id!r} not found",
                )

            # Section 28: ownership + privilege guard
            owns = (
                wallet.tenant_id == tenant_id
                and wallet.user_id == requesting_user_id
            )
            if not owns and not is_admin:
                log.warning(
                    "wallet_ownership_denied",
                    wallet_id=wallet_id,
                    requesting_user=requesting_user_id,
                    owner=wallet.user_id,
                )
                return WalletLifecycleTransitionResult(
                    outcome="privilege_error", wallet=None, audit_entry=None,
                    reason="wallet does not belong to requesting user",
                )

            if not is_valid_transition(wallet.status, to_status):
                return WalletLifecycleTransitionResult(
                    outcome="invalid_transition", wallet=wallet, audit_entry=None,
                    reason=f"{wallet.status.value} → {to_status.value} is not an allowed transition",
                )

            if requires_admin(wallet.status, to_status) and not is_admin:
                return WalletLifecycleTransitionResult(
                    outcome="privilege_error", wallet=wallet, audit_entry=None,
                    reason=f"transition {wallet.status.value} → {to_status.value} requires admin",
                )

            now = utc_now()
            updated = WalletLifecycleRecord(
                wallet_id=wallet.wallet_id,
                tenant_id=wallet.tenant_id,
                user_id=wallet.user_id,
                address=wallet.address,
                status=to_status,
                previous_status=wallet.status,
                status_changed_at=now,
                changed_by=changed_by,
                created_at=wallet.created_at,
                chain_id=wallet.chain_id,
                metadata=wallet.metadata,
            )
            ok = await self._store.upsert_wallet(updated)
            if not ok:
                return WalletLifecycleTransitionResult(
                    outcome="error", wallet=None, audit_entry=None,
                    reason="storage write failed",
                )
            audit = WalletAuditEntry(
                log_id=new_log_id(),
                wallet_id=wallet.wallet_id,
                from_status=wallet.status,
                to_status=to_status,
                changed_at=now,
                changed_by=changed_by,
                reason=reason,
            )
            await self._store.append_audit(audit)
            log.info(
                "wallet_transitioned",
                wallet_id=wallet_id,
                from_status=wallet.status.value,
                to_status=to_status.value,
            )
            return WalletLifecycleTransitionResult(
                outcome="ok", wallet=updated, audit_entry=audit, reason=""
            )
        except Exception as exc:
            log.error("wallet_transition_error", error=str(exc), wallet_id=wallet_id)
            return WalletLifecycleTransitionResult(
                outcome="error", wallet=None, audit_entry=None, reason=str(exc)
            )
