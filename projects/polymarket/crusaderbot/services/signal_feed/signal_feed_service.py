"""SignalFeedService — operator + user surface over the P3c persistence layer.

Idempotent ops on `signal_feeds`, `signal_publications`,
`user_signal_subscriptions`. The strategy plane reads via
`signal_evaluator.evaluate_publications_for_user`; this module is the write
surface (operators publishing) plus the user subscription state.

No HTTP. No execution path. No risk gate touched. Pure DB.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any
from uuid import UUID

from ...database import get_pool

logger = logging.getLogger(__name__)

MAX_SUBSCRIPTIONS_PER_USER = 5
# Slugs are capped so the inline-keyboard callback_data
# ("signals:off:<slug>" — 12-byte prefix) stays under Telegram's 64-byte
# limit. Migration column is VARCHAR(60); the app contract is the tighter
# 50-char cap enforced here. ASCII-only character class keeps the
# 50-char cap aligned with the 50-byte ceiling implied above.
MAX_SLUG_LEN = 50
# Single source of truth for the slug contract. The /signals Telegram
# handler imports this pattern so operator-created feeds are guaranteed
# to be addressable from the bot — the handler accepts whatever the
# service produces, never more.
SLUG_PATTERN = r"^[a-z0-9][a-z0-9_-]{1,49}$"
_SLUG_RE = re.compile(SLUG_PATTERN)
VALID_FEED_STATUSES: tuple[str, ...] = ("active", "paused", "archived")
VALID_PUBLICATION_SIDES: tuple[str, ...] = ("YES", "NO")


def _coerce_uuid(value: Any) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _payload_json(payload: dict[str, Any] | None) -> str:
    return json.dumps(payload or {})


async def _assert_feed_active(conn, feed_id: UUID) -> None:
    """Raise ValueError unless ``signal_feeds.status = 'active'``.

    Honours the migration contract: feed status gates both new
    publications AND new subscriptions. Without this guard, a paused or
    archived feed could accumulate publications that would be emitted
    once the feed is reactivated to subscribers whose ``subscribed_at``
    predates the pause window.
    """
    row = await conn.fetchrow(
        "SELECT status FROM signal_feeds WHERE id = $1",
        feed_id,
    )
    if row is None:
        raise ValueError(f"feed_id {feed_id} is not registered")
    if row["status"] != "active":
        raise ValueError(
            f"feed_id {feed_id} is not active "
            f"(status={row['status']!r}); cannot publish",
        )


# ---------------------------------------------------------------------------
# Feed operator surface — idempotent.
# ---------------------------------------------------------------------------


async def create_feed(
    *,
    name: str,
    slug: str,
    operator_id: UUID | str,
    description: str | None = None,
) -> dict[str, Any]:
    """Create or fetch a signal feed by slug.

    Idempotent on slug — re-calling with the same slug returns the existing
    feed without UPDATE so operator scripts can safely re-run. The slug is
    the stable user-facing identifier; the UUID id is the FK target for
    publications + subscriptions.
    """
    if not name:
        raise ValueError("create_feed requires non-empty name")
    if not slug:
        raise ValueError("create_feed requires non-empty slug")
    if not _SLUG_RE.match(slug):
        # The regex caps length at 50 (chars == bytes for ASCII), enforces
        # lowercase, and rejects punctuation outside `_-`. Operators are
        # expected to provide canonical slugs; the handler's lookups never
        # uppercase or accept non-ASCII, so admitting non-conforming slugs
        # at the service layer would persist feeds the bot cannot address.
        raise ValueError(
            f"create_feed slug must match {SLUG_PATTERN} "
            f"(2-{MAX_SLUG_LEN} ASCII lowercase chars, optional `_-`), "
            f"got {slug!r}",
        )
    op_uuid = _coerce_uuid(operator_id)
    if op_uuid is None:
        raise ValueError(
            f"create_feed operator_id must be UUID-coercible, got {operator_id!r}",
        )

    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id, name, slug, operator_id, status, description, "
            "       subscriber_count, created_at, updated_at "
            "  FROM signal_feeds WHERE slug = $1",
            slug,
        )
        if existing is not None:
            return dict(existing)
        row = await conn.fetchrow(
            """
            INSERT INTO signal_feeds (name, slug, operator_id, description)
            VALUES ($1, $2, $3, $4)
            RETURNING id, name, slug, operator_id, status, description,
                      subscriber_count, created_at, updated_at
            """,
            name, slug, op_uuid, description,
        )
        return dict(row)


async def publish_signal(
    *,
    feed_id: UUID | str,
    market_id: str,
    side: str,
    target_price: float | None = None,
    signal_type: str = "entry",
    payload: dict[str, Any] | None = None,
    expires_at: datetime | None = None,
) -> dict[str, Any]:
    """Insert an entry-side publication. exit_signal=FALSE."""
    fuid = _coerce_uuid(feed_id)
    if fuid is None:
        raise ValueError(
            f"publish_signal feed_id must be UUID-coercible, got {feed_id!r}",
        )
    if not market_id:
        raise ValueError("publish_signal market_id must be non-empty")
    side_norm = (side or "").upper()
    if side_norm not in VALID_PUBLICATION_SIDES:
        raise ValueError(
            f"publish_signal side must be in {VALID_PUBLICATION_SIDES}, "
            f"got {side!r}",
        )

    pool = get_pool()
    async with pool.acquire() as conn:
        await _assert_feed_active(conn, fuid)
        row = await conn.fetchrow(
            """
            INSERT INTO signal_publications
              (feed_id, market_id, side, target_price, signal_type, payload,
               exit_signal, expires_at)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, FALSE, $7)
            RETURNING id, feed_id, market_id, side, target_price,
                      signal_type, payload, exit_signal, published_at,
                      expires_at, exit_published_at
            """,
            fuid, market_id, side_norm, target_price, signal_type,
            _payload_json(payload), expires_at,
        )
        return dict(row)


async def publish_exit(
    *,
    feed_id: UUID | str,
    market_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Insert an exit-side publication. exit_signal=TRUE.

    Operators may also retire an existing entry by updating
    `signal_publications.exit_published_at` directly; this helper is for the
    cleaner 'announce a separate exit row' pattern.
    """
    fuid = _coerce_uuid(feed_id)
    if fuid is None:
        raise ValueError(
            f"publish_exit feed_id must be UUID-coercible, got {feed_id!r}",
        )
    if not market_id:
        raise ValueError("publish_exit market_id must be non-empty")

    pool = get_pool()
    async with pool.acquire() as conn:
        await _assert_feed_active(conn, fuid)
        row = await conn.fetchrow(
            """
            INSERT INTO signal_publications
              (feed_id, market_id, side, signal_type, payload, exit_signal)
            VALUES ($1, $2, 'YES', 'exit', $3::jsonb, TRUE)
            RETURNING id, feed_id, market_id, side, signal_type, payload,
                      exit_signal, published_at, expires_at, exit_published_at
            """,
            fuid, market_id, _payload_json(payload),
        )
        return dict(row)


# ---------------------------------------------------------------------------
# User subscription surface.
# ---------------------------------------------------------------------------


async def subscribe(
    *,
    user_id: UUID | str,
    feed_id: UUID | str,
) -> str:
    """Subscribe ``user_id`` to ``feed_id``.

    Returns one of:
        "subscribed"     — new active subscription created.
        "exists"         — user already actively subscribed to this feed.
        "cap_exceeded"   — user already holds MAX_SUBSCRIPTIONS_PER_USER
                           active rows; this call did nothing.
        "feed_inactive"  — feed.status != 'active'.
        "unknown_feed"   — feed_id not in signal_feeds.

    Concurrency: ``pg_advisory_xact_lock`` keyed on the user_id serialises
    every concurrent /signals on call so the cap check + insert land
    atomically. Without the lock, two concurrent adds could both observe
    `active_count = N < cap` and produce `N + 2 > cap` rows after both
    commit (mirrors the P3b copy_trade pattern).
    """
    uuid_user = _coerce_uuid(user_id)
    uuid_feed = _coerce_uuid(feed_id)
    if uuid_user is None or uuid_feed is None:
        raise ValueError("subscribe requires UUID-coercible user_id and feed_id")

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext($1))",
                str(uuid_user),
            )
            feed_row = await conn.fetchrow(
                "SELECT status FROM signal_feeds WHERE id = $1",
                uuid_feed,
            )
            if feed_row is None:
                return "unknown_feed"
            if feed_row["status"] != "active":
                return "feed_inactive"

            existing = await conn.fetchrow(
                "SELECT id FROM user_signal_subscriptions "
                " WHERE user_id = $1 AND feed_id = $2 "
                "   AND unsubscribed_at IS NULL",
                uuid_user, uuid_feed,
            )
            if existing is not None:
                # Backfill enrollment for pre-existing subscribers who have no
                # user_strategies row yet.  DO NOTHING preserves intentional
                # operator disables — this path must not re-enable them.
                await conn.execute(
                    "INSERT INTO user_strategies "
                    "    (user_id, strategy_name, weight, enabled) "
                    "VALUES ($1, 'signal_following', 1.0, TRUE) "
                    "ON CONFLICT (user_id, strategy_name) DO NOTHING",
                    uuid_user,
                )
                return "exists"

            active_count = int(await conn.fetchval(
                "SELECT COUNT(*) FROM user_signal_subscriptions "
                " WHERE user_id = $1 AND unsubscribed_at IS NULL",
                uuid_user,
            ))
            if active_count >= MAX_SUBSCRIPTIONS_PER_USER:
                return "cap_exceeded"

            await conn.execute(
                "INSERT INTO user_signal_subscriptions (user_id, feed_id) "
                "VALUES ($1, $2)",
                uuid_user, uuid_feed,
            )
            await conn.execute(
                "UPDATE signal_feeds "
                "   SET subscriber_count = subscriber_count + 1, "
                "       updated_at = NOW() "
                " WHERE id = $1",
                uuid_feed,
            )
            # Enroll user in strategy plane.  Re-enable only when this is the
            # user's first/fresh subscription (active_count==0 means any prior
            # user_strategies row was disabled by the unsubscribe flow, not by
            # an operator).  If they already have other active subscriptions the
            # strategy row must already be enabled — DO NOTHING preserves any
            # operator-level disables.
            _enroll_sql = (
                "INSERT INTO user_strategies (user_id, strategy_name, weight, enabled) "
                "VALUES ($1, 'signal_following', 1.0, TRUE) "
                + (
                    "ON CONFLICT (user_id, strategy_name) DO UPDATE SET enabled = TRUE"
                    if active_count == 0
                    else "ON CONFLICT (user_id, strategy_name) DO NOTHING"
                )
            )
            await conn.execute(_enroll_sql, uuid_user)
            return "subscribed"


async def unsubscribe(
    *,
    user_id: UUID | str,
    feed_id: UUID | str,
) -> bool:
    """Mark active subscription as unsubscribed.

    Returns True if a row flipped, False if there was no active subscription
    to flip (idempotent — re-running on an already-unsubscribed pair is a
    no-op rather than an error).
    """
    uuid_user = _coerce_uuid(user_id)
    uuid_feed = _coerce_uuid(feed_id)
    if uuid_user is None or uuid_feed is None:
        raise ValueError(
            "unsubscribe requires UUID-coercible user_id and feed_id",
        )

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "UPDATE user_signal_subscriptions "
                "   SET unsubscribed_at = NOW() "
                " WHERE user_id = $1 AND feed_id = $2 "
                "   AND unsubscribed_at IS NULL "
                " RETURNING id",
                uuid_user, uuid_feed,
            )
            if row is None:
                return False
            await conn.execute(
                "UPDATE signal_feeds "
                "   SET subscriber_count = GREATEST(subscriber_count - 1, 0), "
                "       updated_at = NOW() "
                " WHERE id = $1",
                uuid_feed,
            )
            # Disable strategy enrollment when no active subscriptions remain.
            remaining = int(await conn.fetchval(
                "SELECT COUNT(*) FROM user_signal_subscriptions "
                " WHERE user_id = $1 AND unsubscribed_at IS NULL",
                uuid_user,
            ))
            if remaining == 0:
                await conn.execute(
                    "UPDATE user_strategies "
                    "   SET enabled = FALSE "
                    " WHERE user_id = $1 AND strategy_name = 'signal_following'",
                    uuid_user,
                )
            return True


# ---------------------------------------------------------------------------
# Read helpers — used by /signals handler and the strategy scan loop.
# ---------------------------------------------------------------------------


async def list_user_subscriptions(user_id: UUID | str) -> list[dict[str, Any]]:
    """Return active subscriptions joined with feed metadata."""
    uuid_user = _coerce_uuid(user_id)
    if uuid_user is None:
        return []
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT s.id, s.feed_id, s.subscribed_at,
                   f.name AS feed_name, f.slug AS feed_slug,
                   f.status AS feed_status,
                   f.subscriber_count
              FROM user_signal_subscriptions s
              JOIN signal_feeds f ON f.id = s.feed_id
             WHERE s.user_id = $1 AND s.unsubscribed_at IS NULL
             ORDER BY s.subscribed_at ASC
            """,
            uuid_user,
        )
    return [dict(r) for r in rows]


async def get_feed_by_slug(slug: str) -> dict[str, Any] | None:
    if not slug:
        return None
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, slug, operator_id, status, description, "
            "       subscriber_count, created_at, updated_at "
            "  FROM signal_feeds WHERE slug = $1",
            slug,
        )
    return dict(row) if row else None


async def list_active_feeds() -> list[dict[str, Any]]:
    """List all active feeds (status='active') for the /signals catalogue."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, slug, operator_id, status, description, "
            "       subscriber_count, created_at, updated_at "
            "  FROM signal_feeds WHERE status = 'active' "
            " ORDER BY name ASC",
        )
    return [dict(r) for r in rows]


__all__ = [
    "MAX_SUBSCRIPTIONS_PER_USER",
    "MAX_SLUG_LEN",
    "SLUG_PATTERN",
    "VALID_FEED_STATUSES",
    "VALID_PUBLICATION_SIDES",
    "create_feed",
    "publish_signal",
    "publish_exit",
    "subscribe",
    "unsubscribe",
    "list_user_subscriptions",
    "get_feed_by_slug",
    "list_active_feeds",
]
