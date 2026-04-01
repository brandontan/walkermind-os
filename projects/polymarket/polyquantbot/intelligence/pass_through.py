"""
Intelligence layer — pass-through stub.

Current: returns signal unchanged (confidence = 1.0).
Future: Bayesian confidence adjustment, ML model inference, drift detection.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import structlog

log = structlog.get_logger(__name__)


@dataclass
class IntelligenceContext:
    """Confidence-adjusted signal output from the intelligence layer."""

    market_id: str
    edge: float
    confidence: float  # 0.0–1.0, multiplied against strategy edge
    adjusted_edge: float  # edge * confidence
    source: str = "pass_through"


class IntelligenceLayer:
    """
    Pass-through intelligence layer.

    Currently returns all signals with confidence=1.0.
    Replace with Bayesian/ML models in Phase 11+.
    """

    async def evaluate(
        self,
        market_id: str,
        raw_edge: float,
    ) -> Optional[IntelligenceContext]:
        """
        Evaluate intelligence context for a signal.

        Args:
            market_id: Market being evaluated.
            raw_edge: Edge from strategy layer.

        Returns:
            IntelligenceContext with confidence-adjusted edge.
        """
        if raw_edge <= 0.0:
            return None

        ctx = IntelligenceContext(
            market_id=market_id,
            edge=raw_edge,
            confidence=1.0,
            adjusted_edge=raw_edge,
            source="pass_through",
        )
        log.debug("intelligence.pass_through", market_id=market_id, edge=raw_edge)
        return ctx
