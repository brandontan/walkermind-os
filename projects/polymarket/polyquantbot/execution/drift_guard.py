from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DriftGuardResult:
    allowed: bool
    reason: str | None = None
    details: dict[str, Any] | None = None


class ExecutionDriftGuard:
    """Fail-closed execution-boundary drift and liquidity validator."""

    def __init__(
        self,
        *,
        max_price_deviation_ratio: float = 0.05,
        max_vwap_slippage_ratio: float = 0.02,
    ) -> None:
        self._max_price_deviation_ratio = float(max_price_deviation_ratio)
        self._max_vwap_slippage_ratio = float(max_vwap_slippage_ratio)

    def validate(
        self,
        *,
        side: str,
        validated_price: float,
        execution_price: float,
        size: float,
        market_data: dict[str, Any] | None,
    ) -> DriftGuardResult:
        normalized_side = str(side).strip().upper()
        boundary = dict(market_data or {})

        if execution_price <= 0 or validated_price <= 0:
            return DriftGuardResult(
                allowed=False,
                reason="price_deviation",
                details={
                    "error": "non_positive_price",
                    "validated_price": validated_price,
                    "execution_price": execution_price,
                },
            )

        price_deviation_ratio = abs(execution_price - validated_price) / max(validated_price, 1e-12)
        if price_deviation_ratio > self._max_price_deviation_ratio:
            return DriftGuardResult(
                allowed=False,
                reason="price_deviation",
                details={
                    "validated_price": validated_price,
                    "execution_price": execution_price,
                    "price_deviation_ratio": price_deviation_ratio,
                    "threshold": self._max_price_deviation_ratio,
                },
            )

        model_probability = boundary.get("model_probability")
        if model_probability is None:
            model_probability = boundary.get("signal_probability")
        if model_probability is None:
            model_probability = boundary.get("predicted_probability")
        if model_probability is None:
            model_probability = 0.5

        executable_price = boundary.get("reference_price", execution_price)
        try:
            p_model = float(model_probability)
            p_exec = float(executable_price)
        except (TypeError, ValueError):
            return DriftGuardResult(
                allowed=False,
                reason="ev_negative",
                details={"error": "invalid_boundary_probability_or_price"},
            )
        if p_exec <= 0 or p_exec >= 1:
            return DriftGuardResult(
                allowed=False,
                reason="ev_negative",
                details={"error": "invalid_executable_price", "reference_price": p_exec},
            )

        ev_new = self._compute_binary_ev(side=normalized_side, model_probability=p_model, executable_price=p_exec)
        if ev_new <= 0:
            return DriftGuardResult(
                allowed=False,
                reason="ev_negative",
                details={
                    "ev_new": ev_new,
                    "model_probability": p_model,
                    "reference_price": p_exec,
                },
            )

        book = boundary.get("orderbook")
        if not isinstance(book, dict):
            return DriftGuardResult(
                allowed=False,
                reason="liquidity_insufficient",
                details={"error": "orderbook_missing_or_invalid"},
            )

        levels = self._extract_levels(book=book, side=normalized_side)
        if not levels:
            return DriftGuardResult(
                allowed=False,
                reason="liquidity_insufficient",
                details={"error": "orderbook_empty"},
            )

        simulated = self._simulate_vwap(levels=levels, notional=size)
        if simulated is None:
            return DriftGuardResult(
                allowed=False,
                reason="liquidity_insufficient",
                details={"error": "insufficient_depth", "required_size": size},
            )

        slippage_ratio = abs(simulated - execution_price) / max(execution_price, 1e-12)
        if slippage_ratio > self._max_vwap_slippage_ratio:
            return DriftGuardResult(
                allowed=False,
                reason="liquidity_insufficient",
                details={
                    "error": "slippage_ratio_exceeded",
                    "vwap": simulated,
                    "execution_price": execution_price,
                    "slippage_ratio": slippage_ratio,
                    "threshold": self._max_vwap_slippage_ratio,
                },
            )

        return DriftGuardResult(
            allowed=True,
            details={
                "ev_new": ev_new,
                "vwap": simulated,
                "slippage_ratio": slippage_ratio,
                "price_deviation_ratio": price_deviation_ratio,
            },
        )

    @staticmethod
    def _compute_binary_ev(*, side: str, model_probability: float, executable_price: float) -> float:
        p = min(max(model_probability, 1e-9), 1.0 - 1e-9)
        if side == "NO":
            p = 1.0 - p
        b = (1.0 - executable_price) / executable_price
        return (p * b) - (1.0 - p)

    @staticmethod
    def _extract_levels(*, book: dict[str, Any], side: str) -> list[tuple[float, float]]:
        preferred_key = "asks" if side == "YES" else "bids"
        raw_levels = book.get(preferred_key)
        if raw_levels is None:
            raw_levels = book.get("levels")
        if not isinstance(raw_levels, list):
            return []

        normalized: list[tuple[float, float]] = []
        for level in raw_levels:
            if isinstance(level, dict):
                price_raw = level.get("price")
                size_raw = level.get("size")
            elif isinstance(level, (list, tuple)) and len(level) >= 2:
                price_raw = level[0]
                size_raw = level[1]
            else:
                continue
            try:
                level_price = float(price_raw)
                level_size = float(size_raw)
            except (TypeError, ValueError):
                continue
            if level_price <= 0 or level_size <= 0:
                continue
            normalized.append((level_price, level_size))
        return normalized

    @staticmethod
    def _simulate_vwap(*, levels: list[tuple[float, float]], notional: float) -> float | None:
        if notional <= 0:
            return None
        remaining = float(notional)
        cost = 0.0
        for level_price, level_size in levels:
            take = min(remaining, level_size)
            if take <= 0:
                continue
            cost += level_price * take
            remaining -= take
            if remaining <= 1e-9:
                break
        if remaining > 1e-9:
            return None
        return cost / notional
