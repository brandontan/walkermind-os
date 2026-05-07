"""SignalFollowingStrategy - operator-curated feed signal consumer.

Foundation contract (P3a):
    BaseStrategy.scan          - emit SignalCandidates from active feed
                                 publications (no HTTP, pure DB reads).
    BaseStrategy.evaluate_exit - close on operator-published exit triggers
                                 for the originating feed + market.
    BaseStrategy.default_tp_sl - TP 20% / SL 8%

Pipeline boundary (P3c scope):
    DATA -> [STRATEGY <-- this file] -> INTELLIGENCE -> RISK -> EXECUTION

This module never places orders, never touches the risk gate, never bypasses
activation guards. SignalCandidates returned from `scan()` are handed to the
downstream signal scan loop (P3d) which routes them through risk + execution.

Model:
    Operator publishes signals into `signal_feeds` via SignalFeedService.
    Users subscribe to feeds via /signals (Tier 2 gate). Per scan tick, the
    strategy reads `signal_publications` rows scoped to the user's currently
    active subscriptions. No HTTP fetches happen here - filter enforcement is
    best-effort over the publication payload.

Exit reason encoding:
    The foundation `ExitDecision` invariant pins `should_exit=True` to
    `reason="strategy_exit"`. The signal-driven sub-reason is preserved in
    `metadata["reason"] = "signal_exit_published"` so downstream telemetry can
    attribute closes to the feed publication without breaking the foundation
    contract.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from ....database import get_pool
from ....services.signal_feed.signal_evaluator import (
    evaluate_publications_for_user,
)
from ..base import BaseStrategy
from ..types import ExitDecision, MarketFilters, SignalCandidate, UserContext

logger = logging.getLogger(__name__)

DEFAULT_TP_PCT = 0.20
DEFAULT_SL_PCT = 0.08


class SignalFollowingStrategy(BaseStrategy):
    """Subscribe-and-mirror strategy over operator-curated feeds.

    Per-user state lives in `user_signal_subscriptions` (max 5 active rows
    enforced at the Telegram handler boundary). Per-publication-per-user
    dedup is the responsibility of the downstream scan loop (P3d) - this
    strategy emits one SignalCandidate per publication that survives the
    filter envelope.
    """

    name = "signal_following"
    version = "1.0.0"
    risk_profile_compatibility = ["conservative", "balanced", "aggressive"]

    def default_tp_sl(self) -> tuple[float, float]:
        return (DEFAULT_TP_PCT, DEFAULT_SL_PCT)

    async def scan(
        self,
        market_filters: MarketFilters,
        user_context: UserContext,
    ) -> list[SignalCandidate]:
        """Emit SignalCandidates for the user's active feed subscriptions.

        Delegates the DB read + filter + scoring pipeline to
        `signal_evaluator.evaluate_publications_for_user` so the strategy
        class stays focused on the BaseStrategy contract. A scan failure
        for any reason (DB unavailable, malformed payload, etc.) returns
        an empty list rather than raising - the scheduler must not be able
        to crash the whole user's scan loop on a single bad publication.
        """
        try:
            return await evaluate_publications_for_user(
                user_context=user_context,
                market_filters=market_filters,
                strategy_name=self.name,
            )
        except Exception as exc:
            logger.warning(
                "signal_following scan failed user=%s err=%s",
                user_context.user_id, exc,
            )
            return []

    async def evaluate_exit(self, position: dict) -> ExitDecision:
        """Close when the originating feed publishes an exit trigger.

        Encoding (foundation contract):
            * exit published   -> should_exit=True,  reason='strategy_exit',
                                  metadata['reason']='signal_exit_published'
            * still active     -> should_exit=False, reason='hold'
            * unknown linkage  -> should_exit=False, reason='hold'

        Two trigger forms are honoured:
            (a) the originating publication row has exit_published_at set
                (operator retired the entry signal in place), OR
            (b) a publication on the same feed + market_id has
                exit_signal = TRUE AND published_at strictly later than the
                anchor (origin publication's published_at, or position
                opened_at as fallback).

        Re-entry safety: bounding (b) by ``published_at > anchor`` prevents
        a stale exit_signal row from a previous trade cycle from retiring a
        fresh re-entry on the same market. If neither origin publication
        nor a position timestamp is available, the evaluator holds — it
        cannot distinguish stale from fresh exits without an anchor.
        """
        meta = position.get("metadata") or {}
        feed_uuid = _coerce_uuid(meta.get("feed_id"))
        publication_uuid = _coerce_uuid(meta.get("publication_id"))
        market_id = meta.get("market_id") or position.get("market_id")
        if feed_uuid is None or not market_id:
            return ExitDecision(should_exit=False, reason="hold")

        try:
            pool = get_pool()
            async with pool.acquire() as conn:
                anchor: datetime | None = None
                if publication_uuid is not None:
                    origin = await conn.fetchrow(
                        """
                        SELECT published_at, exit_published_at
                          FROM signal_publications
                         WHERE id = $1 AND feed_id = $2
                        """,
                        publication_uuid, feed_uuid,
                    )
                    if origin is not None:
                        if origin["exit_published_at"] is not None:
                            return _exit_decision(feed_uuid)
                        anchor = origin["published_at"]

                if anchor is None:
                    anchor = _coerce_dt(
                        position.get("opened_at")
                        or position.get("created_at"),
                    )
                if anchor is None:
                    return ExitDecision(should_exit=False, reason="hold")

                row = await conn.fetchrow(
                    """
                    SELECT 1
                      FROM signal_publications
                     WHERE feed_id = $1
                       AND market_id = $2
                       AND exit_signal = TRUE
                       AND published_at > $3
                     LIMIT 1
                    """,
                    feed_uuid, str(market_id), anchor,
                )
        except Exception as exc:
            # DB hiccup must not flip a position to exit. Hold and let the
            # platform-level exit watcher retry on its next tick.
            logger.warning(
                "signal_following evaluate_exit query failed feed=%s err=%s",
                feed_uuid, exc,
            )
            return ExitDecision(should_exit=False, reason="hold")

        if row is None:
            return ExitDecision(should_exit=False, reason="hold")
        return _exit_decision(feed_uuid)


def _exit_decision(feed_uuid: UUID) -> ExitDecision:
    return ExitDecision(
        should_exit=True,
        reason="strategy_exit",
        metadata={
            "reason": "signal_exit_published",
            "feed_id": str(feed_uuid),
        },
    )


def _coerce_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return None


def _coerce_uuid(value: Any) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


__all__ = ["SignalFollowingStrategy"]
