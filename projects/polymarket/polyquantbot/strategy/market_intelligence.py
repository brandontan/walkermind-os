"""strategy.market_intelligence — shadow-only market intelligence analysis."""

from __future__ import annotations

from typing import Any

from .market_classifier import MarketClassifier


class MarketIntelligenceEngine:
    """Builds observational market intelligence payloads for logging/snapshots."""

    def __init__(self, classifier: MarketClassifier | None = None) -> None:
        self._classifier = classifier or MarketClassifier()

    def _to_float(self, value: Any) -> float | None:
        """Best-effort float conversion with ``None`` fallback."""
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def analyze(self, market: dict[str, Any], signal: dict[str, Any] | None = None) -> dict[str, Any]:
        """Analyze a market and return shadow-only intelligence metadata."""
        classified = self._classifier.classify(market if isinstance(market, dict) else {})

        confidence = self._to_float((signal or {}).get("confidence")) if signal else None
        result: dict[str, Any] = {
            "market_type": classified["type"],
            "tags": classified["tags"],
            "signal_present": signal is not None,
        }
        if confidence is not None:
            result["confidence"] = confidence
        return result
