"""MultiStrategyOrchestrator — ties Router → ConflictResolver → Allocator together.

CRITICAL: Execution mode is PAPER ONLY.  This orchestrator FORCES paper execution.
No real orders are placed at this layer.

Pipeline::

    router.evaluate(market_id, market_data)
        │
        ▼
    [tag each signal with strategy_id in metadata]
        │
        ▼
    conflict_resolver.resolve(signals)
        │  → None  ─→ OrchestratorResult(skipped=True, conflict_detected=True)
        │
        ▼
    [for each resolved signal] allocator.allocate(...)
        │
        ▼
    metrics updates
        │
        ▼
    OrchestratorResult(skipped=False, allocations=[...])

Usage::

    orchestrator = MultiStrategyOrchestrator.from_registry()
    result = await orchestrator.run("0xabc...", market_data)
    if result.skipped:
        # conflict — skip this tick
        ...
    for alloc in result.allocations:
        print(alloc.strategy_name, alloc.adjusted_size_usd)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import structlog

from .allocator import AllocationDecision, StrategyAllocator
from .base.base_strategy import SignalResult
from .capital_allocator import DynamicCapitalAllocator
from .conflict_resolver import ConflictResolver
from .router import RouterResult, StrategyRouter
from .implementations import STRATEGY_REGISTRY
from ..monitoring.multi_strategy_metrics import MultiStrategyMetrics

log = structlog.get_logger(__name__)


# ── Result type ───────────────────────────────────────────────────────────────


@dataclass
class OrchestratorResult:
    """Output from a single :meth:`MultiStrategyOrchestrator.run` call.

    Attributes:
        market_id: The market that was evaluated.
        signals: Resolved signals after conflict check (empty when skipped).
        allocations: Capital allocation decisions per resolved signal.
        conflict_detected: True if a YES/NO conflict was found.
        skipped: True if execution was skipped due to conflict.
        router_result: Raw :class:`RouterResult` before conflict resolution.
    """

    market_id: str
    signals: List[SignalResult]
    allocations: List[AllocationDecision]
    conflict_detected: bool
    skipped: bool
    router_result: RouterResult


# ── MultiStrategyOrchestrator ─────────────────────────────────────────────────


class MultiStrategyOrchestrator:
    """Ties StrategyRouter → ConflictResolver → StrategyAllocator together.

    All evaluation happens in PAPER mode — no real orders leave this class.
    The ``force_paper`` flag is intentionally hard-coded to ``True`` and cannot
    be overridden by the caller.

    Args:
        router: Configured :class:`StrategyRouter`.
        resolver: :class:`ConflictResolver` instance.
        allocator: :class:`StrategyAllocator` instance.
        metrics: :class:`MultiStrategyMetrics` tracker.
        force_paper: Must always be True.  Included for clarity; passing False
            will raise a :class:`ValueError`.
    """

    def __init__(
        self,
        router: StrategyRouter,
        resolver: ConflictResolver,
        allocator: "StrategyAllocator | DynamicCapitalAllocator",
        metrics: MultiStrategyMetrics,
        force_paper: bool = True,
    ) -> None:
        if not force_paper:
            raise ValueError(
                "MultiStrategyOrchestrator.force_paper MUST be True — "
                "this component does not support real execution."
            )
        self._router = router
        self._resolver = resolver
        self._allocator = allocator
        self._metrics = metrics
        self._force_paper = True  # always True regardless of argument

        log.info(
            "multi_strategy_orchestrator_initialized",
            strategies=router.strategy_names,
            force_paper=self._force_paper,
        )

    # ── Core evaluation ───────────────────────────────────────────────────────

    async def run(
        self,
        market_id: str,
        market_data: Dict,
    ) -> OrchestratorResult:
        """Run the full multi-strategy evaluation pipeline for one market tick.

        Flow:
        1. Evaluate all strategies via :meth:`StrategyRouter.evaluate`.
        2. Tag each signal with ``strategy_id`` in ``metadata``.
        3. Pass tagged signals through :meth:`ConflictResolver.resolve`.
        4. If conflict → return :class:`OrchestratorResult` with ``skipped=True``.
        5. Allocate capital for each non-conflicting signal.
        6. Update :class:`MultiStrategyMetrics`.
        7. Return :class:`OrchestratorResult` with allocations.

        Args:
            market_id: Polymarket condition ID.
            market_data: Current market snapshot dict.

        Returns:
            :class:`OrchestratorResult` describing what happened this tick.
        """
        log.debug(
            "orchestrator.run_start",
            market_id=market_id,
            strategies=self._router.active_strategy_names,
        )

        # ── Step 1: Evaluate all strategies ──────────────────────────────────
        router_result: RouterResult = await self._router.evaluate(market_id, market_data)

        # ── Step 2: Tag each signal with its originating strategy_id ─────────
        tagged_signals: List[SignalResult] = []
        for strategy_name, signal in router_result.strategy_signals.items():
            if signal is not None:
                signal.metadata["strategy_id"] = strategy_name
                tagged_signals.append(signal)
                # Record in metrics
                self._metrics.record_signal(strategy_name)

        # ── Step 3: Conflict resolution ───────────────────────────────────────
        resolved = self._resolver.resolve(tagged_signals)

        if resolved is None:
            # Conflict detected — skip this tick entirely
            self._metrics.record_conflict()
            log.info(
                "orchestrator.conflict_skip",
                market_id=market_id,
                tagged_signals=len(tagged_signals),
            )
            return OrchestratorResult(
                market_id=market_id,
                signals=[],
                allocations=[],
                conflict_detected=True,
                skipped=True,
                router_result=router_result,
            )

        # ── Step 4: Allocate capital per resolved signal ──────────────────────
        allocations: List[AllocationDecision] = []
        for signal in resolved:
            strategy_name = signal.metadata.get("strategy_id", "unknown")
            decision = self._allocator.allocate(
                strategy_name=strategy_name,
                raw_size_usd=signal.size_usdc,
            )
            allocations.append(decision)

        log.info(
            "orchestrator.run_complete",
            market_id=market_id,
            resolved_signals=len(resolved),
            allocations=len(allocations),
        )

        return OrchestratorResult(
            market_id=market_id,
            signals=resolved,
            allocations=allocations,
            conflict_detected=False,
            skipped=False,
            router_result=router_result,
        )

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_registry(
        cls,
        bankroll: float = 10_000.0,
    ) -> "MultiStrategyOrchestrator":
        """Build a :class:`MultiStrategyOrchestrator` from :data:`STRATEGY_REGISTRY`.

        Creates all standard components (router, resolver, allocator, metrics)
        pre-populated with the three registered strategies (ev_momentum,
        mean_reversion, liquidity_edge).

        Args:
            bankroll: Initial bankroll in USD for the allocator.

        Returns:
            Fully configured :class:`MultiStrategyOrchestrator` in PAPER mode.
        """
        strategy_names = list(STRATEGY_REGISTRY.keys())

        router = StrategyRouter.from_registry()
        resolver = ConflictResolver()
        allocator = DynamicCapitalAllocator(
            strategy_names=strategy_names,
            bankroll=bankroll,
        )
        metrics = MultiStrategyMetrics(strategy_names=strategy_names)

        return cls(
            router=router,
            resolver=resolver,
            allocator=allocator,
            metrics=metrics,
            force_paper=True,
        )

    def __repr__(self) -> str:
        return (
            f"<MultiStrategyOrchestrator strategies={self._router.strategy_names} "
            f"paper=True>"
        )
