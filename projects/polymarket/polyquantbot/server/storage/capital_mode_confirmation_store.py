"""Capital mode confirmation store — Priority 8-E.

PostgreSQL-backed persistence for the runtime acknowledgment receipt that
complements the CAPITAL_MODE_CONFIRMED env-var gate. The LiveExecutionGuard
requires BOTH the env var AND an unrevoked row in `capital_mode_confirmations`
before admitting live capital execution.

Idempotent inserts (ON CONFLICT DO NOTHING on confirmation_id). Failed writes
return False; failed reads return None / []. Callers must not assume success.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from projects.polymarket.polyquantbot.infra.db import DatabaseClient

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CapitalModeConfirmation:
    """Immutable view of a single capital-mode confirmation row.

    Attributes:
        confirmation_id:         Server-assigned UUID hex.
        operator_id:             Operator who issued the confirmation.
        mode:                    "LIVE" or "PAPER".
        acknowledgment_token:    Two-step confirmation anti-misclick token.
        upstream_gates_snapshot: Dict of all 5 gate booleans at confirm time.
        confirmed_at:            UTC timestamp of the confirmation.
        revoked_at:              UTC timestamp if revoked, else None.
        revoked_by:              Operator who revoked, else None.
        revoke_reason:           Reason supplied at revoke, else None.
    """

    confirmation_id: str
    operator_id: str
    mode: str
    acknowledgment_token: str
    upstream_gates_snapshot: dict[str, Any]
    confirmed_at: datetime
    revoked_at: Optional[datetime]
    revoked_by: Optional[str]
    revoke_reason: Optional[str]

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class CapitalModeConfirmationStore:
    """PostgreSQL-backed store for capital_mode_confirmations rows.

    Args:
        db: DatabaseClient instance (from server runtime state).
    """

    def __init__(self, db: DatabaseClient) -> None:
        self._db = db

    # ── Writes ────────────────────────────────────────────────────────────────

    async def insert(
        self,
        *,
        operator_id: str,
        mode: str,
        acknowledgment_token: str,
        upstream_gates_snapshot: dict[str, Any],
    ) -> Optional[CapitalModeConfirmation]:
        """Insert a new confirmation receipt. Returns the persisted record on success.

        Returns None if the DB write fails — caller must treat as a refusal.
        """
        confirmation_id = uuid.uuid4().hex
        confirmed_at = datetime.now(timezone.utc)
        sql = """
            INSERT INTO capital_mode_confirmations (
                confirmation_id, operator_id, mode, acknowledgment_token,
                upstream_gates_snapshot, confirmed_at
            ) VALUES ($1, $2, $3, $4, $5::jsonb, $6)
            ON CONFLICT (confirmation_id) DO NOTHING
        """
        ok = await self._db._execute(
            sql,
            confirmation_id,
            operator_id,
            mode,
            acknowledgment_token,
            json.dumps(upstream_gates_snapshot),
            confirmed_at,
            op_label="capital_mode_confirm_insert",
        )
        if not ok:
            log.error(
                "capital_mode_confirm_insert_failed",
                operator_id=operator_id,
                mode=mode,
            )
            return None
        return CapitalModeConfirmation(
            confirmation_id=confirmation_id,
            operator_id=operator_id,
            mode=mode,
            acknowledgment_token=acknowledgment_token,
            upstream_gates_snapshot=dict(upstream_gates_snapshot),
            confirmed_at=confirmed_at,
            revoked_at=None,
            revoked_by=None,
            revoke_reason=None,
        )

    async def revoke_latest(
        self,
        *,
        mode: str,
        revoked_by: str,
        reason: str,
    ) -> Optional[CapitalModeConfirmation]:
        """Revoke the newest active confirmation for the given mode.

        Returns the revoked record on success, None if no active row exists or
        the DB write fails.
        """
        active = await self.get_active(mode)
        if active is None:
            return None
        revoked_at = datetime.now(timezone.utc)
        sql = """
            UPDATE capital_mode_confirmations
               SET revoked_at = $1,
                   revoked_by = $2,
                   revoke_reason = $3
             WHERE confirmation_id = $4
               AND revoked_at IS NULL
        """
        ok = await self._db._execute(
            sql,
            revoked_at,
            revoked_by,
            reason,
            active.confirmation_id,
            op_label="capital_mode_confirm_revoke",
        )
        if not ok:
            log.error(
                "capital_mode_confirm_revoke_failed",
                confirmation_id=active.confirmation_id,
                revoked_by=revoked_by,
            )
            return None
        return CapitalModeConfirmation(
            confirmation_id=active.confirmation_id,
            operator_id=active.operator_id,
            mode=active.mode,
            acknowledgment_token=active.acknowledgment_token,
            upstream_gates_snapshot=active.upstream_gates_snapshot,
            confirmed_at=active.confirmed_at,
            revoked_at=revoked_at,
            revoked_by=revoked_by,
            revoke_reason=reason,
        )

    # ── Reads ─────────────────────────────────────────────────────────────────

    async def get_active(self, mode: str) -> Optional[CapitalModeConfirmation]:
        """Return the most-recent unrevoked confirmation for `mode`, or None."""
        sql = """
            SELECT confirmation_id, operator_id, mode, acknowledgment_token,
                   upstream_gates_snapshot, confirmed_at,
                   revoked_at, revoked_by, revoke_reason
              FROM capital_mode_confirmations
             WHERE mode = $1 AND revoked_at IS NULL
             ORDER BY confirmed_at DESC
             LIMIT 1
        """
        rows = await self._db._fetch(sql, mode, op_label="capital_mode_confirm_get_active")
        if not rows:
            return None
        return _row_to_record(rows[0])

    async def list_recent(self, *, limit: int = 20) -> list[CapitalModeConfirmation]:
        """Return the most-recent confirmations (active and revoked) for audit display."""
        sql = """
            SELECT confirmation_id, operator_id, mode, acknowledgment_token,
                   upstream_gates_snapshot, confirmed_at,
                   revoked_at, revoked_by, revoke_reason
              FROM capital_mode_confirmations
             ORDER BY confirmed_at DESC
             LIMIT $1
        """
        rows = await self._db._fetch(sql, limit, op_label="capital_mode_confirm_list_recent")
        return [_row_to_record(row) for row in rows]


# ── Module helpers ────────────────────────────────────────────────────────────


def _row_to_record(row: dict[str, Any]) -> CapitalModeConfirmation:
    snapshot_raw = row.get("upstream_gates_snapshot") or {}
    if isinstance(snapshot_raw, str):
        try:
            snapshot = json.loads(snapshot_raw)
        except json.JSONDecodeError:
            snapshot = {}
    elif isinstance(snapshot_raw, dict):
        snapshot = snapshot_raw
    else:
        snapshot = {}
    return CapitalModeConfirmation(
        confirmation_id=row["confirmation_id"],
        operator_id=row["operator_id"],
        mode=row["mode"],
        acknowledgment_token=row["acknowledgment_token"],
        upstream_gates_snapshot=snapshot,
        confirmed_at=row["confirmed_at"],
        revoked_at=row.get("revoked_at"),
        revoked_by=row.get("revoked_by"),
        revoke_reason=row.get("revoke_reason"),
    )
