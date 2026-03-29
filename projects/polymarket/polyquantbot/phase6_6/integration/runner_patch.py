"""Phase 6.6 runner integration patch.

Wires all Phase 6.6 patches into the existing Phase 6 event-driven runner.
This module provides:

  1. MarketCache — per-market price/return/volatility store fed by MARKET_DATA events.
  2. Phase66Integrator — orchestrates all patches in a non-blocking async pipeline:
       MarketCache → CorrelationMatrix → ExitEnginePatch
                  → VolatilityFilter → SizingPatch
                  → ExecutionEnginePatch → MarketMakerPatch

Usage in Phase 6 runner.py::

    # At startup (in main()):
    from phase6_6.integration.runner_patch import Phase66Integrator
    integrator = Phase66Integrator.from_config(cfg, mm_cancel_cb=mm.cancel_all_orders)

    # In market-data loop, before publishing to EventBus:
    await integrator.on_market_tick(market_id, price, latency_ms, correlation_id)

    # When sizing a position (in pipeline_handlers.handle_position_sized):
    adjusted_size = await integrator.apply_sizing(
        signal=signal,
        raw_size=alloc.size,
        open_positions=open_positions,
        correlation_id=correlation_id,
    )
    if adjusted_size <= 0:
        return  # rejected

    # Before execution (fill_prob):
    decision = integrator.exec_patch.decide_v2(
        signal_ev=signal.ev, ..., latency_ms=integrator.get_latency_ms(market_id),
        volatility=integrator.get_volatility(market_id), ...
    )

    # When opening a position (in handle_order_filled):
    levels = integrator.compute_exit_levels(
        market_id=market_id,
        entry_price=order_result.filled_price,
        correlation_id=correlation_id,
    )
    # store levels.tp_price, levels.sl_price on the trade

    # In exit_monitor_loop, replace static tp_pct/sl_pct with:
    levels = integrator.compute_exit_levels(market_id, pos.entry_price, cid)
    reason = exit_engine.should_exit(current_price, levels, elapsed_min, timeout)

    # After MM fill (in handle_order_filled):
    integrator.mm_patch.record_fill(market_id, filled_size, outcome, correlation_id)
    await integrator.check_mm_inventory(market_id, max_position, correlation_id)

Backward compatibility:
    - Phase 6 EventBus, StateManager, StrategyManager, CapitalAllocator,
      CorrelationEngine, MarketMaker are all UNCHANGED.
    - Phase66Integrator wraps them with additive behaviour only.
    - All Phase 6 event types, payload schemas, and handler signatures preserved.
    - No shared mutable state between Phase 6 and Phase 6.6 components.
"""
from __future__ import annotations

import math
import statistics
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import structlog

from ..engine.correlation_matrix import CorrelationMatrix
from ..engine.execution_engine_patch import ExecutionEnginePatch, ExecutionDecisionV2
from ..engine.exit_engine_patch import ExitEnginePatch, ExitLevels
from ..engine.market_maker_patch import MarketMakerPatch, InventoryCheckResult
from ..engine.sizing_patch import SizingPatch, SizingResult
from ..engine.volatility_filter import VolatilityFilter, VolatilityFilterResult

log = structlog.get_logger()

_PRICE_FLOOR: float = 1e-9
_DEFAULT_LATENCY_MS: float = 50.0    # assumed baseline when no measurement available


# ── MarketCache ───────────────────────────────────────────────────────────────

@dataclass
class MarketSnapshot:
    """Per-market rolling data for Phase 6.6 patch computations."""

    market_id: str
    prices: deque = field(default_factory=lambda: deque(maxlen=52))
    returns: list = field(default_factory=list)    # computed lazily
    last_latency_ms: float = _DEFAULT_LATENCY_MS
    last_updated: float = field(default_factory=time.time)

    def update(self, price: float, latency_ms: Optional[float] = None) -> None:
        """Append a new price observation and recompute returns."""
        safe = max(price, _PRICE_FLOOR)
        self.prices.append(safe)
        if latency_ms is not None:
            self.last_latency_ms = max(latency_ms, 0.0)
        self.last_updated = time.time()
        # Recompute log-returns from stored prices
        pl = list(self.prices)
        if len(pl) >= 2:
            self.returns = [
                math.log(pl[i] / max(pl[i - 1], _PRICE_FLOOR))
                for i in range(1, len(pl))
            ]
        else:
            self.returns = []

    def volatility(self, lookback: int = 20, default_vol: float = 0.02) -> float:
        """Compute realised volatility from last `lookback` log-returns.

        Returns default_vol if fewer than 2 returns are available.
        """
        window = self.returns[-lookback:] if len(self.returns) >= lookback else self.returns
        if len(window) < 2:
            return default_vol
        try:
            vol = statistics.stdev(window)
        except statistics.StatisticsError:
            return default_vol
        return vol if math.isfinite(vol) and vol >= 0 else default_vol

    def prev_price(self) -> Optional[float]:
        """Return the second-to-last price, or None if not enough history."""
        pl = list(self.prices)
        return pl[-2] if len(pl) >= 2 else None

    def latest_price(self) -> Optional[float]:
        """Return the most recent price, or None if empty."""
        return self.prices[-1] if self.prices else None


class MarketCache:
    """In-memory cache of per-market price/return/volatility data.

    Fed by on_tick() calls from the runner's market-data loop.
    Provides data to CorrelationMatrix, ExitEnginePatch, SizingPatch,
    ExecutionEnginePatch, and VolatilityFilter.

    Thread-safety: single-threaded asyncio only.
    """

    def __init__(self, default_vol: float = 0.02, vol_lookback: int = 20) -> None:
        """Initialise the cache.

        Args:
            default_vol: Fallback volatility when history is insufficient.
            vol_lookback: Number of returns used for stdev computation.
        """
        self._default_vol = default_vol
        self._lookback = vol_lookback
        self._markets: dict[str, MarketSnapshot] = {}

    def on_tick(
        self,
        market_id: str,
        price: float,
        latency_ms: Optional[float] = None,
    ) -> None:
        """Record a new price observation for a market.

        Args:
            market_id: Market identifier.
            price: Current mid-price.
            latency_ms: Round-trip latency for this data point (ms).
        """
        if market_id not in self._markets:
            self._markets[market_id] = MarketSnapshot(market_id=market_id)
        self._markets[market_id].update(price, latency_ms)

    def get_returns(self, market_id: str) -> list[float]:
        """Return log-returns for a market (newest last). Empty if unknown."""
        snap = self._markets.get(market_id)
        return list(snap.returns) if snap else []

    def get_volatility(self, market_id: str) -> float:
        """Return realised volatility for a market. Returns default_vol if unknown."""
        snap = self._markets.get(market_id)
        if snap is None:
            return self._default_vol
        return snap.volatility(self._lookback, self._default_vol)

    def get_latency_ms(self, market_id: str) -> float:
        """Return last observed round-trip latency for a market (ms)."""
        snap = self._markets.get(market_id)
        return snap.last_latency_ms if snap else _DEFAULT_LATENCY_MS

    def get_prev_price(self, market_id: str) -> Optional[float]:
        """Return the second-to-last price for momentum computation."""
        snap = self._markets.get(market_id)
        return snap.prev_price() if snap else None

    def get_latest_price(self, market_id: str) -> Optional[float]:
        """Return the most recent recorded price."""
        snap = self._markets.get(market_id)
        return snap.latest_price() if snap else None

    def market_ids(self) -> list[str]:
        """Return all tracked market IDs."""
        return list(self._markets.keys())


# ── Phase66Integrator ─────────────────────────────────────────────────────────

class Phase66Integrator:
    """Orchestrates all Phase 6.6 hardening patches.

    Single point of integration: construct once at startup, then call
    the appropriate method at each pipeline stage.

    All methods are non-blocking and async-safe.  No sleep() calls.
    External I/O is wrapped in asyncio.wait_for() where applicable.
    """

    def __init__(
        self,
        correlation_matrix: CorrelationMatrix,
        exec_patch: ExecutionEnginePatch,
        exit_engine: ExitEnginePatch,
        sizing_patch: SizingPatch,
        vol_filter: VolatilityFilter,
        mm_patch: MarketMakerPatch,
        market_cache: MarketCache,
        recompute_interval: int = 10,
    ) -> None:
        """Initialise the integrator with all patch instances.

        Args:
            correlation_matrix: Stabilized correlation estimator.
            exec_patch: Phase 6.6 fill-prob model.
            exit_engine: Adaptive TP/SL engine.
            sizing_patch: Soft correlation sizing.
            vol_filter: Volatility regime filter.
            mm_patch: MM inventory hard stop.
            market_cache: Per-market price/return/vol cache.
            recompute_interval: Recompute correlation matrix every N ticks.
        """
        self.correlation_matrix = correlation_matrix
        self.exec_patch = exec_patch
        self.exit_engine = exit_engine
        self.sizing_patch = sizing_patch
        self.vol_filter = vol_filter
        self.mm_patch = mm_patch
        self.market_cache = market_cache
        self._recompute_interval = recompute_interval
        self._tick_count: int = 0

    # ── Market data ingestion ─────────────────────────────────────────────────

    async def on_market_tick(
        self,
        market_id: str,
        price: float,
        latency_ms: float,
        correlation_id: str,
    ) -> dict[tuple[str, str], float]:
        """Process a new market data tick.

        Updates the MarketCache and CorrelationMatrix (every N ticks).
        Returns the current correlation matrix (may be unchanged if not
        a recompute cycle).

        This is non-blocking: CorrelationMatrix.recompute() is synchronous
        but O(markets^2) — for typical market counts (< 50) this is < 1ms.

        Args:
            market_id: Market that generated this tick.
            price: Current mid-price.
            latency_ms: Data pipeline round-trip latency.
            correlation_id: Request ID for log correlation.

        Returns:
            Current EMA-smoothed correlation matrix dict.
        """
        self.market_cache.on_tick(market_id, price, latency_ms)
        self.correlation_matrix.update_price(market_id, price)
        self._tick_count += 1

        if self._tick_count % self._recompute_interval == 0:
            matrix = self.correlation_matrix.recompute(correlation_id)
            return matrix

        return self.correlation_matrix.get_matrix()

    # ── Sizing pipeline ───────────────────────────────────────────────────────

    async def apply_sizing(
        self,
        signal_market_id: str,
        signal_strategy: str,
        raw_size: float,
        open_position_market_ids: list[str],
        correlation_id: str,
    ) -> float:
        """Apply full Phase 6.6 sizing pipeline: vol filter → correlation sizing.

        Steps:
          1. Compute volatility for the signal's market.
          2. VolatilityFilter: halve size in high-vol regime.
          3. SizingPatch: reduce size proportional to portfolio correlation.

        Args:
            signal_market_id: Market ID of the incoming signal.
            signal_strategy: Strategy name for log context.
            raw_size: Size from Phase 6 CapitalAllocator (USD).
            open_position_market_ids: List of currently open position market IDs.
            correlation_id: Request ID.

        Returns:
            Final adjusted size in USD.  Returns 0.0 if any gate rejects.
        """
        # ── Step 1: Volatility filter ─────────────────────────────────────────
        vol = self.market_cache.get_volatility(signal_market_id)
        vf_result: VolatilityFilterResult = self.vol_filter.apply(
            size=raw_size,
            volatility=vol,
            correlation_id=correlation_id,
            market_id=signal_market_id,
        )
        if not vf_result.approved:
            log.warning(
                "sizing_rejected_volatility_filter",
                correlation_id=correlation_id,
                market_id=signal_market_id,
                strategy=signal_strategy,
                regime=vf_result.regime,
                original_size=raw_size,
            )
            return 0.0

        # ── Step 2: Correlation-aware sizing ──────────────────────────────────
        corr_matrix = self.correlation_matrix.get_matrix()
        sizing_result: SizingResult = self.sizing_patch.apply(
            signal_market_id=signal_market_id,
            size=vf_result.adjusted_size,
            open_position_market_ids=open_position_market_ids,
            correlation_matrix=corr_matrix,
            correlation_id=correlation_id,
        )
        if not sizing_result.approved:
            log.warning(
                "sizing_rejected_correlation",
                correlation_id=correlation_id,
                market_id=signal_market_id,
                strategy=signal_strategy,
                total_corr=sizing_result.total_corr,
                reason=sizing_result.reason,
            )
            return 0.0

        return sizing_result.adjusted_size

    # ── Exit level computation ────────────────────────────────────────────────

    def compute_exit_levels(
        self,
        market_id: str,
        entry_price: float,
        correlation_id: str,
    ) -> ExitLevels:
        """Compute adaptive TP / SL levels for a newly opened position.

        Uses the most recent returns from MarketCache.  Falls back to
        default_vol if return history is insufficient.

        Args:
            market_id: Market of the opened position.
            entry_price: Fill price of the position.
            correlation_id: Request ID.

        Returns:
            ExitLevels with tp_price, sl_price, tp_pct, sl_pct.
        """
        returns = self.market_cache.get_returns(market_id)
        return self.exit_engine.compute_levels(
            entry_price=entry_price,
            returns=returns,
            correlation_id=correlation_id,
            market_id=market_id,
        )

    # ── Fill probability ──────────────────────────────────────────────────────

    def get_fill_prob(
        self,
        market_id: str,
        size: float,
        spread: float,
        depth: float,
        correlation_id: str,
    ) -> float:
        """Compute Phase 6.6 fill probability.

        Pulls latency and volatility from MarketCache automatically.

        Args:
            market_id: Target market.
            size: Proposed order size (USD).
            spread: Current bid-ask spread.
            depth: Available market depth (USD).
            correlation_id: Request ID.

        Returns:
            fill_prob ∈ [0.0, 1.0].
        """
        latency_ms = self.market_cache.get_latency_ms(market_id)
        volatility = self.market_cache.get_volatility(market_id)
        fp_result = self.exec_patch.calc_fill_prob(
            depth=depth,
            size=size,
            latency_ms=latency_ms,
            volatility=volatility,
            spread=spread,
            correlation_id=correlation_id,
        )
        return fp_result.fill_prob

    def get_volatility(self, market_id: str) -> float:
        """Return cached volatility for a market."""
        return self.market_cache.get_volatility(market_id)

    def get_latency_ms(self, market_id: str) -> float:
        """Return cached round-trip latency for a market."""
        return self.market_cache.get_latency_ms(market_id)

    # ── Market maker inventory guard ──────────────────────────────────────────

    async def check_mm_inventory(
        self,
        market_id: str,
        max_position: float,
        correlation_id: str,
    ) -> InventoryCheckResult:
        """Check and enforce MM inventory hard stop.

        Should be called after every order fill that involves MM quotes.

        Args:
            market_id: Market being checked.
            max_position: Max allowed absolute position (USD), typically
                          balance × max_position_pct.
            correlation_id: Request ID.

        Returns:
            InventoryCheckResult with stopped=True if halted.
        """
        return await self.mm_patch.check_inventory(
            market_id=market_id,
            max_position=max_position,
            correlation_id=correlation_id,
        )

    def record_mm_fill(
        self,
        market_id: str,
        filled_size: float,
        outcome: str,
        correlation_id: str,
    ) -> None:
        """Record a MM fill into the inventory tracker.

        Call this after every MM order fill event.
        """
        self.mm_patch.record_fill(market_id, filled_size, outcome, correlation_id)

    def record_mm_close(
        self,
        market_id: str,
        closed_size: float,
        outcome: str,
        correlation_id: str,
    ) -> None:
        """Record a position close into the inventory tracker."""
        self.mm_patch.record_close(market_id, closed_size, outcome, correlation_id)

    async def shutdown(self) -> None:
        """Graceful shutdown: wait for pending MM cancel tasks."""
        await self.mm_patch.cleanup()
        log.info("phase66_integrator_shutdown")

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_config(
        cls,
        cfg: dict,
        mm_cancel_callback=None,
    ) -> "Phase66Integrator":
        """Construct the integrator from top-level config dict.

        Args:
            cfg: Top-level config dict loaded from phase6_6/config.yaml.
            mm_cancel_callback: Async function(market_id, correlation_id) → None.
                Pass MarketMaker.cancel_all_orders from Phase 6.
                If None, cancellation is skipped (safe for testing).

        Example::

            from phase6_6.integration.runner_patch import Phase66Integrator
            import yaml

            with open("phase6_6/config.yaml") as f:
                cfg = yaml.safe_load(f)

            integrator = Phase66Integrator.from_config(
                cfg, mm_cancel_callback=market_maker.cancel_all_orders
            )
        """
        corr_cfg = cfg.get("correlation", {})
        pos_cfg = cfg.get("position", {})

        correlation_matrix = CorrelationMatrix.from_config(cfg)
        exec_patch = ExecutionEnginePatch.from_config(cfg)
        exit_engine = ExitEnginePatch.from_config(cfg)
        sizing_patch = SizingPatch.from_config(cfg)
        vol_filter = VolatilityFilter.from_config(cfg)
        mm_patch = MarketMakerPatch.from_config(cfg, cancel_callback=mm_cancel_callback)
        market_cache = MarketCache(
            default_vol=float(pos_cfg.get("default_vol", 0.02)),
            vol_lookback=20,
        )

        recompute_interval = int(corr_cfg.get("recompute_interval", 10))

        log.info(
            "phase66_integrator_created",
            correlation_window=correlation_matrix._window,
            shrinkage=correlation_matrix._shrinkage,
            ema_alpha=correlation_matrix._alpha,
            recompute_interval=recompute_interval,
            high_vol_threshold=vol_filter._threshold,
            mm_inventory_limit_pct=mm_patch._inv_pct,
            mm_hard_stop_multiplier=mm_patch._multiplier,
        )

        return cls(
            correlation_matrix=correlation_matrix,
            exec_patch=exec_patch,
            exit_engine=exit_engine,
            sizing_patch=sizing_patch,
            vol_filter=vol_filter,
            mm_patch=mm_patch,
            market_cache=market_cache,
            recompute_interval=recompute_interval,
        )
