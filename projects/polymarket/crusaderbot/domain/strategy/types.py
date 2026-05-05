"""Shared dataclasses for the CrusaderBot strategy plane.

Foundation-only types consumed by `BaseStrategy` implementations and the
`StrategyRegistry`. No execution, no risk evaluation, no signal generation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

VALID_SIDES: tuple[str, ...] = ("YES", "NO")
VALID_RISK_PROFILES: tuple[str, ...] = ("conservative", "balanced", "aggressive")
VALID_EXIT_REASONS: tuple[str, ...] = ("strategy_exit", "hold")


@dataclass(frozen=True)
class SignalCandidate:
    """A strategy-emitted candidate for downstream risk evaluation."""

    market_id: str
    condition_id: str
    side: str
    confidence: float
    suggested_size_usdc: float
    strategy_name: str
    signal_ts: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.side not in VALID_SIDES:
            raise ValueError(
                f"SignalCandidate.side must be one of {VALID_SIDES}, got {self.side!r}"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"SignalCandidate.confidence must be in [0.0, 1.0], got {self.confidence}"
            )
        if self.suggested_size_usdc < 0.0:
            raise ValueError(
                "SignalCandidate.suggested_size_usdc must be >= 0, "
                f"got {self.suggested_size_usdc}"
            )
        if not self.market_id:
            raise ValueError("SignalCandidate.market_id must be non-empty")
        if not self.condition_id:
            raise ValueError("SignalCandidate.condition_id must be non-empty")
        if not self.strategy_name:
            raise ValueError("SignalCandidate.strategy_name must be non-empty")


@dataclass(frozen=True)
class ExitDecision:
    """Result of a per-position strategy exit evaluation."""

    should_exit: bool
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.reason not in VALID_EXIT_REASONS:
            raise ValueError(
                f"ExitDecision.reason must be one of {VALID_EXIT_REASONS}, "
                f"got {self.reason!r}"
            )
        if self.should_exit and self.reason != "strategy_exit":
            raise ValueError(
                "ExitDecision.should_exit=True requires reason='strategy_exit'"
            )
        if not self.should_exit and self.reason != "hold":
            raise ValueError(
                "ExitDecision.should_exit=False requires reason='hold'"
            )


@dataclass(frozen=True)
class MarketFilters:
    """User-level filters narrowing the universe a strategy may act on."""

    categories: list[str]
    min_liquidity: float
    max_time_to_resolution_days: int
    blacklisted_market_ids: list[str]

    def __post_init__(self) -> None:
        if self.min_liquidity < 0.0:
            raise ValueError(
                f"MarketFilters.min_liquidity must be >= 0, got {self.min_liquidity}"
            )
        if self.max_time_to_resolution_days < 0:
            raise ValueError(
                "MarketFilters.max_time_to_resolution_days must be >= 0, "
                f"got {self.max_time_to_resolution_days}"
            )


@dataclass(frozen=True)
class UserContext:
    """Per-user context handed to a strategy at scan time."""

    user_id: str
    sub_account_id: str
    risk_profile: str
    capital_allocation_pct: float
    available_balance_usdc: float

    def __post_init__(self) -> None:
        if self.risk_profile not in VALID_RISK_PROFILES:
            raise ValueError(
                f"UserContext.risk_profile must be one of {VALID_RISK_PROFILES}, "
                f"got {self.risk_profile!r}"
            )
        if not 0.0 <= self.capital_allocation_pct <= 1.0:
            raise ValueError(
                "UserContext.capital_allocation_pct must be in [0.0, 1.0], "
                f"got {self.capital_allocation_pct}"
            )
        if self.available_balance_usdc < 0.0:
            raise ValueError(
                "UserContext.available_balance_usdc must be >= 0, "
                f"got {self.available_balance_usdc}"
            )
        if not self.user_id:
            raise ValueError("UserContext.user_id must be non-empty")
        if not self.sub_account_id:
            raise ValueError("UserContext.sub_account_id must be non-empty")


__all__ = [
    "SignalCandidate",
    "ExitDecision",
    "MarketFilters",
    "UserContext",
    "VALID_SIDES",
    "VALID_RISK_PROFILES",
    "VALID_EXIT_REASONS",
]
