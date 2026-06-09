"""PLAYBOOK correlation engine.

Prevents duplicate exposure to the same underlying risk. On one event, a team
moneyline, a series-winner market, and a correlated player prop are largely the
*same* bet; sizing them independently would multiply exposure on one outcome.

This module derives a stable ``cluster_key`` per market's underlying event and
scores correlation between markets. The key is attached to each emitted
``SignalCandidate`` (metadata) so the existing risk-gate exposure check
(``MAX_CORRELATED_EXPOSURE`` aggregate cap, gate step 8) can treat correlated
legs as one cluster. This *layers on top of* the gate — it introduces no new
risk authority.

Pure functions — no DB, no async.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Per-event sub-cap: fraction of capital allowed on a single cluster_key. Tighter
# than the aggregate MAX_CORRELATED_EXPOSURE so one game cannot dominate the book
# even when total exposure is within bounds. Config-tunable in a later lane.
EVENT_CLUSTER_CAP_PCT: float = 0.15

_SLUG_SANITIZE = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    """Lowercase + collapse non-alphanumerics to single hyphens; trim."""
    return _SLUG_SANITIZE.sub("-", (text or "").lower()).strip("-")


def cluster_key(
    *,
    sport: str,
    event_id: str = "",
    event_date: str = "",
    home: str = "",
    away: str = "",
) -> str:
    """Build a deterministic cluster key for a market's underlying event.

    Prefers an explicit ``event_id`` when available (most reliable). Otherwise
    falls back to ``sport:date:away@home`` with team names normalised so the
    two legs of the same game collapse to one key. Returns ``"unclustered"``
    when there is not enough information to group safely (each such market is
    then treated as its own cluster by the caller).
    """
    sport_s = _slug(sport)
    if event_id:
        return f"{sport_s}:{_slug(event_id)}"
    if home or away:
        return f"{sport_s}:{_slug(event_date)}:{_slug(away)}@{_slug(home)}"
    return "unclustered"


@dataclass(frozen=True)
class CorrelationResult:
    """Correlation verdict between two markets.

    ``score`` in [0, 1]; ``correlated`` is True when the score meets the
    threshold and the two should be treated as one exposure unit.
    """

    score: float
    correlated: bool
    shared_key: str | None = None


def score_correlation(
    key_a: str,
    key_b: str,
    *,
    threshold: float = 0.99,
) -> CorrelationResult:
    """Score correlation between two cluster keys.

    Phase-1 uses exact-key matching: two markets on the same underlying event
    (identical, non-``unclustered`` key) score 1.0 and are correlated; anything
    else scores 0.0. Richer scoring (partial overlap, prop-vs-ML weighting) is
    a V2 refinement, but the interface is stable so modules need not change.
    """
    if key_a and key_a == key_b and key_a != "unclustered":
        return CorrelationResult(score=1.0, correlated=True, shared_key=key_a)
    return CorrelationResult(score=0.0, correlated=False, shared_key=None)


__all__ = [
    "CorrelationResult",
    "cluster_key",
    "score_correlation",
    "EVENT_CLUSTER_CAP_PCT",
]
