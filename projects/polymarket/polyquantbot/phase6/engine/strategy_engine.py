"""Multi-strategy engine — Phase 6. Unchanged from Phase 5.

Strategies: Bayesian, Momentum, MeanReversion, Arbitrage.
All implement BaseStrategy ABC, are async, stateless per call,
parameterized from config.
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import structlog

from ..core.signal_model import SignalResult, calculate_ev

if TYPE_CHECKING:
    from .strategy_manager import StrategyManager

log = structlog.get_logger()

ALPHA = 0.05  # Bayesian informational edge


class BaseStrategy(ABC):
    """Abstract base for all trading strategies."""

    name: str

    @abstractmethod
    async def generate_signal(self, market_data: dict) -> list[SignalResult]:
        """Return 0, 1, or 2 signals (arbitrage emits 2)."""
        ...


class BayesianStrategy(BaseStrategy):
    """Applies a fixed informational edge over market price."""

    name = "bayesian"

    def __init__(self, min_ev: float) -> None:
        """Initialise with minimum EV threshold."""
        self._min_ev = min_ev

    async def generate_signal(self, market_data: dict) -> list[SignalResult]:
        """Generate signal if Bayesian EV exceeds threshold."""
        p_market: float = market_data["p_market"]
        if p_market <= 0 or p_market >= 1:
            return []
        p_model = min(p_market + ALPHA, 0.99)
        ev = calculate_ev(p_model, p_market)
        if ev < self._min_ev:
            return []
        zscore = ev / max(ALPHA, 1e-9)
        return [SignalResult(
            market_id=market_data["market_id"],
            question=market_data["question"],
            outcome="YES",
            p_model=p_model,
            p_market=p_market,
            ev=ev,
            zscore=round(zscore, 4),
            strategy=self.name,
        )]


class MomentumStrategy(BaseStrategy):
    """Detects upward price drift and rides the momentum."""

    name = "momentum"

    def __init__(self, min_ev: float, threshold: float) -> None:
        """Initialise with EV threshold and minimum momentum."""
        self._min_ev = min_ev
        self._threshold = threshold

    async def generate_signal(self, market_data: dict) -> list[SignalResult]:
        """Generate signal if price drift exceeds momentum threshold."""
        p_market: float = market_data["p_market"]
        p_prev: float = market_data.get("p_market_prev", p_market)
        if p_market <= 0 or p_market >= 1:
            return []
        momentum = p_market - p_prev
        if momentum < self._threshold:
            return []
        p_model = min(p_market + momentum * 0.5, 0.99)
        ev = calculate_ev(p_model, p_market)
        if ev < self._min_ev:
            return []
        zscore = momentum / max(self._threshold, 1e-9)
        return [SignalResult(
            market_id=market_data["market_id"],
            question=market_data["question"],
            outcome="YES",
            p_model=p_model,
            p_market=p_market,
            ev=ev,
            zscore=round(zscore, 4),
            strategy=self.name,
        )]


class MeanReversionStrategy(BaseStrategy):
    """Detects price depressed below rolling mean and expects reversion."""

    name = "mean_reversion"

    def __init__(self, min_ev: float, k: float) -> None:
        """Initialise with EV threshold and std-deviation multiplier k."""
        self._min_ev = min_ev
        self._k = k

    async def generate_signal(self, market_data: dict) -> list[SignalResult]:
        """Generate signal if price is k-sigma below bid/ask mean."""
        p_market: float = market_data["p_market"]
        if p_market <= 0 or p_market >= 1:
            return []
        bid: float = market_data.get("bid", p_market - 0.01)
        ask: float = market_data.get("ask", p_market + 0.01)
        mean = (bid + ask) / 2
        std = max((ask - bid) / 2, 0.001)
        deviation = (p_market - mean) / std
        if deviation >= -self._k:
            return []
        p_model = min(mean + std * 0.5, 0.99)
        ev = calculate_ev(p_model, p_market)
        if ev < self._min_ev:
            return []
        zscore = abs(deviation)
        return [SignalResult(
            market_id=market_data["market_id"],
            question=market_data["question"],
            outcome="YES",
            p_model=p_model,
            p_market=p_market,
            ev=ev,
            zscore=round(zscore, 4),
            strategy=self.name,
        )]


class ArbitrageStrategy(BaseStrategy):
    """Detects YES+NO mispricing and emits paired buy signals."""

    name = "arbitrage"

    def __init__(self, fee_margin: float) -> None:
        """Initialise with minimum net edge after fees."""
        self._fee_margin = fee_margin

    async def generate_signal(self, market_data: dict) -> list[SignalResult]:
        """Emit BUY YES + BUY NO when p_yes + p_no < 1 - fee_margin."""
        p_yes: float | None = market_data.get("p_yes")
        p_no: float | None = market_data.get("p_no")
        if p_yes is None or p_no is None:
            return []
        total = p_yes + p_no
        edge = (1.0 - total) - self._fee_margin
        if edge <= 0:
            return []
        zscore = edge / max(self._fee_margin, 1e-9)
        half_edge = edge / 2
        market_id = market_data["market_id"]
        question = market_data["question"]
        log.info("arbitrage_detected", market_id=market_id, p_yes=p_yes, p_no=p_no,
                 edge=round(edge, 4))
        return [
            SignalResult(
                market_id=market_id, question=question, outcome="YES",
                p_model=min(p_yes + half_edge, 0.99), p_market=p_yes,
                ev=half_edge, zscore=round(zscore, 4), strategy=self.name,
            ),
            SignalResult(
                market_id=market_id, question=question, outcome="NO",
                p_model=min(p_no + half_edge, 0.99), p_market=p_no,
                ev=half_edge, zscore=round(zscore, 4), strategy=self.name,
            ),
        ]


def build_strategies(cfg: dict) -> list[BaseStrategy]:
    """Build enabled strategies from config."""
    s_cfg = cfg["strategy"]
    enabled = s_cfg["enabled"]
    min_ev = cfg["trading"]["min_ev_threshold"]
    strategies: list[BaseStrategy] = []
    if enabled.get("bayesian"):
        strategies.append(BayesianStrategy(min_ev=min_ev))
    if enabled.get("momentum"):
        strategies.append(MomentumStrategy(
            min_ev=min_ev, threshold=s_cfg["momentum_threshold"]))
    if enabled.get("mean_reversion"):
        strategies.append(MeanReversionStrategy(
            min_ev=min_ev, k=s_cfg["mean_reversion_k"]))
    if enabled.get("arbitrage"):
        strategies.append(ArbitrageStrategy(fee_margin=s_cfg["fee_margin"]))
    return strategies


async def run_all_strategies(
    strategies: list[BaseStrategy],
    market_data: dict,
    strategy_manager: StrategyManager,
) -> list[SignalResult]:
    """Run all enabled strategies concurrently via asyncio.gather.

    Returns flat sorted list: arbitrage first, then by ev descending.
    """
    enabled = [s for s in strategies if strategy_manager.is_enabled(s.name)]
    if not enabled:
        return []

    results = await asyncio.gather(
        *[s.generate_signal(market_data) for s in enabled],
        return_exceptions=True,
    )

    signals: list[SignalResult] = []
    for s, res in zip(enabled, results):
        if isinstance(res, Exception):
            log.warning("strategy_error", strategy=s.name, error=str(res))
            continue
        signals.extend(res)

    signals.sort(key=lambda sig: (sig.strategy != "arbitrage", -sig.ev))
    return signals
