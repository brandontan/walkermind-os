"""strategy.market_classifier — shadow-only market type classification."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class MarketClassifier:
    """Classifies markets into broad observable market types.

    Classification is designed for telemetry only and never mutates trading
    decisions, filtering, or execution behavior.
    """

    def _to_float(self, value: Any) -> float | None:
        """Best-effort float conversion with ``None`` fallback."""
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _days_to_expiry(self, expiry: Any) -> float | None:
        """Return days until expiry, or ``None`` when parsing fails."""
        if expiry is None:
            return None

        try:
            if isinstance(expiry, (int, float)):
                expiry_dt = datetime.fromtimestamp(float(expiry), tz=timezone.utc)
            elif isinstance(expiry, str):
                normalized = expiry.replace("Z", "+00:00")
                expiry_dt = datetime.fromisoformat(normalized)
                if expiry_dt.tzinfo is None:
                    expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
                else:
                    expiry_dt = expiry_dt.astimezone(timezone.utc)
            elif isinstance(expiry, datetime):
                expiry_dt = expiry if expiry.tzinfo else expiry.replace(tzinfo=timezone.utc)
                expiry_dt = expiry_dt.astimezone(timezone.utc)
            else:
                return None

            now = datetime.now(timezone.utc)
            delta = expiry_dt - now
            return delta.total_seconds() / 86400.0
        except (TypeError, ValueError, OSError):
            return None

    def classify(self, market: dict[str, Any]) -> dict[str, Any]:
        """Classify a market into type + tags with safe fallbacks."""
        tags: list[str] = []

        price_yes = self._to_float(market.get("price_yes"))
        volume_24h = self._to_float(market.get("volume_24h"))
        days_to_expiry = self._days_to_expiry(market.get("expiry"))

        if price_yes is not None and (price_yes >= 0.95 or price_yes <= 0.05):
            tags.append("BONDS")

        if volume_24h is not None and volume_24h > 500_000:
            tags.append("HIGH_LIQUIDITY")

        if days_to_expiry is not None and days_to_expiry <= 7:
            tags.append("SHORT_TERM")

        if days_to_expiry is not None and days_to_expiry > 30:
            tags.append("LONG_TERM")

        if "BONDS" in tags:
            market_type = "BONDS"
        elif "HIGH_LIQUIDITY" in tags:
            market_type = "HIGH_LIQUIDITY"
        elif "SHORT_TERM" in tags:
            market_type = "SHORT_TERM"
        elif "LONG_TERM" in tags:
            market_type = "LONG_TERM"
        else:
            market_type = "GENERAL"

        return {
            "type": market_type,
            "tags": tags,
        }
