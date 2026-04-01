"""ConflictResolver — detects and resolves conflicting multi-strategy signals.

Logic:
  - If signals contain BOTH 'YES' and 'NO' for the same market_id → CONFLICT → return None (SKIP)
  - Otherwise → pass forward unchanged

Usage::

    from projects.polymarket.polyquantbot.strategy.conflict_resolver import ConflictResolver

    resolver = ConflictResolver()
    resolved = resolver.resolve(signals)
    if resolved is None:
        # conflict detected — skip this tick
        ...
    stats = resolver.stats()
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

import structlog

from .base.base_strategy import SignalResult

log = structlog.get_logger(__name__)


# ── Stats type ────────────────────────────────────────────────────────────────


@dataclass
class ConflictStats:
    """Lifetime statistics for a :class:`ConflictResolver` instance.

    Attributes:
        total_checked: Total resolve() calls made.
        conflicts: Number of calls that returned None (conflict detected).
        passed: Number of calls that returned a signal list unchanged.
    """

    total_checked: int = 0
    conflicts: int = 0
    passed: int = 0


# ── ConflictResolver ─────────────────────────────────────────────────────────


class ConflictResolver:
    """Detects and resolves conflicting multi-strategy signals.

    A conflict is defined as: two or more signals targeting the **same
    ``market_id``** but on **opposing sides** (one 'YES' and one 'NO').
    When a conflict is detected the entire signal list is discarded and
    ``resolve()`` returns ``None``, signalling the caller to skip execution
    for that tick.

    Signals for different markets never conflict with each other.

    Args:
        None — stateless except for lifetime statistics counters.
    """

    def __init__(self) -> None:
        self._stats = ConflictStats()

    # ── Public API ────────────────────────────────────────────────────────────

    def resolve(
        self,
        signals: List[SignalResult],
    ) -> Optional[List[SignalResult]]:
        """Check *signals* for intra-market YES/NO conflict.

        For each unique ``market_id`` present in *signals*, this method checks
        whether the signal set contains at least one 'YES' **and** at least one
        'NO' signal.  If such a conflict exists for **any** market, the entire
        batch is rejected.

        An empty signal list is considered conflict-free and returned as-is
        (empty list, not None).

        Args:
            signals: List of :class:`SignalResult` objects from the router.

        Returns:
            The original *signals* list if no conflict is detected, or
            ``None`` if a YES/NO conflict exists for any market.
        """
        self._stats.total_checked += 1

        if not signals:
            self._stats.passed += 1
            log.debug("conflict_resolver.empty_signals")
            return signals

        # Group sides by market_id
        sides_by_market: Dict[str, Set[str]] = {}
        for sig in signals:
            market_sides = sides_by_market.setdefault(sig.market_id, set())
            market_sides.add(sig.side.upper())

        # Detect conflict: same market has both YES and NO
        for market_id, sides in sides_by_market.items():
            if "YES" in sides and "NO" in sides:
                self._stats.conflicts += 1
                log.info(
                    "conflict_resolver.conflict_detected",
                    market_id=market_id,
                    total_signals=len(signals),
                    conflicts_lifetime=self._stats.conflicts,
                )
                return None

        self._stats.passed += 1
        log.debug(
            "conflict_resolver.passed",
            total_signals=len(signals),
            markets=list(sides_by_market.keys()),
        )
        return signals

    def stats(self) -> ConflictStats:
        """Return a snapshot of lifetime resolver statistics.

        Returns:
            :class:`ConflictStats` with total_checked, conflicts, passed counts.
        """
        return ConflictStats(
            total_checked=self._stats.total_checked,
            conflicts=self._stats.conflicts,
            passed=self._stats.passed,
        )

    def __repr__(self) -> str:
        s = self._stats
        return (
            f"<ConflictResolver checked={s.total_checked} "
            f"conflicts={s.conflicts} passed={s.passed}>"
        )
