"""SignalFeedService + signal_evaluator package (P3c).

Public surface:
    create_feed / publish_signal / publish_exit / subscribe / unsubscribe
    list_user_subscriptions / get_feed_by_slug / list_active_feeds
    evaluate_publications_for_user (consumed by SignalFollowingStrategy.scan)
"""

from .signal_evaluator import (
    DEFAULT_CONFIDENCE,
    DEFAULT_TRADE_SIZE_USDC,
    MIN_TRADE_SIZE_USDC,
    evaluate_publications_for_user,
)
from .signal_feed_service import (
    MAX_SUBSCRIPTIONS_PER_USER,
    VALID_FEED_STATUSES,
    VALID_PUBLICATION_SIDES,
    create_feed,
    get_feed_by_slug,
    list_active_feeds,
    list_user_subscriptions,
    publish_exit,
    publish_signal,
    subscribe,
    unsubscribe,
)

__all__ = [
    "MAX_SUBSCRIPTIONS_PER_USER",
    "VALID_FEED_STATUSES",
    "VALID_PUBLICATION_SIDES",
    "DEFAULT_CONFIDENCE",
    "DEFAULT_TRADE_SIZE_USDC",
    "MIN_TRADE_SIZE_USDC",
    "create_feed",
    "publish_signal",
    "publish_exit",
    "subscribe",
    "unsubscribe",
    "list_user_subscriptions",
    "get_feed_by_slug",
    "list_active_feeds",
    "evaluate_publications_for_user",
]
