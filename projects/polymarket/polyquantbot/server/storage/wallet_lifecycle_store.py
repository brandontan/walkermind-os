"""Wallet lifecycle storage — PostgreSQL-backed via DatabaseClient."""
from __future__ import annotations

import json
from typing import Optional

import structlog

from projects.polymarket.polyquantbot.infra.db import DatabaseClient
from projects.polymarket.polyquantbot.server.schemas.wallet_lifecycle import (
    WalletAuditEntry,
    WalletLifecycleRecord,
    WalletLifecycleStatus,
)

log = structlog.get_logger(__name__)


class WalletLifecycleStore:
    """PostgreSQL-backed store for wallet lifecycle records and audit log."""

    def __init__(self, db: DatabaseClient) -> None:
        self._db = db

    async def upsert_wallet(self, record: WalletLifecycleRecord) -> bool:
        sql = """
            INSERT INTO wallet_lifecycle (
                wallet_id, tenant_id, user_id, address, status,
                previous_status, status_changed_at, changed_by,
                created_at, chain_id, metadata
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            ON CONFLICT (wallet_id) DO UPDATE
                SET status            = EXCLUDED.status,
                    previous_status   = EXCLUDED.previous_status,
                    status_changed_at = EXCLUDED.status_changed_at,
                    changed_by        = EXCLUDED.changed_by,
                    metadata          = EXCLUDED.metadata
        """
        return await self._db._execute(
            sql,
            record.wallet_id,
            record.tenant_id,
            record.user_id,
            record.address,
            record.status.value,
            record.previous_status.value if record.previous_status else None,
            record.status_changed_at,
            record.changed_by,
            record.created_at,
            record.chain_id,
            json.dumps(record.metadata),
            op_label="wallet_lifecycle_upsert",
        )

    async def get_wallet(self, wallet_id: str) -> Optional[WalletLifecycleRecord]:
        sql = "SELECT * FROM wallet_lifecycle WHERE wallet_id = $1"
        rows = await self._db._fetch(sql, wallet_id, op_label="wallet_lifecycle_get")
        if not rows:
            return None
        return self._row_to_record(rows[0])

    async def get_wallet_by_address(
        self, tenant_id: str, address: str
    ) -> Optional[WalletLifecycleRecord]:
        sql = """
            SELECT * FROM wallet_lifecycle
            WHERE tenant_id = $1 AND address = $2
            LIMIT 1
        """
        rows = await self._db._fetch(
            sql, tenant_id, address, op_label="wallet_lifecycle_get_by_address"
        )
        if not rows:
            return None
        return self._row_to_record(rows[0])

    async def list_wallets_for_user(
        self,
        tenant_id: str,
        user_id: str,
        status: Optional[WalletLifecycleStatus] = None,
    ) -> list[WalletLifecycleRecord]:
        if status:
            sql = """
                SELECT * FROM wallet_lifecycle
                WHERE tenant_id = $1 AND user_id = $2 AND status = $3
                ORDER BY created_at ASC
            """
            rows = await self._db._fetch(
                sql, tenant_id, user_id, status.value,
                op_label="wallet_lifecycle_list_status",
            )
        else:
            sql = """
                SELECT * FROM wallet_lifecycle
                WHERE tenant_id = $1 AND user_id = $2
                ORDER BY created_at ASC
            """
            rows = await self._db._fetch(
                sql, tenant_id, user_id, op_label="wallet_lifecycle_list"
            )
        return [self._row_to_record(r) for r in rows]

    async def append_audit(self, entry: WalletAuditEntry) -> bool:
        sql = """
            INSERT INTO wallet_audit_log (
                log_id, wallet_id, from_status, to_status,
                changed_at, changed_by, reason
            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (log_id) DO NOTHING
        """
        return await self._db._execute(
            sql,
            entry.log_id,
            entry.wallet_id,
            entry.from_status.value if entry.from_status else None,
            entry.to_status.value,
            entry.changed_at,
            entry.changed_by,
            entry.reason,
            op_label="wallet_audit_append",
        )

    async def transition_atomic(
        self,
        *,
        wallet_id: str,
        expected_from_status: str,
        new_record: WalletLifecycleRecord,
        audit_entry: WalletAuditEntry,
    ) -> str:
        """Atomic FSM transition: SELECT FOR UPDATE + UPDATE + INSERT audit in one transaction.

        Returns:
            "ok"        — transition applied
            "conflict"  — current status ≠ expected (concurrent transition won)
            "not_found" — wallet_id does not exist
            "error"     — unexpected DB failure
        """
        if self._db._pool is None:
            await self._db.connect()
        if self._db._pool is None:
            log.error("wallet_lifecycle_transition_atomic_no_pool", wallet_id=wallet_id)
            return "error"
        try:
            async with self._db._pool.acquire() as conn:
                async with conn.transaction():
                    row = await conn.fetchrow(
                        "SELECT status FROM wallet_lifecycle WHERE wallet_id = $1 FOR UPDATE",
                        wallet_id,
                    )
                    if row is None:
                        return "not_found"
                    if row["status"] != expected_from_status:
                        log.warning(
                            "wallet_lifecycle_transition_conflict",
                            wallet_id=wallet_id,
                            expected=expected_from_status,
                            actual=row["status"],
                        )
                        return "conflict"
                    await conn.execute(
                        """
                        UPDATE wallet_lifecycle
                        SET status            = $2,
                            previous_status   = $3,
                            status_changed_at = $4,
                            changed_by        = $5,
                            metadata          = $6
                        WHERE wallet_id = $1
                        """,
                        new_record.wallet_id,
                        new_record.status.value,
                        new_record.previous_status.value if new_record.previous_status else None,
                        new_record.status_changed_at,
                        new_record.changed_by,
                        json.dumps(new_record.metadata),
                    )
                    await conn.execute(
                        """
                        INSERT INTO wallet_audit_log (
                            log_id, wallet_id, from_status, to_status,
                            changed_at, changed_by, reason
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                        ON CONFLICT (log_id) DO NOTHING
                        """,
                        audit_entry.log_id,
                        audit_entry.wallet_id,
                        audit_entry.from_status.value if audit_entry.from_status else None,
                        audit_entry.to_status.value,
                        audit_entry.changed_at,
                        audit_entry.changed_by,
                        audit_entry.reason,
                    )
            log.info(
                "wallet_lifecycle_transition_atomic_ok",
                wallet_id=wallet_id,
                to_status=new_record.status.value,
            )
            return "ok"
        except Exception as exc:
            log.error(
                "wallet_lifecycle_transition_atomic_error",
                wallet_id=wallet_id,
                error=str(exc),
            )
            return "error"

    async def list_audit_for_wallet(
        self, wallet_id: str, limit: int = 50
    ) -> list[WalletAuditEntry]:
        sql = """
            SELECT * FROM wallet_audit_log
            WHERE wallet_id = $1
            ORDER BY changed_at ASC LIMIT $2
        """
        rows = await self._db._fetch(
            sql, wallet_id, limit, op_label="wallet_audit_list"
        )
        return [self._row_to_audit(r) for r in rows]

    def _row_to_record(self, row: dict) -> WalletLifecycleRecord:
        meta = row.get("metadata") or "{}"
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        prev = row.get("previous_status")
        return WalletLifecycleRecord(
            wallet_id=row["wallet_id"],
            tenant_id=row["tenant_id"],
            user_id=row["user_id"],
            address=row["address"],
            status=WalletLifecycleStatus(row["status"]),
            previous_status=WalletLifecycleStatus(prev) if prev else None,
            status_changed_at=row["status_changed_at"],
            changed_by=row["changed_by"],
            created_at=row["created_at"],
            chain_id=row.get("chain_id", "polygon"),
            metadata=meta,
        )

    def _row_to_audit(self, row: dict) -> WalletAuditEntry:
        from_s = row.get("from_status")
        return WalletAuditEntry(
            log_id=row["log_id"],
            wallet_id=row["wallet_id"],
            from_status=WalletLifecycleStatus(from_s) if from_s else None,
            to_status=WalletLifecycleStatus(row["to_status"]),
            changed_at=row["changed_at"],
            changed_by=row["changed_by"],
            reason=row.get("reason", ""),
        )
