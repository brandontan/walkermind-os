"""PLAYBOOK — autonomous sports-market orchestration engine.

PLAYBOOK is a *strategy router*, not a strategy (the sports equivalent of
SMART STRIKE / ``candle_auto``). It evaluates each sports market through a
Market Quality Filter, computes a bundle of signal readings, and routes the
market to the highest-EV sports module via a precedence-claim router. The
selected module emits a standard ``SignalCandidate`` consumed by the existing
risk gate and execution router — PLAYBOOK adds no new risk or execution
authority.

Foundation-only package: no DB access, no execution, no risk evaluation here.
See ``docs/blueprint/playbook.md`` for the full design.
"""
from __future__ import annotations

from .correlation import CorrelationResult, cluster_key, score_correlation
from .feeds import NullFeed, SportsFeed
from .market_quality import MarketQualityResult, evaluate_market_quality
from .modules import (
    ClosingEdgeModule,
    InjuryAlphaModule,
    ModuleDecision,
    PlaybookModule,
    PublicFadeModule,
    SharpMoneyModule,
)
from .router import PlaybookRouter, RouteResult
from .signals import SignalBundle, SignalReading, compute_signal_bundle

__all__ = [
    # market quality
    "MarketQualityResult",
    "evaluate_market_quality",
    # signals
    "SignalReading",
    "SignalBundle",
    "compute_signal_bundle",
    # feeds
    "SportsFeed",
    "NullFeed",
    # correlation
    "CorrelationResult",
    "cluster_key",
    "score_correlation",
    # modules
    "PlaybookModule",
    "ModuleDecision",
    "ClosingEdgeModule",
    "SharpMoneyModule",
    "PublicFadeModule",
    "InjuryAlphaModule",
    # router
    "PlaybookRouter",
    "RouteResult",
]
