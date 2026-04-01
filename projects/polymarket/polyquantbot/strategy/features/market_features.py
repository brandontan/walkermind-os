"""Market feature engineering for strategy signals.

Computes derived features from raw market data (bid, ask, depth, volume) that
are consumed by the strategy layer.  All computations are stateless helper
functions — strategies maintain their own rolling state.

Features produced:
  - mid         : (bid + ask) / 2
  - spread      : ask - bid
  - spread_pct  : spread / mid (relative spread)
  - depth_total : depth_yes + depth_no (total book depth in USDC)
  - depth_imbalance : (depth_yes - depth_no) / (depth_yes + depth_no)
  - vwap_proxy  : volume-weighted mid estimate (when recent_trades provided)
  - price_velocity : mean price change per tick from a tick list

Usage::

    from projects.polymarket.polyquantbot.strategy.features.market_features import (
        compute_features,
        MarketFeatures,
    )

    features = compute_features(market_data)
    print(features.spread_pct, features.depth_imbalance)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MarketFeatures:
    """Derived features computed from a single market data snapshot.

    Attributes:
        market_id: Polymarket condition ID.
        bid: Best bid price.
        ask: Best ask price.
        mid: Midpoint price = (bid + ask) / 2.
        spread: Absolute spread = ask - bid.
        spread_pct: Relative spread = spread / mid (0 if mid == 0).
        depth_yes: Order book depth on the YES side (USDC).
        depth_no: Order book depth on the NO side (USDC).
        depth_total: Combined depth = depth_yes + depth_no.
        depth_imbalance: (depth_yes - depth_no) / depth_total.
            +1.0 = fully YES-weighted, -1.0 = fully NO-weighted, 0.0 = balanced.
            None if depth_total == 0.
        volume: Reported 24h trading volume (USDC), if provided.
        vwap_proxy: Volume-weighted average of recent trade prices, if available.
        price_velocity: Mean price change per tick from recent_ticks list.
            None if fewer than 2 ticks supplied.
        raw: Original market_data dict for pass-through access.
    """

    market_id: str
    bid: float
    ask: float
    mid: float
    spread: float
    spread_pct: float
    depth_yes: float
    depth_no: float
    depth_total: float
    depth_imbalance: Optional[float]
    volume: float
    vwap_proxy: Optional[float]
    price_velocity: Optional[float]
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise features for logging or persistence."""
        return {
            "market_id": self.market_id,
            "bid": round(self.bid, 4),
            "ask": round(self.ask, 4),
            "mid": round(self.mid, 4),
            "spread": round(self.spread, 4),
            "spread_pct": round(self.spread_pct, 4),
            "depth_yes": self.depth_yes,
            "depth_no": self.depth_no,
            "depth_total": self.depth_total,
            "depth_imbalance": (
                round(self.depth_imbalance, 4) if self.depth_imbalance is not None else None
            ),
            "volume": self.volume,
            "vwap_proxy": (
                round(self.vwap_proxy, 4) if self.vwap_proxy is not None else None
            ),
            "price_velocity": (
                round(self.price_velocity, 6) if self.price_velocity is not None else None
            ),
        }


def compute_features(
    market_data: Dict[str, Any],
    market_id: str = "",
    recent_ticks: Optional[List[float]] = None,
    recent_trades: Optional[List[Dict[str, float]]] = None,
) -> MarketFeatures:
    """Compute derived market features from a raw market data snapshot.

    Args:
        market_data: Dict with keys: bid, ask, mid (opt), depth_yes, depth_no, volume (opt).
        market_id: Polymarket condition ID (optional context label).
        recent_ticks: List of recent mid prices (newest last) for velocity computation.
        recent_trades: List of dicts with ``price`` and ``size`` keys for VWAP proxy.

    Returns:
        :class:`MarketFeatures` with all derived values populated.
    """
    bid = float(market_data.get("bid", 0.0))
    ask = float(market_data.get("ask", 1.0))
    mid = float(market_data.get("mid", (bid + ask) / 2.0))
    depth_yes = float(market_data.get("depth_yes", 0.0))
    depth_no = float(market_data.get("depth_no", 0.0))
    volume = float(market_data.get("volume", 0.0))

    spread = max(0.0, ask - bid)
    spread_pct = spread / mid if mid > 0 else 0.0
    depth_total = depth_yes + depth_no

    depth_imbalance: Optional[float]
    if depth_total > 0:
        depth_imbalance = (depth_yes - depth_no) / depth_total
    else:
        depth_imbalance = None

    # VWAP proxy from recent trade list
    vwap_proxy: Optional[float] = None
    if recent_trades:
        total_value = sum(t["price"] * t["size"] for t in recent_trades if t.get("size", 0) > 0)
        total_size = sum(t["size"] for t in recent_trades if t.get("size", 0) > 0)
        if total_size > 0:
            vwap_proxy = total_value / total_size

    # Price velocity from tick list
    price_velocity: Optional[float] = None
    if recent_ticks and len(recent_ticks) >= 2:
        deltas = [recent_ticks[i + 1] - recent_ticks[i] for i in range(len(recent_ticks) - 1)]
        price_velocity = sum(deltas) / len(deltas)

    return MarketFeatures(
        market_id=market_id,
        bid=bid,
        ask=ask,
        mid=mid,
        spread=spread,
        spread_pct=spread_pct,
        depth_yes=depth_yes,
        depth_no=depth_no,
        depth_total=depth_total,
        depth_imbalance=depth_imbalance,
        volume=volume,
        vwap_proxy=vwap_proxy,
        price_velocity=price_velocity,
        raw=dict(market_data),
    )
