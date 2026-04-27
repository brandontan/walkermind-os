"""CrossWalletStateAggregator — Priority 6 Phase B (section 39).

Produces a unified cross-wallet view for a single user from a pre-fetched
list of WalletCandidate objects. Stateless by design — the service layer
fetches candidates from PostgreSQL; the aggregator classifies and aggregates.

Risk thresholds (imported from server.schemas.portfolio — never duplicated):
  MAX_DRAWDOWN          = 0.08  (hard ceiling)
  MAX_TOTAL_EXPOSURE_PCT = 0.10 (conflict threshold)

WalletRiskState classification:
  healthy : drawdown_pct <= MAX_DRAWDOWN * 0.75
  at_risk : drawdown_pct  > MAX_DRAWDOWN * 0.75
  breached: drawdown_pct  > MAX_DRAWDOWN
"""
from __future__ import annotations

from typing import Sequence

import structlog

from projects.polymarket.polyquantbot.server.orchestration.schemas import (
    RISK_STATE_AT_RISK,
    RISK_STATE_BREACHED,
    RISK_STATE_HEALTHY,
    CrossWalletState,
    WalletCandidate,
    WalletHealthStatus,
)
from projects.polymarket.polyquantbot.server.schemas.portfolio import MAX_DRAWDOWN, MAX_TOTAL_EXPOSURE_PCT

log = structlog.get_logger(__name__)

_AT_RISK_THRESHOLD: float = MAX_DRAWDOWN * 0.75   # 0.06
_BREACHED_THRESHOLD: float = MAX_DRAWDOWN          # 0.08
_CONFLICT_EXPOSURE: float = MAX_TOTAL_EXPOSURE_PCT  # 0.10

_ACTIVE_STATUS: str = "active"


def _classify_risk(drawdown_pct: float) -> str:
    if drawdown_pct > _BREACHED_THRESHOLD:
        return RISK_STATE_BREACHED
    if drawdown_pct > _AT_RISK_THRESHOLD:
        return RISK_STATE_AT_RISK
    return RISK_STATE_HEALTHY


class CrossWalletStateAggregator:
    """Stateless aggregator that builds a unified cross-wallet view."""

    async def aggregate(
        self,
        tenant_id: str,
        user_id: str,
        candidates: Sequence[WalletCandidate],
        enabled_wallet_ids: frozenset[str] | None = None,
    ) -> CrossWalletState:
        """Aggregate candidates into a CrossWalletState snapshot.

        Args:
            tenant_id:          Ownership scope (used in result only — not filtered here).
            user_id:            Ownership scope (used in result only — not filtered here).
            candidates:         Pre-fetched wallet candidates (all wallets for this user).
            enabled_wallet_ids: Optional set from WalletControlsStore; when provided,
                                is_enabled on WalletHealthStatus reflects the toggle state.
                                When None, all wallets are considered enabled.

        Returns:
            CrossWalletState with per-wallet health, total exposure, conflict detection.
        """
        log.info(
            "cross_wallet_aggregate_start",
            tenant_id=tenant_id,
            user_id=user_id,
            candidate_count=len(candidates),
        )

        if not candidates:
            return CrossWalletState(
                tenant_id=tenant_id,
                user_id=user_id,
                wallet_count=0,
                active_count=0,
                total_exposure_pct=0.0,
                max_drawdown_pct=0.0,
                wallets=(),
                has_conflict=False,
                conflict_reasons=(),
            )

        active = [c for c in candidates if c.lifecycle_status == _ACTIVE_STATUS]

        # Weighted exposure: sum(exposure_pct * balance_usd) / total_balance_usd
        total_balance = sum(c.balance_usd for c in active)
        if total_balance > 0:
            weighted_exposure = sum(c.exposure_pct * c.balance_usd for c in active)
            total_exposure_pct = weighted_exposure / total_balance
        else:
            total_exposure_pct = 0.0

        max_drawdown_pct = max((c.drawdown_pct for c in candidates), default=0.0)

        # Per-wallet health status
        health_statuses = tuple(
            WalletHealthStatus(
                wallet_id=c.wallet_id,
                lifecycle_status=c.lifecycle_status,
                is_enabled=(
                    c.wallet_id in enabled_wallet_ids
                    if enabled_wallet_ids is not None
                    else True
                ),
                risk_state=_classify_risk(c.drawdown_pct),
                drawdown_pct=c.drawdown_pct,
                exposure_pct=c.exposure_pct,
            )
            for c in candidates
        )

        # Conflict detection
        conflict_reasons: list[str] = []
        if total_exposure_pct >= _CONFLICT_EXPOSURE:
            conflict_reasons.append(
                f"total_exposure_pct={total_exposure_pct:.4f} >= "
                f"MAX_TOTAL_EXPOSURE_PCT={_CONFLICT_EXPOSURE}"
            )

        has_conflict = bool(conflict_reasons)

        log.info(
            "cross_wallet_aggregate_done",
            tenant_id=tenant_id,
            user_id=user_id,
            wallet_count=len(candidates),
            active_count=len(active),
            total_exposure_pct=round(total_exposure_pct, 6),
            max_drawdown_pct=round(max_drawdown_pct, 6),
            has_conflict=has_conflict,
        )

        return CrossWalletState(
            tenant_id=tenant_id,
            user_id=user_id,
            wallet_count=len(candidates),
            active_count=len(active),
            total_exposure_pct=total_exposure_pct,
            max_drawdown_pct=max_drawdown_pct,
            wallets=health_statuses,
            has_conflict=has_conflict,
            conflict_reasons=tuple(conflict_reasons),
        )
