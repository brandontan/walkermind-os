"""PLAYBOOK external data-feed adapters.

Phase-1 is Polymarket-native only: native signals are computed directly from
orderbook / on-chain snapshots in ``signals.py``. Feed-dependent signals
(public flow, injury/news, historical team strength) require *external* data
sources (odds providers, injury feeds). Those are modelled here as a
``SportsFeed`` Protocol so a real adapter can be dropped in for V2 without
touching the router or modules.

``NullFeed`` is the Phase-1 default: it returns ``None`` for every lookup,
which callers interpret as "no external signal available" and fall back to a
neutral reading. This keeps Phase-1 free of any network dependency.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class InjuryEvent:
    """A confirmed injury / lineup / scratch event for a market's underlying."""

    market_id: str
    headline: str
    severity: float  # [0, 1] — impact on the outcome probability
    detected_ts_epoch: float  # unix seconds when the event was first observed


@dataclass(frozen=True)
class PublicFlow:
    """Public-betting flow snapshot for a market's underlying outcome."""

    market_id: str
    public_pct_on_side: float  # [0, 1] — share of public tickets on `side`
    side: str  # "YES" | "NO"


@runtime_checkable
class SportsFeed(Protocol):
    """External sports-data adapter contract.

    Implementations must be safe to call from async strategy code; they should
    never raise on a missing record — return ``None`` so the caller can fall
    back to a neutral reading. Real adapters (V2) wrap odds/injury APIs with
    retry + timeout + structured logging per the engineering standards.
    """

    async def get_injury_event(self, market_id: str) -> InjuryEvent | None:
        """Return the latest unrepriced injury event for the market, or None."""
        ...

    async def get_public_flow(self, market_id: str) -> PublicFlow | None:
        """Return the current public-flow snapshot for the market, or None."""
        ...

    async def get_model_probability(self, market_id: str, side: str) -> float | None:
        """Return a model/Elo win probability in [0, 1] for the side, or None."""
        ...


class NullFeed:
    """Default no-op feed for Phase-1 native-only operation.

    Every lookup returns ``None``. Conforms structurally to ``SportsFeed`` so
    it can be injected anywhere a feed is expected without a network call.
    """

    async def get_injury_event(self, market_id: str) -> InjuryEvent | None:
        return None

    async def get_public_flow(self, market_id: str) -> PublicFlow | None:
        return None

    async def get_model_probability(self, market_id: str, side: str) -> float | None:
        return None


__all__ = [
    "InjuryEvent",
    "PublicFlow",
    "SportsFeed",
    "NullFeed",
]
