from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Optional


@dataclass(frozen=True)
class TradeTrace:
    position_id: str
    market_id: str
    entry_price: float
    exit_price: float
    size: float
    pnl: float
    intelligence_score: float
    intelligence_reasons: List[str]
    decision_threshold: float
    action: str  # "OPEN" or "CLOSE"
    timestamp: datetime


class TradeTraceEngine:
    def __init__(self):
        self._traces: List[TradeTrace] = []

    def record_trace(
        self,
        position_id: str,
        market_id: str,
        entry_price: float,
        exit_price: float,
        size: float,
        pnl: float,
        intelligence_score: float,
        intelligence_reasons: List[str],
        decision_threshold: float,
        action: str,
    ) -> None:
        """Record a trade trace."""
        self._traces.append(
            TradeTrace(
                position_id=position_id,
                market_id=market_id,
                entry_price=entry_price,
                exit_price=exit_price,
                size=size,
                pnl=pnl,
                intelligence_score=intelligence_score,
                intelligence_reasons=intelligence_reasons,
                decision_threshold=decision_threshold,
                action=action,
                timestamp=datetime.utcnow(),
            )
        )

    def get_traces(self) -> List[TradeTrace]:
        """Retrieve all trade traces."""
        return self._traces

    def get_trace_by_position_id(self, position_id: str) -> Optional[TradeTrace]:
        """Retrieve a trace by position ID."""
        return next((t for t in self._traces if t.position_id == position_id), None)