"""BaseStrategy ABC for the CrusaderBot strategy plane.

Every concrete strategy module (Copy Trade, Signal Following, Value, Momentum,
Hybrid, ...) must subclass `BaseStrategy` and implement the three abstract
hooks below. Foundation-only — no execution, no risk evaluation here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .types import ExitDecision, MarketFilters, SignalCandidate, UserContext


class BaseStrategy(ABC):
    """Abstract base class every strategy must implement.

    Class attributes (declare on subclass):
        name: stable identifier, must be unique in the registry.
        version: semver-like version string ("MAJOR.MINOR.PATCH").
        risk_profile_compatibility: subset of {"conservative", "balanced",
            "aggressive"} — which user risk profiles may activate this
            strategy.
    """

    name: str = ""
    version: str = ""
    risk_profile_compatibility: list[str] = []

    @abstractmethod
    async def scan(
        self,
        market_filters: MarketFilters,
        user_context: UserContext,
    ) -> list[SignalCandidate]:
        """Emit signal candidates for the user under the given filters.

        Implementations must return an empty list rather than raising when no
        candidate is found. Risk evaluation is NOT this method's responsibility.
        """

    @abstractmethod
    async def evaluate_exit(self, position: dict) -> ExitDecision:
        """Decide whether to exit a strategy-owned position.

        Called by the exit watcher AFTER user force-close, TP, and SL checks
        have run. Must return `ExitDecision(should_exit=False, reason='hold')`
        when no strategy-level exit applies.
        """

    @abstractmethod
    def default_tp_sl(self) -> tuple[float, float]:
        """Strategy-default (take_profit_pct, stop_loss_pct) tuple.

        Used when the user does not override TP/SL via Trade Setting. Both
        values are positive percentages expressed as decimals (e.g. 0.20 for
        20%). The platform interprets SL as a downside threshold.
        """


__all__ = ["BaseStrategy"]
