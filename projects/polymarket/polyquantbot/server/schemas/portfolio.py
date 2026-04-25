"""Portfolio domain model — Priority 5 Portfolio Management Logic.

Covers sections 31–36 of WORKTODO.md:
  31. Portfolio model (entity, per-user, per-wallet relation)
  32. Exposure aggregation
  33. Allocation logic
  34. PnL logic
  35. Portfolio guardrails
  36. Portfolio surfaces and validation

Constants (LOCKED per AGENTS.md):
    KELLY_FRACTION        = 0.25  (fractional only — a=1.0 FORBIDDEN)
    MAX_POSITION_PCT      = 0.10  (max 10% of equity per position)
    MAX_DRAWDOWN          = 0.08  (8% drawdown circuit-breaker)
    DAILY_LOSS_LIMIT      = -2000.0
    MAX_CONCENTRATION_PCT = 0.20  (max 20% in one market across wallet)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4


# ── Risk constants (LOCKED per AGENTS.md) ────────────────────────────────────
KELLY_FRACTION: float = 0.25
MAX_POSITION_PCT: float = 0.10        # max 10% of equity per single position
MAX_TOTAL_EXPOSURE_PCT: float = 0.10  # max 10% total exposure cap (conservative — this lane)
MIN_POSITION_USD: float = 10.0
MAX_DRAWDOWN: float = 0.08
DAILY_LOSS_LIMIT: float = -2000.0
MAX_CONCENTRATION_PCT: float = 0.20   # max 20% in one market


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _new_snapshot_id() -> str:
    return "pfs_" + uuid4().hex


# ── Core domain models ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PortfolioPosition:
    """A single open position snapshot within a portfolio."""

    market_id: str
    side: str
    size_usd: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    opened_at: float  # epoch seconds


@dataclass(frozen=True)
class PortfolioSummary:
    """Computed portfolio state for a user+wallet at a point in time."""

    tenant_id: str
    user_id: str
    wallet_id: str
    cash_usd: float
    locked_usd: float
    equity_usd: float
    realized_pnl: float
    unrealized_pnl: float
    net_pnl: float
    drawdown: float
    exposure_pct: float
    position_count: int
    positions: tuple[PortfolioPosition, ...]
    computed_at: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True)
class PortfolioSnapshot:
    """Persisted point-in-time portfolio snapshot record."""

    snapshot_id: str
    tenant_id: str
    user_id: str
    wallet_id: str
    realized_pnl: float
    unrealized_pnl: float
    net_pnl: float
    cash_usd: float
    locked_usd: float
    equity_usd: float
    drawdown: float
    exposure_pct: float
    position_count: int
    mode: str
    recorded_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Allocation ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SignalAllocation:
    """Kelly-sized allocation for a single signal."""

    signal_id: str
    market_id: str
    size_usd: float
    kelly_fraction: float
    edge: float
    price: float


@dataclass(frozen=True)
class AllocationPlan:
    """Kelly-based allocation plan across a set of signals."""

    user_id: str
    wallet_id: str
    total_bankroll: float
    allocations: tuple[SignalAllocation, ...]
    total_allocated_usd: float
    kelly_fraction: float
    computed_at: datetime = field(default_factory=_utc_now)


# ── Exposure ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ExposureReport:
    """Aggregated exposure across all open positions for a user."""

    tenant_id: str
    user_id: str
    total_exposure_usd: float
    exposure_pct: float
    per_market: dict[str, float]  # market_id -> USD locked
    market_count: int
    computed_at: datetime = field(default_factory=_utc_now)


# ── Guardrails ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GuardrailCheckResult:
    """Result of portfolio guardrail enforcement check."""

    allowed: bool
    violations: tuple[str, ...]
    drawdown: float
    exposure_pct: float
    max_single_market_pct: float
    kill_switch_active: bool
    checked_at: datetime = field(default_factory=_utc_now)


# ── Result type ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PortfolioOperationResult:
    """Unified result wrapper for portfolio service operations.

    outcome values:
        ok            — operation succeeded
        no_wallet     — wallet_id not found or not active
        no_positions  — no open positions available
        db_error      — database operation failed
        error         — unexpected error
    """

    outcome: str
    summary: Optional[PortfolioSummary]
    reason: str = ""
