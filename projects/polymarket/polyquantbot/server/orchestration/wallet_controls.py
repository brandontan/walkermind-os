"""WalletControlsStore — Priority 6 Phase B (section 40).

In-memory per-session control state for per-wallet enable/disable toggles
and portfolio-wide global halt. Phase C will add PostgreSQL persistence.

All mutations return WalletControlResult for structured logging by callers.
build_overlay() produces a PortfolioControlOverlay for WalletOrchestrator.
"""
from __future__ import annotations

from typing import Sequence

import structlog

from server.orchestration.schemas import (
    PortfolioControlOverlay,
    WalletCandidate,
    WalletControlResult,
)

log = structlog.get_logger(__name__)


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
