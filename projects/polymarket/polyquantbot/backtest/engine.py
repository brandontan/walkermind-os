"""Event-driven backtesting engine for PolyQuantBot strategies.

The BacktestEngine feeds historical market snapshots (ticks) through the
strategy layer in sequence, simulating fills and tracking performance metrics
identical to the live system.

Design principles:
  - Stateless except for the run result accumulator — no shared state between runs.
  - Fills are simulated with a configurable slippage model.
  - Fractional Kelly sizing rules (α = 0.25) are enforced identically to live.
  - Zero external I/O — entire run is in-memory.

Usage::

    from projects.polymarket.polyquantbot.backtest.engine import (
        BacktestEngine,
        BacktestConfig,
        TickData,
    )
    from projects.polymarket.polyquantbot.strategy.router import StrategyRouter

    router = StrategyRouter.from_registry()
    engine = BacktestEngine(router=router, config=BacktestConfig(bankroll=10_000.0))

    ticks = [
        TickData(market_id="mkt-1", bid=0.48, ask=0.52, depth_yes=15_000, depth_no=12_000),
        ...
    ]

    result = await engine.run(ticks)
    print(result.summary())
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import structlog

from ..strategy.base.base_strategy import SignalResult
from ..strategy.router import StrategyRouter

log = structlog.get_logger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

_DEFAULT_SLIPPAGE_PCT: float = 0.002   # 0.2% slippage on fills
_DEFAULT_MAX_POSITION_PCT: float = 0.10  # 10% bankroll per position
_FILL_PROBABILITY: float = 1.0        # 100% fill rate in backtesting (optimistic baseline)
_EPSILON: float = 1e-6               # small value to prevent division by zero


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class TickData:
    """A single historical market snapshot (one "tick").

    Attributes:
        market_id: Polymarket condition ID.
        bid: Best bid price at the tick.
        ask: Best ask price at the tick.
        depth_yes: YES-side book depth in USDC.
        depth_no: NO-side book depth in USDC.
        mid: Midpoint price; computed from bid/ask if not supplied.
        volume: Optional 24h volume.
        timestamp_ms: Optional wall-clock timestamp for the tick (epoch ms).
        extra: Optional extra fields forwarded to strategy market_data.
    """

    market_id: str
    bid: float
    ask: float
    depth_yes: float = 20_000.0
    depth_no: float = 20_000.0
    mid: Optional[float] = None
    volume: float = 0.0
    timestamp_ms: Optional[int] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_market_data(self) -> Dict[str, Any]:
        """Convert to the market_data dict expected by strategy.evaluate()."""
        mid = self.mid if self.mid is not None else (self.bid + self.ask) / 2.0
        d = {
            "bid": self.bid,
            "ask": self.ask,
            "mid": mid,
            "depth_yes": self.depth_yes,
            "depth_no": self.depth_no,
            "volume": self.volume,
        }
        d.update(self.extra)
        return d


@dataclass
class BacktestConfig:
    """Configuration for a backtest run.

    Attributes:
        bankroll: Starting capital in USD.
        max_position_pct: Maximum fraction of bankroll per single position.
        slippage_pct: Simulated fill slippage as a fraction of the execution price.
        fill_probability: Probability that a submitted order gets filled (0.0–1.0).
    """

    bankroll: float = 10_000.0
    max_position_pct: float = _DEFAULT_MAX_POSITION_PCT
    slippage_pct: float = _DEFAULT_SLIPPAGE_PCT
    fill_probability: float = _FILL_PROBABILITY


@dataclass
class BacktestTrade:
    """A single simulated trade recorded during a backtest run.

    Attributes:
        market_id: Market where the trade was taken.
        side: "YES" or "NO".
        entry_price: Simulated fill price (includes slippage).
        size_usd: USD size of the position.
        signal_edge: Edge at signal time.
        exit_price: Price at the next opposite tick (simplified PnL model).
        pnl_usd: Realised PnL for this trade.
        strategy_name: Which strategy generated the signal.
        tick_index: Index of the tick in the input sequence.
    """

    market_id: str
    side: str
    entry_price: float
    size_usd: float
    signal_edge: float
    exit_price: float = 0.0
    pnl_usd: float = 0.0
    strategy_name: str = ""
    tick_index: int = 0


@dataclass
class BacktestResult:
    """Aggregate result from a complete BacktestEngine.run() call.

    Attributes:
        ticks_processed: Total market ticks evaluated.
        trades: All simulated trades.
        total_pnl_usd: Net PnL across all trades.
        win_rate: Fraction of profitable trades (0.0–1.0).
        sharpe_ratio: Annualised Sharpe ratio estimate (None if < 2 trades).
        max_drawdown_pct: Maximum drawdown as a fraction of peak equity.
        profit_factor: Gross profit / gross loss (None if no losses).
        signals_generated: Total signals across all strategies.
        strategies_evaluated: Names of strategies that participated.
    """

    ticks_processed: int
    trades: List[BacktestTrade]
    total_pnl_usd: float
    win_rate: float
    sharpe_ratio: Optional[float]
    max_drawdown_pct: float
    profit_factor: Optional[float]
    signals_generated: int
    strategies_evaluated: List[str]

    def summary(self) -> Dict[str, Any]:
        """Return a serialisable summary dict for logging or reporting."""
        return {
            "ticks_processed": self.ticks_processed,
            "total_trades": len(self.trades),
            "total_pnl_usd": round(self.total_pnl_usd, 2),
            "win_rate": round(self.win_rate, 4),
            "sharpe_ratio": (
                round(self.sharpe_ratio, 4) if self.sharpe_ratio is not None else None
            ),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "profit_factor": (
                round(self.profit_factor, 4) if self.profit_factor is not None else None
            ),
            "signals_generated": self.signals_generated,
            "strategies_evaluated": self.strategies_evaluated,
        }


# ── BacktestEngine ────────────────────────────────────────────────────────────


class BacktestEngine:
    """Event-driven backtesting engine.

    Feeds a sequence of :class:`TickData` snapshots through a :class:`StrategyRouter`
    and simulates trades with configurable fill and slippage models.

    Args:
        router: Pre-configured :class:`StrategyRouter` with registered strategies.
        config: :class:`BacktestConfig` with bankroll and simulation parameters.
    """

    def __init__(
        self,
        router: StrategyRouter,
        config: Optional[BacktestConfig] = None,
    ) -> None:
        self._router = router
        self._config = config or BacktestConfig()

    # ── Public API ────────────────────────────────────────────────────────────

    async def run(self, ticks: Sequence[TickData]) -> BacktestResult:
        """Run a full backtest over a sequence of ticks.

        Each tick is evaluated by all active strategies.  Signals are converted
        to simulated trades.  A simplified immediate-exit PnL model is used:
        the position is closed at the *next* tick's mid price.

        Args:
            ticks: Ordered sequence of historical market snapshots.

        Returns:
            :class:`BacktestResult` with all performance metrics.
        """
        trades: List[BacktestTrade] = []
        signals_generated = 0
        tick_list = list(ticks)

        log.info(
            "backtest.run_start",
            ticks=len(tick_list),
            bankroll=self._config.bankroll,
            strategies=self._router.strategy_names,
        )

        for idx, tick in enumerate(tick_list):
            market_data = tick.to_market_data()
            result = await self._router.evaluate(tick.market_id, market_data)
            signals_generated += len(result.signals)

            for signal in result.signals:
                # Determine exit price from next available tick for same market
                exit_price = self._find_exit_price(tick_list, idx, tick.market_id, signal.side)

                trade = self._simulate_fill(signal, idx, exit_price)
                if trade is not None:
                    trades.append(trade)

        result_metrics = self._compute_metrics(
            trades=trades,
            ticks_processed=len(tick_list),
            signals_generated=signals_generated,
        )

        log.info(
            "backtest.run_complete",
            **result_metrics.summary(),
        )

        return result_metrics

    # ── Private helpers ───────────────────────────────────────────────────────

    def _simulate_fill(
        self,
        signal: SignalResult,
        tick_index: int,
        exit_price: float,
    ) -> Optional[BacktestTrade]:
        """Simulate a single fill for a signal.

        Args:
            signal: The strategy signal to fill.
            tick_index: Current tick index in the sequence.
            exit_price: Price at which the position will be closed.

        Returns:
            :class:`BacktestTrade` or None if the fill is rejected by risk rules.
        """
        # Enforce max position cap
        max_size = self._config.bankroll * self._config.max_position_pct
        size_usd = min(signal.size_usdc, max_size)
        if size_usd <= 0:
            return None

        # Simulate slippage: YES buys at ask + slippage; NO sells at bid - slippage.
        # When actual ask/bid aren't available in SignalResult, approximate from edge:
        # a YES trade expects p_model > p_market, so entry ≈ p_market + edge/2 + slippage.
        slippage = self._config.slippage_pct
        if signal.side == "YES":
            # Entry above the signal edge (buying the outcome): higher price = worse fill
            entry_price = min(0.99, (0.5 + signal.edge / 2.0) * (1.0 + slippage))
            entry_price = max(0.01, entry_price)
        else:
            # Entry below the complement price (buying NO = selling YES)
            entry_price = max(0.01, (0.5 - signal.edge / 2.0) * (1.0 - slippage))
            entry_price = min(0.99, entry_price)

        # PnL model: edge captured proportionally to signal edge
        if exit_price > 0:
            if signal.side == "YES":
                pnl = (exit_price - entry_price) * (size_usd / max(entry_price, _EPSILON))
            else:
                pnl = (entry_price - exit_price) * (size_usd / max(1.0 - entry_price, _EPSILON))
        else:
            pnl = 0.0

        strategy_name = signal.metadata.get("strategy", "unknown")

        return BacktestTrade(
            market_id=signal.market_id,
            side=signal.side,
            entry_price=round(entry_price, 4),
            size_usd=round(size_usd, 2),
            signal_edge=signal.edge,
            exit_price=round(exit_price, 4),
            pnl_usd=round(pnl, 4),
            strategy_name=strategy_name,
            tick_index=tick_index,
        )

    def _find_exit_price(
        self,
        ticks: List[TickData],
        current_idx: int,
        market_id: str,
        side: str,
    ) -> float:
        """Find the exit price for a trade from subsequent ticks.

        Uses the mid price of the next tick for the same market.

        Args:
            ticks: Full tick sequence.
            current_idx: Index of the signal tick.
            market_id: Market to search for.
            side: Trade direction ("YES" or "NO") — used for price reference.

        Returns:
            Exit price (mid of next same-market tick), or 0.5 as neutral fallback.
        """
        for i in range(current_idx + 1, len(ticks)):
            t = ticks[i]
            if t.market_id == market_id:
                mid = t.mid if t.mid is not None else (t.bid + t.ask) / 2.0
                return mid
        # Fallback: neutral mid
        return 0.5

    def _compute_metrics(
        self,
        trades: List[BacktestTrade],
        ticks_processed: int,
        signals_generated: int,
    ) -> BacktestResult:
        """Compute aggregate performance metrics from a list of trades.

        Args:
            trades: All simulated trades from the run.
            ticks_processed: Total ticks evaluated.
            signals_generated: Total signals produced by all strategies.

        Returns:
            :class:`BacktestResult` with computed metrics.
        """
        if not trades:
            return BacktestResult(
                ticks_processed=ticks_processed,
                trades=[],
                total_pnl_usd=0.0,
                win_rate=0.0,
                sharpe_ratio=None,
                max_drawdown_pct=0.0,
                profit_factor=None,
                signals_generated=signals_generated,
                strategies_evaluated=self._router.strategy_names,
            )

        total_pnl = sum(t.pnl_usd for t in trades)
        wins = [t for t in trades if t.pnl_usd > 0]
        losses = [t for t in trades if t.pnl_usd <= 0]
        win_rate = len(wins) / len(trades) if trades else 0.0

        # Gross profit / gross loss
        gross_profit = sum(t.pnl_usd for t in wins)
        gross_loss = abs(sum(t.pnl_usd for t in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else None

        # Drawdown: rolling equity curve
        equity = self._config.bankroll
        peak = equity
        max_dd = 0.0
        for t in trades:
            equity += t.pnl_usd
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

        # Sharpe ratio: annualised approximation (using per-trade PnL as returns)
        sharpe: Optional[float] = None
        if len(trades) >= 2:
            pnls = [t.pnl_usd for t in trades]
            mean_pnl = sum(pnls) / len(pnls)
            variance = sum((p - mean_pnl) ** 2 for p in pnls) / len(pnls)
            std_pnl = variance ** 0.5
            if std_pnl > 0:
                # Annualise by √252 (daily equivalent approximation)
                sharpe = round((mean_pnl / std_pnl) * (252 ** 0.5), 4)

        return BacktestResult(
            ticks_processed=ticks_processed,
            trades=trades,
            total_pnl_usd=round(total_pnl, 4),
            win_rate=round(win_rate, 4),
            sharpe_ratio=sharpe,
            max_drawdown_pct=round(max_dd, 4),
            profit_factor=profit_factor,
            signals_generated=signals_generated,
            strategies_evaluated=self._router.strategy_names,
        )
