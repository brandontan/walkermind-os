"""Multi-strategy router — runs all registered strategies in parallel and aggregates signals.

StrategyRouter coordinates execution of multiple :class:`BaseStrategy` instances,
collecting their signals for a given market and returning the aggregated result.

Aggregation policy:
  - All strategies are evaluated concurrently via ``asyncio.gather()``.
  - Each strategy independently decides whether to emit a signal (or ``None``).
  - When multiple strategies produce signals for the same ``(market_id, side)``
    pair the signal with the highest edge is selected (best-edge wins).
  - Signals for different sides on the same market are both forwarded — the risk
    layer decides which (if any) to execute.

Usage::

    from projects.polymarket.polyquantbot.strategy.router import StrategyRouter
    from projects.polymarket.polyquantbot.strategy.implementations import (
        EVMomentumStrategy,
        MeanReversionStrategy,
        LiquidityEdgeStrategy,
    )

    router = StrategyRouter()
    router.register(EVMomentumStrategy())
    router.register(MeanReversionStrategy())
    router.register(LiquidityEdgeStrategy())

    signals = await router.evaluate(market_id, market_data)
    for sig in signals:
        print(sig.market_id, sig.side, sig.edge)
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Union

import structlog

from .base.base_strategy import BaseStrategy, SignalResult
from .implementations import STRATEGY_REGISTRY

log = structlog.get_logger(__name__)

# Sentinel used internally to distinguish "errored" from "returned None".
_EVALUATE_ERROR = object()


# ── Router result type ────────────────────────────────────────────────────────


@dataclass
class RouterResult:
    """Aggregated output from a single StrategyRouter.evaluate() call.

    Attributes:
        market_id: The market that was evaluated.
        signals: Deduplicated signals — one per winning (market_id, side) pair.
        evaluated: Total number of strategies that ran without error.
        errored: Number of strategies that raised an exception.
        skipped: Number of strategies that returned None (no signal).
        strategy_signals: Raw per-strategy results before deduplication.
    """

    market_id: str
    signals: List[SignalResult]
    evaluated: int
    errored: int
    skipped: int
    strategy_signals: Dict[str, Optional[SignalResult]] = field(default_factory=dict)

    def best_signal(self) -> Optional[SignalResult]:
        """Return the highest-edge signal, or None if no signals produced."""
        if not self.signals:
            return None
        return max(self.signals, key=lambda s: s.edge)


# ── StrategyRouter ────────────────────────────────────────────────────────────


class StrategyRouter:
    """Parallel multi-strategy coordinator.

    Maintains a registry of :class:`BaseStrategy` instances and evaluates all of
    them concurrently for each market tick.  Aggregates results using a
    best-edge-wins deduplication policy.

    Args:
        strategies: Optional initial list of strategy instances to register.
        timeout_s: Per-strategy evaluation timeout in seconds (default 5.0).
            Strategies that exceed this timeout are treated as errored and
            contribute 0 signals.
    """

    def __init__(
        self,
        strategies: Optional[Sequence[BaseStrategy]] = None,
        timeout_s: float = 5.0,
    ) -> None:
        self._strategies: Dict[str, BaseStrategy] = {}
        self._enabled: Dict[str, bool] = {}
        self._timeout_s = timeout_s

        if strategies:
            for s in strategies:
                self.register(s)

    # ── Registration ──────────────────────────────────────────────────────────

    def register(self, strategy: BaseStrategy) -> None:
        """Register a strategy with the router.

        If a strategy with the same name is already registered it is replaced.

        Args:
            strategy: Concrete :class:`BaseStrategy` instance to add.
        """
        name = strategy.name
        self._strategies[name] = strategy
        self._enabled[name] = True
        log.info("router.strategy_registered", strategy=name)

    def unregister(self, name: str) -> bool:
        """Remove a strategy from the router.

        Args:
            name: Strategy name to remove.

        Returns:
            True if the strategy was found and removed, False otherwise.
        """
        if name in self._strategies:
            del self._strategies[name]
            del self._enabled[name]
            log.info("router.strategy_unregistered", strategy=name)
            return True
        return False

    def enable(self, name: str) -> None:
        """Enable a previously disabled strategy.

        Args:
            name: Strategy name.

        Raises:
            KeyError: If the strategy is not registered.
        """
        if name not in self._strategies:
            raise KeyError(f"Strategy '{name}' not registered")
        self._enabled[name] = True

    def disable(self, name: str) -> None:
        """Disable a strategy (it will be skipped during evaluation).

        Args:
            name: Strategy name.

        Raises:
            KeyError: If the strategy is not registered.
        """
        if name not in self._strategies:
            raise KeyError(f"Strategy '{name}' not registered")
        self._enabled[name] = False

    @property
    def strategy_names(self) -> List[str]:
        """Names of all registered strategies (enabled and disabled)."""
        return list(self._strategies.keys())

    @property
    def active_strategy_names(self) -> List[str]:
        """Names of currently enabled strategies."""
        return [n for n, enabled in self._enabled.items() if enabled]

    # ── Evaluation ────────────────────────────────────────────────────────────

    async def evaluate(
        self,
        market_id: str,
        market_data: Dict,
    ) -> RouterResult:
        """Evaluate all enabled strategies concurrently for a single market tick.

        Args:
            market_id: Polymarket condition ID.
            market_data: Current market snapshot (bid, ask, mid, depth_yes, depth_no, …).

        Returns:
            :class:`RouterResult` with aggregated signals and run statistics.
        """
        active = [(name, s) for name, s in self._strategies.items() if self._enabled.get(name)]

        if not active:
            log.warning("router.no_active_strategies", market_id=market_id)
            return RouterResult(
                market_id=market_id,
                signals=[],
                evaluated=0,
                errored=0,
                skipped=0,
            )

        raw_results = await asyncio.gather(
            *[self._safe_evaluate(name, s, market_id, market_data) for name, s in active],
            return_exceptions=False,
        )

        evaluated = 0
        errored = 0
        skipped = 0
        strategy_signals: Dict[str, Optional[SignalResult]] = {}

        for (name, _), result in zip(active, raw_results):
            if result is _EVALUATE_ERROR:
                errored += 1
                strategy_signals[name] = None
            elif result is None:
                skipped += 1
                evaluated += 1
                strategy_signals[name] = None
            else:
                evaluated += 1
                strategy_signals[name] = result

        # Deduplicate: best-edge-wins per (market_id, side)
        best: Dict[str, SignalResult] = {}  # key = side
        for result in strategy_signals.values():
            if result is None or isinstance(result, Exception):
                continue
            key = result.side
            if key not in best or result.edge > best[key].edge:
                best[key] = result

        aggregated_signals = list(best.values())

        log.info(
            "router.evaluate_complete",
            market_id=market_id,
            signals=len(aggregated_signals),
            evaluated=evaluated,
            errored=errored,
            skipped=skipped,
        )

        return RouterResult(
            market_id=market_id,
            signals=aggregated_signals,
            evaluated=evaluated,
            errored=errored,
            skipped=skipped,
            strategy_signals=strategy_signals,
        )

    async def _safe_evaluate(
        self,
        name: str,
        strategy: BaseStrategy,
        market_id: str,
        market_data: Dict,
    ) -> Optional[SignalResult]:
        """Evaluate a single strategy with timeout and error isolation.

        Returns the :class:`SignalResult` or None; never raises.

        Args:
            name: Strategy name (for logging).
            strategy: Strategy instance.
            market_id: Polymarket condition ID.
            market_data: Market snapshot.

        Returns:
            SignalResult | None
        """
        try:
            result = await asyncio.wait_for(
                strategy.evaluate(market_id, market_data),
                timeout=self._timeout_s,
            )
            return result
        except asyncio.TimeoutError:
            log.error(
                "router.strategy_timeout",
                strategy=name,
                market_id=market_id,
                timeout_s=self._timeout_s,
            )
            return _EVALUATE_ERROR
        except Exception as exc:  # noqa: BLE001
            log.error(
                "router.strategy_error",
                strategy=name,
                market_id=market_id,
                error_type=exc.__class__.__name__,
                error=str(exc),
            )
            return _EVALUATE_ERROR

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_registry(cls, timeout_s: float = 5.0) -> "StrategyRouter":
        """Build a StrategyRouter pre-populated with all STRATEGY_REGISTRY strategies.

        Args:
            timeout_s: Per-strategy evaluation timeout.

        Returns:
            Configured :class:`StrategyRouter` with EV Momentum, Mean Reversion,
            and Liquidity Edge strategies registered.
        """
        router = cls(timeout_s=timeout_s)
        for strategy_cls in STRATEGY_REGISTRY.values():
            router.register(strategy_cls())
        return router

    def __repr__(self) -> str:
        return (
            f"<StrategyRouter strategies={self.strategy_names} "
            f"active={self.active_strategy_names}>"
        )
