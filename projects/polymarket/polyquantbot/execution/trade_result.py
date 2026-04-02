"""TradeResult — canonical model for a completed trade outcome.

Produced by the execution layer after a fill (real or paper) and consumed by:
    - MultiStrategyMetrics  (win/loss, PnL, trade_count)
    - DynamicCapitalAllocator  (weight recomputation via live metrics)
    - FeedbackLoop  (orchestrator that wires the above together)

Fields
------
strategy_id : str
    Strategy that generated the signal (e.g. "ev_momentum").
market_id : str
    Polymarket condition ID.
side : str
    "YES" or "NO".
price : float
    Requested / expected entry price.
size : float
    Order size in USD.
pnl : float
    Realised or estimated profit/loss in USD.
    At fill time this is an *estimate*:
        paper  → size * expected_ev
        live   → size * expected_ev  (resolved PnL unknown until market settles)
    Callers may update this field once the market resolves.
expected_ev : float
    Expected value per USD as predicted by the signal (e.g. 0.08 = 8 cents / $1).
timestamp : datetime
    UTC datetime of fill confirmation.
trade_id : str
    Stable unique identifier used for idempotency deduplication.
    Defaults to a new UUID4 but SHOULD be set to the exchange order_id when
    available so that re-processing the same fill never double-counts.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class TradeResult:
    """Outcome of a single executed trade.

    This is the canonical object that flows through the feedback loop:
    execution → metrics → allocator.

    Idempotency guarantee
    ---------------------
    ``trade_id`` is used as a dedup key inside :class:`MultiStrategyMetrics`
    and :class:`FeedbackLoop`.  Set it to the exchange ``order_id`` (available
    in :class:`ExecutionResult`) to ensure that replaying the same fill does
    not inflate counters.
    """

    strategy_id: str
    market_id: str
    side: str          # "YES" | "NO"
    price: float
    size: float
    pnl: float
    expected_ev: float
    timestamp: datetime
    trade_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # ── Derived helpers ───────────────────────────────────────────────────────

    @property
    def won(self) -> bool:
        """True when PnL is positive, or — when PnL is unknown (0.0) — when
        expected_ev is positive (strategy predicted a profitable trade)."""
        if self.pnl != 0.0:
            return self.pnl > 0.0
        return self.expected_ev > 0.0

    # ── Factory helpers ───────────────────────────────────────────────────────

    @classmethod
    def from_execution(
        cls,
        strategy_id: str,
        market_id: str,
        side: str,
        price: float,
        size: float,
        filled_size: float,
        avg_fill_price: float,
        expected_ev: float,
        order_id: str = "",
    ) -> "TradeResult":
        """Build a TradeResult from execution-layer data.

        PnL is estimated as ``filled_size * expected_ev`` — a proxy for the
        expected profit given the model's EV prediction.  Callers may overwrite
        ``pnl`` when the market resolves and the true outcome is known.

        Args:
            strategy_id: Originating strategy name.
            market_id:   Polymarket condition ID.
            side:        "YES" | "NO".
            price:       Requested limit price.
            size:        Requested order size in USD.
            filled_size: Actual filled size in USD (0.0 on paper).
            avg_fill_price: Volume-weighted average fill price.
            expected_ev: Signal's expected value per USD.
            order_id:    Exchange order ID (used as trade_id when provided).

        Returns:
            :class:`TradeResult` with estimated PnL.
        """
        effective_size = filled_size if filled_size > 0.0 else size
        estimated_pnl = round(effective_size * expected_ev, 6)

        return cls(
            strategy_id=strategy_id,
            market_id=market_id,
            side=side,
            price=price,
            size=size,
            pnl=estimated_pnl,
            expected_ev=expected_ev,
            timestamp=datetime.now(timezone.utc),
            trade_id=order_id if order_id else str(uuid.uuid4()),
        )

    def to_dict(self) -> dict:
        """Serialise to a plain dict for structured logging / JSON output."""
        return {
            "trade_id": self.trade_id,
            "strategy_id": self.strategy_id,
            "market_id": self.market_id,
            "side": self.side,
            "price": self.price,
            "size": self.size,
            "pnl": round(self.pnl, 6),
            "expected_ev": round(self.expected_ev, 6),
            "won": self.won,
            "timestamp": self.timestamp.isoformat(),
        }
