from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal

import structlog

log = structlog.get_logger(__name__)

DriftRejectReason = Literal["price_deviation", "ev_negative", "liquidity_insufficient"]


@dataclass(frozen=True)
class DriftGuardResult:
    approved: bool
    reason: DriftRejectReason | None
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ExecutionDriftGuard:
    """Fail-closed execution boundary guard for price/EV/liquidity drift checks."""

    def __init__(
        self,
        *,
        max_price_deviation_ratio: float = 0.03,
        max_slippage_ratio: float = 0.02,
    ) -> None:
        self._max_price_deviation_ratio = max(0.0, float(max_price_deviation_ratio))
        self._max_slippage_ratio = max(0.0, float(max_slippage_ratio))

    def validate(
        self,
        validated_price: float,
        current_orderbook: dict[str, Any],
        model_probability: float,
        order_size: float,
        side: str,
    ) -> DriftGuardResult:
        safe_validated_price = float(validated_price)
        normalized_side = str(side).strip().upper()
        safe_model_probability = max(0.0, min(1.0, float(model_probability)))
        safe_order_size = max(0.0, float(order_size))

        current_price = self._resolve_reference_price(current_orderbook, normalized_side)
        if current_price <= 0.0:
            return self._reject(
                reason="liquidity_insufficient",
                details={
                    "error": "invalid_current_price",
                    "current_price": current_price,
                },
            )

        max_deviation = safe_validated_price * self._max_price_deviation_ratio
        deviation = abs(current_price - safe_validated_price)
        if safe_validated_price <= 0.0:
            return self._reject(
                reason="price_deviation",
                details={
                    "error": "invalid_validated_price",
                    "validated_price": safe_validated_price,
                    "current_price": current_price,
                },
            )
        if (deviation - max_deviation) > 1e-12:
            return self._reject(
                reason="price_deviation",
                details={
                    "validated_price": safe_validated_price,
                    "current_price": current_price,
                    "deviation": deviation,
                    "max_deviation": max_deviation,
                    "max_price_deviation_ratio": self._max_price_deviation_ratio,
                },
            )

        b_new = (1.0 / current_price) - 1.0
        ev_new = (safe_model_probability * b_new) - (1.0 - safe_model_probability)
        if ev_new <= 0.0:
            return self._reject(
                reason="ev_negative",
                details={
                    "validated_price": safe_validated_price,
                    "current_price": current_price,
                    "model_probability": safe_model_probability,
                    "b_new": b_new,
                    "ev_new": ev_new,
                },
            )

        fill_simulation = self._simulate_fill(
            orderbook=current_orderbook,
            side=normalized_side,
            order_size=safe_order_size,
        )
        if not fill_simulation["sufficient_depth"]:
            return self._reject(
                reason="liquidity_insufficient",
                details={
                    **fill_simulation,
                    "current_price": current_price,
                },
            )

        expected_fill_price = float(fill_simulation["vwap"])
        slippage_ratio = abs(expected_fill_price - current_price) / max(current_price, 1e-9)
        if slippage_ratio > self._max_slippage_ratio:
            return self._reject(
                reason="liquidity_insufficient",
                details={
                    **fill_simulation,
                    "current_price": current_price,
                    "expected_fill_price": expected_fill_price,
                    "slippage_ratio": slippage_ratio,
                    "max_slippage_ratio": self._max_slippage_ratio,
                },
            )

        return DriftGuardResult(
            approved=True,
            reason=None,
            details={
                "validated_price": safe_validated_price,
                "current_price": current_price,
                "ev_new": ev_new,
                "expected_fill_price": expected_fill_price,
                "slippage_ratio": slippage_ratio,
            },
        )

    def _reject(self, *, reason: DriftRejectReason, details: dict[str, Any]) -> DriftGuardResult:
        log.warning("execution_drift_guard_rejected", reason=reason, **details)
        return DriftGuardResult(approved=False, reason=reason, details=details)

    def _resolve_reference_price(self, orderbook: dict[str, Any], side: str) -> float:
        asks = self._extract_levels(orderbook, key="asks")
        bids = self._extract_levels(orderbook, key="bids")
        if side in {"YES", "BUY", "LONG"}:
            if asks:
                return float(asks[0][0])
            if bids:
                return float(bids[0][0])
        else:
            if bids:
                return float(bids[0][0])
            if asks:
                return float(asks[0][0])

        for key in ("mid_price", "price", "best_ask", "best_bid"):
            if key in orderbook:
                try:
                    value = float(orderbook[key])
                except (TypeError, ValueError):
                    continue
                if value > 0.0:
                    return value
        return 0.0

    def _simulate_fill(self, *, orderbook: dict[str, Any], side: str, order_size: float) -> dict[str, Any]:
        if order_size <= 0.0:
            return {
                "sufficient_depth": False,
                "requested_size": order_size,
                "filled_size": 0.0,
                "remaining_size": order_size,
                "vwap": 0.0,
            }

        levels = self._extract_levels(orderbook, key="asks" if side in {"YES", "BUY", "LONG"} else "bids")
        if not levels:
            return {
                "sufficient_depth": False,
                "requested_size": order_size,
                "filled_size": 0.0,
                "remaining_size": order_size,
                "vwap": 0.0,
            }

        remaining = order_size
        filled = 0.0
        notional = 0.0
        for price, quantity in levels:
            if remaining <= 0.0:
                break
            take = min(remaining, quantity)
            if take <= 0.0:
                continue
            filled += take
            notional += take * price
            remaining -= take

        vwap = notional / filled if filled > 0.0 else 0.0
        return {
            "sufficient_depth": remaining <= 1e-9,
            "requested_size": order_size,
            "filled_size": filled,
            "remaining_size": max(remaining, 0.0),
            "vwap": vwap,
        }

    def _extract_levels(self, orderbook: dict[str, Any], *, key: str) -> list[tuple[float, float]]:
        raw_levels = orderbook.get(key, [])
        normalized: list[tuple[float, float]] = []
        for level in raw_levels:
            price: float | None = None
            quantity: float | None = None
            if isinstance(level, dict):
                raw_price = level.get("price")
                raw_quantity = level.get("size", level.get("quantity", level.get("amount", 0.0)))
            elif isinstance(level, (list, tuple)) and len(level) >= 2:
                raw_price = level[0]
                raw_quantity = level[1]
            else:
                continue
            try:
                price = float(raw_price)
                quantity = float(raw_quantity)
            except (TypeError, ValueError):
                continue
            if price <= 0.0 or quantity <= 0.0:
                continue
            normalized.append((price, quantity))

        if normalized:
            normalized.sort(key=lambda item: item[0], reverse=(key == "bids"))
            return normalized

        depth = orderbook.get("orderbook_depth_usd", orderbook.get("depth_usd", orderbook.get("liquidity_usd")))
        mid = orderbook.get("mid_price", orderbook.get("price", orderbook.get("best_ask", orderbook.get("best_bid"))))
        try:
            depth_value = float(depth)
            mid_price = float(mid)
        except (TypeError, ValueError):
            return []
        if depth_value <= 0.0 or mid_price <= 0.0:
            return []
        return [(mid_price, depth_value)]


def build_orderbook_snapshot_from_context(
    *,
    context: dict[str, Any] | None,
    market_price: float,
) -> dict[str, Any]:
    snapshot_source = context or {}
    explicit_snapshot = snapshot_source.get("orderbook")
    if isinstance(explicit_snapshot, dict):
        return dict(explicit_snapshot)

    spread = max(float(snapshot_source.get("spread", 0.0)), 0.0)
    best_bid = float(snapshot_source.get("best_bid", max(0.0, market_price - (spread / 2.0))))
    best_ask = float(snapshot_source.get("best_ask", min(1.0, market_price + (spread / 2.0))))
    depth = float(
        snapshot_source.get(
            "orderbook_depth_usd",
            snapshot_source.get("depth_usd", snapshot_source.get("liquidity_usd", 0.0)),
        )
    )
    now_ts = datetime.now(timezone.utc).timestamp()
    return {
        "timestamp": float(snapshot_source.get("orderbook_timestamp", now_ts)),
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid_price": max(min((best_bid + best_ask) / 2.0, 1.0), 0.0),
        "orderbook_depth_usd": max(depth, 0.0),
        "bids": [[best_bid, max(depth, 0.0)]],
        "asks": [[best_ask, max(depth, 0.0)]],
    }
