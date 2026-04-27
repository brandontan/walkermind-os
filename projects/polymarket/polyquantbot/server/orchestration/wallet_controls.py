"""WalletControlsStore — Priority 6 Phase B + Phase C (sections 40–42).

In-memory per-session control state for per-wallet enable/disable toggles
and portfolio-wide global halt.  Phase C adds PostgreSQL persistence via
load() and persist() methods.

Persistence design:
  - wallet_id = '__global__' is the magic key for global halt state.
  - Per-wallet disabled entries use the actual wallet_id with is_disabled=True.
  - load() replaces the current in-memory state with the DB snapshot.
  - persist() deletes all existing rows for (tenant_id, user_id) then re-inserts
    current state. Not atomic but acceptable for an admin-control store where
    in-memory state is always authoritative during a session.

All mutations return WalletControlResult for structured logging by callers.
build_overlay() produces a PortfolioControlOverlay for WalletOrchestrator.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

import structlog

from projects.polymarket.polyquantbot.server.orchestration.schemas import (
    PortfolioControlOverlay,
    WalletCandidate,
    WalletControlResult,
)

if TYPE_CHECKING:
    from projects.polymarket.polyquantbot.infra.db import DatabaseClient

log = structlog.get_logger(__name__)

_GLOBAL_HALT_KEY = "__global__"


class WalletControlsStore:
    """In-memory store for per-wallet enable/disable state and global halt."""

    def __init__(self) -> None:
        self._disabled: set[str] = set()   # wallet_ids explicitly disabled
        self._global_halt: bool = False
        self._halt_reason: str = ""

    # ── Per-wallet toggles ────────────────────────────────────────────────────

    def enable_wallet(self, wallet_id: str) -> WalletControlResult:
        """Re-enable a previously disabled wallet."""
        was_disabled = wallet_id in self._disabled
        self._disabled.discard(wallet_id)
        log.info("wallet_enabled", wallet_id=wallet_id, was_disabled=was_disabled)
        return WalletControlResult(
            wallet_id=wallet_id,
            action="enable",
            success=True,
            reason="wallet enabled" if was_disabled else "wallet was already enabled",
        )

    def disable_wallet(self, wallet_id: str, reason: str = "") -> WalletControlResult:
        """Disable a wallet from routing selection."""
        self._disabled.add(wallet_id)
        log.info("wallet_disabled", wallet_id=wallet_id, reason=reason)
        return WalletControlResult(
            wallet_id=wallet_id,
            action="disable",
            success=True,
            reason=reason or "wallet disabled by operator",
        )

    def get_enabled_wallet_ids(self, wallet_ids: Sequence[str]) -> frozenset[str]:
        """Return the subset of wallet_ids that are currently enabled."""
        return frozenset(wid for wid in wallet_ids if wid not in self._disabled)

    # ── Global halt ───────────────────────────────────────────────────────────

    def set_global_halt(self, reason: str) -> None:
        """Halt all routing for this store instance."""
        self._global_halt = True
        self._halt_reason = reason
        log.warning("global_halt_set", reason=reason)

    def clear_global_halt(self) -> None:
        """Clear the global halt — routing resumes."""
        self._global_halt = False
        self._halt_reason = ""
        log.info("global_halt_cleared")

    # ── Overlay builder ───────────────────────────────────────────────────────

    # ── DB persistence (Phase C) ──────────────────────────────────────────────

    async def load(
        self,
        db: "DatabaseClient",
        tenant_id: str,
        user_id: str,
    ) -> None:
        """Replace in-memory state with the snapshot persisted in DB.

        Rows with wallet_id='__global__' carry the global halt state.
        All other rows with is_disabled=True populate the disabled set.
        Rows with is_disabled=False are ignored — they represent wallets
        that were explicitly re-enabled and previously persisted.
        """
        rows = await db._fetch(
            "SELECT wallet_id, is_disabled, halt_reason "
            "FROM wallet_controls "
            "WHERE tenant_id = $1 AND user_id = $2",
            tenant_id,
            user_id,
            op_label="wallet_controls_load",
        )
        new_disabled: set[str] = set()
        new_halt = False
        new_halt_reason = ""
        for row in rows:
            wid = str(row["wallet_id"])
            if wid == _GLOBAL_HALT_KEY:
                new_halt = bool(row["is_disabled"])
                new_halt_reason = str(row["halt_reason"])
            elif bool(row["is_disabled"]):
                new_disabled.add(wid)
        self._disabled = new_disabled
        self._global_halt = new_halt
        self._halt_reason = new_halt_reason
        log.info(
            "wallet_controls_loaded",
            tenant_id=tenant_id,
            user_id=user_id,
            disabled_count=len(new_disabled),
            global_halt=new_halt,
        )

    async def persist(
        self,
        db: "DatabaseClient",
        tenant_id: str,
        user_id: str,
    ) -> bool:
        """Write current in-memory state to DB atomically (delete-then-insert in one transaction).

        Returns True if the transaction committed successfully, False on any failure.
        """
        if db._pool is None:
            log.warning("wallet_controls_persist_no_pool", tenant_id=tenant_id, user_id=user_id)
            return False

        upsert_sql = """
            INSERT INTO wallet_controls (tenant_id, user_id, wallet_id, is_disabled, halt_reason)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (tenant_id, user_id, wallet_id) DO UPDATE
                SET is_disabled = EXCLUDED.is_disabled,
                    halt_reason = EXCLUDED.halt_reason,
                    updated_at  = NOW()
        """
        try:
            async with db._pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(
                        "DELETE FROM wallet_controls WHERE tenant_id = $1 AND user_id = $2",
                        tenant_id,
                        user_id,
                    )
                    await conn.execute(
                        upsert_sql,
                        tenant_id,
                        user_id,
                        _GLOBAL_HALT_KEY,
                        self._global_halt,
                        self._halt_reason,
                    )
                    for wid in self._disabled:
                        await conn.execute(
                            upsert_sql,
                            tenant_id,
                            user_id,
                            wid,
                            True,
                            "",
                        )
            log.info(
                "wallet_controls_persisted",
                tenant_id=tenant_id,
                user_id=user_id,
                disabled_count=len(self._disabled),
                global_halt=self._global_halt,
            )
            return True
        except Exception as exc:
            log.warning(
                "wallet_controls_persist_failed",
                tenant_id=tenant_id,
                user_id=user_id,
                error=str(exc),
            )
            return False

    # ── Overlay builder ───────────────────────────────────────────────────────

    def build_overlay(
        self,
        tenant_id: str,
        user_id: str,
        candidates: Sequence[WalletCandidate],
    ) -> PortfolioControlOverlay:
        """Build a PortfolioControlOverlay for use by WalletOrchestrator.

        When global_halt is True, enabled_wallet_ids is empty — the
        orchestrator will return outcome="halted" before any policy evaluation.

        Args:
            tenant_id:  Ownership scope to embed in the overlay.
            user_id:    Ownership scope to embed in the overlay.
            candidates: Current wallet candidates; their wallet_ids are used
                        to compute enabled_wallet_ids.

        Returns:
            PortfolioControlOverlay with halt state and enabled wallet set.
        """
        all_ids = [c.wallet_id for c in candidates]

        if self._global_halt:
            enabled: frozenset[str] = frozenset()
        else:
            enabled = self.get_enabled_wallet_ids(all_ids)

        return PortfolioControlOverlay(
            tenant_id=tenant_id,
            user_id=user_id,
            global_halt=self._global_halt,
            halt_reason=self._halt_reason,
            enabled_wallet_ids=enabled,
        )
