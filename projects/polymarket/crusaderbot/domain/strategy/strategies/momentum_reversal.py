"""MomentumReversalStrategy — contrarian mean-reversion on breaking markets.

Foundation contract (P3a):
    BaseStrategy.scan          — emit YES-side SignalCandidates for oversold markets.
    BaseStrategy.evaluate_exit — hold (platform TP/SL handles exit timing).
    BaseStrategy.default_tp_sl — TP 15% / SL 8% (conservative defaults).

Pipeline boundary:
    DATA -> [STRATEGY <-- this file] -> INTELLIGENCE -> RISK -> EXECUTION

This module never places orders, never touches the risk gate, never bypasses
activation guards. SignalCandidates returned from `scan()` are handed to the
downstream scan loop which routes them through risk + execution.

Strategy logic:
    Identify markets where the YES price has dropped significantly in 24h.
    Filter by liquidity, volume, market status, and YES price range. Bet on
    price reversion. Higher drops → higher confidence scores.

Design reference:
    lib/strategies/momentum.py (legacy — design reference only, not imported).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ....integrations import polymarket as pm
from ..base import BaseStrategy
from ..types import ExitDecision, MarketFilters, SignalCandidate, UserContext

logger = logging.getLogger(__name__)

DROP_THRESHOLD: float = -0.10
MIN_VOLUME_24H: float = 1_000.0
MIN_YES_PRICE: float = 0.10
MAX_YES_PRICE: float = 0.85
DEFAULT_TP_PCT: float = 0.15
DEFAULT_SL_PCT: float = 0.08
SCAN_MARKET_LIMIT: int = 100

_SUGGESTED_SIZE_FRACTION: float = 0.05
_SUGGESTED_SIZE_MIN_USDC: float = 1.0
_SUGGESTED_SIZE_MAX_USDC: float = 50.0


class MomentumReversalStrategy(BaseStrategy):
    """Contrarian mean-reversion on Polymarket YES tokens with large 24h drops.

    Compatible with balanced and aggressive profiles only — this strategy takes
    directional risk on oversold markets, inappropriate for conservative users.
    """

    name = "momentum_reversal"
    version = "1.0.0"
    risk_profile_compatibility = ["balanced", "aggressive"]

    def default_tp_sl(self) -> tuple[float, float]:
        return (DEFAULT_TP_PCT, DEFAULT_SL_PCT)

    async def scan(
        self,
        market_filters: MarketFilters,
        user_context: UserContext,
    ) -> list[SignalCandidate]:
        """Emit YES-side candidates for markets with significant 24h price drops.

        Returns an empty list on any failure or when no market qualifies.
        Never raises — scan errors must not crash the scheduler scan loop.
        """
        try:
            markets = await pm.get_markets(limit=SCAN_MARKET_LIMIT)
        except Exception as exc:
            logger.warning("momentum_reversal scan: get_markets failed err=%s", exc)
            return []

        if not markets:
            return []

        now = datetime.now(timezone.utc)
        blacklist = set(market_filters.blacklisted_market_ids)
        effective_min_liquidity = max(market_filters.min_liquidity, 0.0)
        candidates: list[SignalCandidate] = []

        for m in markets:
            try:
                candidate = _evaluate_market(
                    m,
                    blacklist=blacklist,
                    min_liquidity=effective_min_liquidity,
                    user_context=user_context,
                    strategy_name=self.name,
                    signal_ts=now,
                )
            except Exception as exc:
                logger.debug("momentum_reversal scan: skip market err=%s", exc)
                continue
            if candidate is not None:
                candidates.append(candidate)

        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates

    async def evaluate_exit(self, position: dict) -> ExitDecision:
        """Defers exit timing to the platform TP/SL watcher."""
        return ExitDecision(should_exit=False, reason="hold")


def _evaluate_market(
    m: dict[str, Any],
    *,
    blacklist: set[str],
    min_liquidity: float,
    user_context: UserContext,
    strategy_name: str,
    signal_ts: datetime,
) -> SignalCandidate | None:
    """Return a SignalCandidate if the market passes all filters, else None."""
    market_id = str(m.get("id") or "")
    condition_id = str(
        m.get("conditionId") or m.get("condition_id") or m.get("conditionID") or ""
    )
    if not market_id or not condition_id:
        return None

    if condition_id in blacklist or market_id in blacklist:
        return None

    if not m.get("active"):
        return None
    if m.get("closed"):
        return None
    if not m.get("acceptingOrders", m.get("accepting_orders", True)):
        return None

    yes_price = _extract_yes_price(m)
    if yes_price is None:
        return None
    if yes_price < MIN_YES_PRICE or yes_price > MAX_YES_PRICE:
        return None

    drop = _extract_24h_price_change(m)
    if drop is None or drop > DROP_THRESHOLD:
        return None

    liquidity = _extract_liquidity(m)
    if liquidity < min_liquidity:
        return None

    volume_24h = _extract_volume_24h(m)
    if volume_24h < MIN_VOLUME_24H:
        return None

    confidence = min(abs(drop) / 0.20, 1.0)

    allocated = user_context.available_balance_usdc * user_context.capital_allocation_pct
    suggested = max(
        _SUGGESTED_SIZE_MIN_USDC,
        min(allocated * _SUGGESTED_SIZE_FRACTION, _SUGGESTED_SIZE_MAX_USDC),
    )

    return SignalCandidate(
        market_id=market_id,
        condition_id=condition_id,
        side="YES",
        confidence=confidence,
        suggested_size_usdc=suggested,
        strategy_name=strategy_name,
        signal_ts=signal_ts,
        metadata={
            "yes_price": yes_price,
            "drop_24h": drop,
            "liquidity_usdc": liquidity,
            "volume_24h": volume_24h,
            "reason": (
                f"24h drop {drop:+.2f}, price {yes_price:.2f}, liq ${liquidity:.0f}"
            ),
        },
    )


def _extract_yes_price(m: dict[str, Any]) -> float | None:
    prices = m.get("outcomePrices") or m.get("outcome_prices")
    if prices and len(prices) >= 1:
        try:
            return float(prices[0])
        except (TypeError, ValueError):
            return None
    return None


def _extract_24h_price_change(m: dict[str, Any]) -> float | None:
    val = m.get("oneDayPriceChange")
    if val is not None:
        try:
            return float(val)
        except (TypeError, ValueError):
            pass
    pc = m.get("priceChange")
    if isinstance(pc, dict):
        val = pc.get("oneDay")
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    return None


def _extract_liquidity(m: dict[str, Any]) -> float:
    liq = m.get("liquidity")
    if liq is None:
        liq = m.get("liquidityNum") or m.get("liquidity_num")
    if isinstance(liq, dict):
        return float(liq.get("total") or 0)
    if liq is not None:
        try:
            return float(liq)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _extract_volume_24h(m: dict[str, Any]) -> float:
    val = (
        m.get("volume_24hr")
        or m.get("volume24h")
        or m.get("volume24hr")
        or m.get("volumeNum")
        or m.get("volume_num")
        or m.get("volume")
        or 0
    )
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


__all__ = ["MomentumReversalStrategy"]
