"""ConfluenceScalperStrategy — multi-signal alignment scalper for mid-range markets.

Foundation contract (P3a):
    BaseStrategy.scan          — emit YES- or NO-side scalp candidates when
                                 liquidity, 24h volume, mid-band pricing, and a
                                 shallow 24h drift all align (confluence).
    BaseStrategy.evaluate_exit — hold (platform TP/SL handles exit timing).
    BaseStrategy.default_tp_sl — TP 8% / SL 4% (tight scalp targets).

Pipeline boundary:
    DATA -> [STRATEGY <-- this file] -> INTELLIGENCE -> RISK -> EXECUTION

This module never places orders, never touches the risk gate, never bypasses
activation guards. SignalCandidates returned from `scan()` are handed to the
downstream scan loop which routes them through risk + execution.

Strategy logic:
    A "confluence" candidate must satisfy ALL of:
        - market is active, accepting orders, not blacklisted, not closed
        - YES price is mid-range (avoids tail markets where scalping has no
          room to breathe)
        - 24h drift is a shallow move (small reversion play, not a trend break)
        - liquidity and 24h volume clear internal floors plus the user filter
    The confidence score is a weighted combination of how close each signal
    sits to its sweet spot, so partial confluence still produces a low score
    rather than a hard skip on borderline data.

Side selection (mean-reversion):
    drift < 0  -> YES  (bet the dip bounces back toward mid)
    drift > 0  -> NO   (bet the pop pulls back toward mid)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ....integrations import polymarket as pm
from ..base import BaseStrategy
from ..types import ExitDecision, MarketFilters, SignalCandidate, UserContext

logger = logging.getLogger(__name__)

MIN_YES_PRICE: float = 0.30
MAX_YES_PRICE: float = 0.70
MIN_ABS_DRIFT: float = 0.02
MAX_ABS_DRIFT: float = 0.08
MIN_LIQUIDITY_USDC: float = 5_000.0
MIN_VOLUME_24H: float = 2_000.0
DEFAULT_TP_PCT: float = 0.08
DEFAULT_SL_PCT: float = 0.04
SCAN_MARKET_LIMIT: int = 100

_W_DRIFT: float = 0.35
_W_LIQUIDITY: float = 0.25
_W_VOLUME: float = 0.20
_W_MIDBAND: float = 0.20

_SUGGESTED_SIZE_FRACTION: float = 0.04
_SUGGESTED_SIZE_MIN_USDC: float = 1.0
_SUGGESTED_SIZE_MAX_USDC: float = 25.0


class ConfluenceScalperStrategy(BaseStrategy):
    """Multi-signal alignment scalper on Polymarket mid-band markets.

    Compatible with balanced, aggressive, and custom profiles only —
    scalping demands frequent re-entries and is inappropriate for the
    conservative risk envelope.
    """

    name = "confluence_scalper"
    version = "1.0.0"
    risk_profile_compatibility = ["balanced", "aggressive", "custom"]

    def default_tp_sl(self) -> tuple[float, float]:
        return (DEFAULT_TP_PCT, DEFAULT_SL_PCT)

    async def scan(
        self,
        market_filters: MarketFilters,
        user_context: UserContext,
    ) -> list[SignalCandidate]:
        """Emit scalp candidates for markets where every confluence signal aligns.

        Returns an empty list on any failure or when no market qualifies.
        Never raises — scan errors must not crash the scheduler scan loop.
        """
        try:
            markets = await pm.get_markets(limit=SCAN_MARKET_LIMIT)
        except Exception as exc:
            logger.warning("confluence_scalper scan: get_markets failed err=%s", exc)
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
                logger.debug("confluence_scalper scan: skip market err=%s", exc)
                continue
            if candidate is not None:
                candidates.append(candidate)

        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates

    async def evaluate_exit(self, position: dict) -> ExitDecision:
        """Defers exit timing to the platform TP/SL watcher."""
        return ExitDecision(should_exit=False, reason="hold")


def _evaluate_market(
    m: dict[str, Any] | None,
    *,
    blacklist: set[str],
    min_liquidity: float,
    user_context: UserContext,
    strategy_name: str,
    signal_ts: datetime,
) -> SignalCandidate | None:
    """Return a SignalCandidate if the market passes all confluence filters."""
    if not isinstance(m, dict):
        return None

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

    drift = _extract_24h_price_change(m)
    if drift is None:
        return None
    abs_drift = abs(drift)
    if abs_drift < MIN_ABS_DRIFT or abs_drift > MAX_ABS_DRIFT:
        return None

    liquidity = _extract_liquidity(m)
    floor_liquidity = max(min_liquidity, MIN_LIQUIDITY_USDC)
    if liquidity < floor_liquidity:
        return None

    volume_24h = _extract_volume_24h(m)
    if volume_24h < MIN_VOLUME_24H:
        return None

    side = "YES" if drift < 0 else "NO"

    drift_sweet_spot = (MIN_ABS_DRIFT + MAX_ABS_DRIFT) / 2.0
    drift_score = 1.0 - min(abs(abs_drift - drift_sweet_spot) / drift_sweet_spot, 1.0)
    drift_score = max(drift_score, 0.0)

    liquidity_excess = liquidity - MIN_LIQUIDITY_USDC
    liquidity_score = max(0.0, min(liquidity_excess / MIN_LIQUIDITY_USDC, 1.0))

    volume_excess = volume_24h - MIN_VOLUME_24H
    volume_score = max(0.0, min(volume_excess / MIN_VOLUME_24H, 1.0))

    midband_score = 1.0 - min(abs(yes_price - 0.5) / 0.20, 1.0)
    midband_score = max(midband_score, 0.0)

    confidence = (
        _W_DRIFT * drift_score
        + _W_LIQUIDITY * liquidity_score
        + _W_VOLUME * volume_score
        + _W_MIDBAND * midband_score
    )
    confidence = max(0.0, min(confidence, 1.0))

    allocated = user_context.available_balance_usdc * user_context.capital_allocation_pct
    suggested = max(
        _SUGGESTED_SIZE_MIN_USDC,
        min(allocated * _SUGGESTED_SIZE_FRACTION, _SUGGESTED_SIZE_MAX_USDC),
    )

    return SignalCandidate(
        market_id=market_id,
        condition_id=condition_id,
        side=side,
        confidence=confidence,
        suggested_size_usdc=suggested,
        strategy_name=strategy_name,
        signal_ts=signal_ts,
        metadata={
            "yes_price": yes_price,
            "drift_24h": drift,
            "liquidity_usdc": liquidity,
            "volume_24h": volume_24h,
            "score_components": {
                "drift": drift_score,
                "liquidity": liquidity_score,
                "volume": volume_score,
                "midband": midband_score,
            },
            "reason": (
                f"confluence: drift {drift:+.2%}, price {yes_price:.2f}, "
                f"liq ${liquidity:.0f}, vol ${volume_24h:.0f}"
            ),
        },
        reasoning=(
            f"Scalp {side} mean-revert: drift {drift:+.2%}, "
            f"price {yes_price:.2f}, conf={confidence:.0%}."
        ),
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


__all__ = ["ConfluenceScalperStrategy"]
