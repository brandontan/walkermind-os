"""Portfolio management service — Priority 5.

Covers sections 31–36 of WORKTODO.md:
  31. Portfolio model
  32. Exposure aggregation (per-market, per-user, per-wallet)
  33. Allocation logic (bankroll, strategy, user/wallet-aware)
  34. PnL logic (realized, unrealized, portfolio-level, history)
  35. Portfolio guardrails (exposure/drawdown/concentration caps, kill switch)
  36. Portfolio surfaces and validation

Constants (LOCKED per AGENTS.md):
    KELLY_FRACTION        = 0.25  (fractional only — a=1.0 FORBIDDEN)
    MAX_POSITION_PCT      = 0.10  (max 10% of equity per position)
    MAX_DRAWDOWN          = 0.08  (8% drawdown circuit-breaker)
    DAILY_LOSS_LIMIT      = -2000.0
    MAX_CONCENTRATION_PCT = 0.20  (max 20% of equity in one market)
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

import structlog

from projects.polymarket.polyquantbot.server.schemas.portfolio import (
    DAILY_LOSS_LIMIT,
    KELLY_FRACTION,
    MAX_CONCENTRATION_PCT,
    MAX_DRAWDOWN,
    MAX_POSITION_PCT,
    MAX_TOTAL_EXPOSURE_PCT,
    MIN_POSITION_USD,
    AllocationPlan,
    ExposureReport,
    GuardrailCheckResult,
    PortfolioOperationResult,
    PortfolioSnapshot,
    PortfolioSummary,
    SignalAllocation,
    _new_snapshot_id,
    _utc_now,
)
from projects.polymarket.polyquantbot.server.storage.portfolio_store import PortfolioStore

log = structlog.get_logger(__name__)


class PortfolioService:
    """Business logic layer for portfolio management.

    Computes portfolio summaries, exposure reports, allocation plans, and
    guardrail checks from live engine state and DB persistence.

    Args:
        store: PortfolioStore connected to PostgreSQL.
        mode:  Trading mode — 'paper' (default) or 'live'.
    """

    def __init__(
        self,
        store: PortfolioStore,
        mode: str = "paper",
    ) -> None:
        self._store = store
        self._mode = mode.upper()
        log.info("portfolio_service_initialized", mode=self._mode)

    # ── Section 34: PnL Logic ─────────────────────────────────────────────────

    async def compute_summary(
        self,
        tenant_id: str,
        user_id: str,
        wallet_id: str,
        *,
        cash_usd: float = 0.0,
        locked_usd: float = 0.0,
        equity_usd: float = 0.0,
        peak_equity: float = 0.0,
    ) -> PortfolioOperationResult:
        """Compute full portfolio summary for a user+wallet.

        Reads realized PnL from trades table and open positions from
        paper_positions table, then assembles a PortfolioSummary.

        Args:
            tenant_id:   Tenant scope.
            user_id:     User ID.
            wallet_id:   Wallet ID (may be '' for paper mode).
            cash_usd:    Current wallet cash (from live engine state).
            locked_usd:  Current locked USD (from live engine state).
            equity_usd:  Current equity (from live engine state).
            peak_equity: Peak equity for drawdown calculation.

        Returns:
            PortfolioOperationResult with outcome 'ok' on success.
        """
        try:
            realized_pnl = await self._store.get_realized_pnl(
                user_id=user_id,
                mode=self._mode,
            )
            positions = await self._store.get_open_positions(user_id=user_id)

            unrealized_pnl = sum(p.unrealized_pnl for p in positions)
            net_pnl = round(realized_pnl + unrealized_pnl, 4)

            effective_equity = max(equity_usd, 1.0)
            exposure_pct = locked_usd / effective_equity if effective_equity > 0 else 0.0

            effective_peak = max(peak_equity, equity_usd, 1.0)
            drawdown = max((effective_peak - equity_usd) / effective_peak, 0.0)

            summary = PortfolioSummary(
                tenant_id=tenant_id,
                user_id=user_id,
                wallet_id=wallet_id,
                cash_usd=round(cash_usd, 4),
                locked_usd=round(locked_usd, 4),
                equity_usd=round(equity_usd, 4),
                realized_pnl=round(realized_pnl, 4),
                unrealized_pnl=round(unrealized_pnl, 4),
                net_pnl=net_pnl,
                drawdown=round(drawdown, 6),
                exposure_pct=round(exposure_pct, 6),
                position_count=len(positions),
                positions=tuple(positions),
            )
            log.info(
                "portfolio_summary_computed",
                user_id=user_id,
                wallet_id=wallet_id,
                equity_usd=equity_usd,
                net_pnl=net_pnl,
                position_count=len(positions),
            )
            return PortfolioOperationResult(outcome="ok", summary=summary)
        except Exception as exc:  # noqa: BLE001
            log.error(
                "portfolio_compute_summary_error",
                user_id=user_id,
                error=str(exc),
            )
            return PortfolioOperationResult(
                outcome="error",
                summary=None,
                reason=str(exc),
            )

    async def get_pnl_history(
        self,
        tenant_id: str,
        user_id: str,
        wallet_id: str = "",
        limit: int = 30,
    ) -> list[PortfolioSnapshot]:
        """Return PnL history as ordered portfolio snapshots (newest first)."""
        return await self._store.list_snapshots(
            tenant_id=tenant_id,
            user_id=user_id,
            wallet_id=wallet_id,
            limit=limit,
        )

    # ── Section 32: Exposure Aggregation ──────────────────────────────────────

    async def aggregate_exposure(
        self,
        tenant_id: str,
        user_id: str,
        equity_usd: float,
    ) -> ExposureReport:
        """Compute total and per-market exposure for a user.

        Args:
            tenant_id:  Tenant scope.
            user_id:    User ID.
            equity_usd: Current equity for exposure-pct calculation.

        Returns:
            ExposureReport with per-market breakdown.
        """
        try:
            per_market = await self._store.get_exposure_per_market(user_id=user_id)
            total_exposure = sum(per_market.values())
            effective_equity = max(equity_usd, 1.0)
            exposure_pct = total_exposure / effective_equity

            report = ExposureReport(
                tenant_id=tenant_id,
                user_id=user_id,
                total_exposure_usd=round(total_exposure, 4),
                exposure_pct=round(exposure_pct, 6),
                per_market={k: round(v, 4) for k, v in per_market.items()},
                market_count=len(per_market),
            )
            log.info(
                "portfolio_exposure_aggregated",
                user_id=user_id,
                total_exposure=total_exposure,
                market_count=len(per_market),
            )
            return report
        except Exception as exc:  # noqa: BLE001
            log.error(
                "portfolio_aggregate_exposure_error",
                user_id=user_id,
                error=str(exc),
            )
            return ExposureReport(
                tenant_id=tenant_id,
                user_id=user_id,
                total_exposure_usd=0.0,
                exposure_pct=0.0,
                per_market={},
                market_count=0,
            )

    # ── Section 33: Allocation Logic ──────────────────────────────────────────

    def compute_allocation(
        self,
        user_id: str,
        wallet_id: str,
        equity_usd: float,
        signals: list[dict[str, Any]],
    ) -> AllocationPlan:
        """Compute fractional Kelly allocation for a set of signals.

        Each signal must contain: signal_id, market_id, edge (float), price (float).

        Constants (LOCKED):
            KELLY_FRACTION   = 0.25  (fractional — never 1.0)
            MAX_POSITION_PCT = 0.10  (10% equity cap per position)
            MIN_POSITION_USD = 10.0  (floor to avoid dust)

        Args:
            user_id:    User ID.
            wallet_id:  Wallet ID.
            equity_usd: Current equity to size against.
            signals:    List of signal dicts.

        Returns:
            AllocationPlan with per-signal USD sizes.
        """
        effective_equity = max(equity_usd, 1.0)
        allocations: list[SignalAllocation] = []
        total_allocated = 0.0

        for sig in signals:
            try:
                signal_id = str(sig.get("signal_id", ""))
                market_id = str(sig.get("market_id", ""))
                edge = float(sig.get("edge", 0.0))
                price = max(float(sig.get("price", 0.01)), 0.01)

                if edge <= 0:
                    continue

                kelly_f = edge / price
                size_usd = round(effective_equity * KELLY_FRACTION * kelly_f, 2)
                size_usd = min(size_usd, round(effective_equity * MAX_POSITION_PCT, 2))

                if size_usd < MIN_POSITION_USD:
                    continue

                allocations.append(
                    SignalAllocation(
                        signal_id=signal_id,
                        market_id=market_id,
                        size_usd=size_usd,
                        kelly_fraction=KELLY_FRACTION,
                        edge=edge,
                        price=price,
                    )
                )
                total_allocated += size_usd
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "portfolio_allocation_signal_skip",
                    signal=sig,
                    error=str(exc),
                )

        plan = AllocationPlan(
            user_id=user_id,
            wallet_id=wallet_id,
            total_bankroll=round(effective_equity, 4),
            allocations=tuple(allocations),
            total_allocated_usd=round(total_allocated, 4),
            kelly_fraction=KELLY_FRACTION,
        )
        log.info(
            "portfolio_allocation_computed",
            user_id=user_id,
            signal_count=len(allocations),
            total_allocated_usd=total_allocated,
        )
        return plan

    # ── Section 35: Portfolio Guardrails ──────────────────────────────────────

    def check_guardrails(
        self,
        *,
        drawdown: float,
        exposure_pct: float,
        per_market_exposure: dict[str, float],
        equity_usd: float,
        kill_switch_active: bool,
    ) -> GuardrailCheckResult:
        """Enforce all portfolio guardrails.

        Checks (in order):
          1. Kill switch
          2. Drawdown cap (> 8%)
          3. Total exposure cap (> 10% of equity)
          4. Concentration cap (any single market > 20% of equity)

        Args:
            drawdown:              Current peak-to-valley drawdown ratio.
            exposure_pct:          Current total exposure as pct of equity.
            per_market_exposure:   market_id -> USD locked.
            equity_usd:            Current equity (for concentration check).
            kill_switch_active:    Whether the kill switch is engaged.

        Returns:
            GuardrailCheckResult — allowed=True only if all pass.
        """
        violations: list[str] = []
        effective_equity = max(equity_usd, 1.0)

        if kill_switch_active:
            violations.append("kill_switch_enabled")

        if drawdown > MAX_DRAWDOWN:
            violations.append(
                f"drawdown_exceeded:{round(drawdown, 4)}_max:{MAX_DRAWDOWN}"
            )

        if exposure_pct > MAX_TOTAL_EXPOSURE_PCT:
            violations.append(
                f"exposure_cap_exceeded:{round(exposure_pct, 4)}_max:{MAX_TOTAL_EXPOSURE_PCT}"
            )

        max_single_market_pct = 0.0
        for market_id, locked_usd in per_market_exposure.items():
            pct = locked_usd / effective_equity
            if pct > max_single_market_pct:
                max_single_market_pct = pct
            if pct > MAX_CONCENTRATION_PCT:
                violations.append(
                    f"concentration_exceeded:{market_id}:{round(pct, 4)}_max:{MAX_CONCENTRATION_PCT}"
                )

        result = GuardrailCheckResult(
            allowed=len(violations) == 0,
            violations=tuple(violations),
            drawdown=round(drawdown, 6),
            exposure_pct=round(exposure_pct, 6),
            max_single_market_pct=round(max_single_market_pct, 6),
            kill_switch_active=kill_switch_active,
        )
        if not result.allowed:
            log.warning(
                "portfolio_guardrails_blocked",
                violations=list(violations),
                drawdown=drawdown,
                exposure_pct=exposure_pct,
            )
        return result

    # ── Section 36: Portfolio Surfaces — Snapshot persistence ─────────────────

    async def record_snapshot(
        self,
        summary: PortfolioSummary,
        wallet_id: str = "",
    ) -> bool:
        """Persist a portfolio snapshot from a computed PortfolioSummary.

        Args:
            summary:   Computed PortfolioSummary.
            wallet_id: Wallet ID to tag the snapshot with.

        Returns:
            True on success, False on DB error.
        """
        snapshot = PortfolioSnapshot(
            snapshot_id=_new_snapshot_id(),
            tenant_id=summary.tenant_id,
            user_id=summary.user_id,
            wallet_id=wallet_id or summary.wallet_id,
            realized_pnl=summary.realized_pnl,
            unrealized_pnl=summary.unrealized_pnl,
            net_pnl=summary.net_pnl,
            cash_usd=summary.cash_usd,
            locked_usd=summary.locked_usd,
            equity_usd=summary.equity_usd,
            drawdown=summary.drawdown,
            exposure_pct=summary.exposure_pct,
            position_count=summary.position_count,
            mode=self._mode,
            recorded_at=_utc_now(),
            metadata={},
        )
        return await self._store.insert_snapshot(snapshot)

    async def get_latest_snapshot(
        self,
        tenant_id: str,
        user_id: str,
        wallet_id: str = "",
    ) -> Optional[PortfolioSnapshot]:
        """Return the most recent snapshot for this user+wallet."""
        return await self._store.get_latest_snapshot(
            tenant_id=tenant_id,
            user_id=user_id,
            wallet_id=wallet_id,
        )
