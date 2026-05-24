"""signal_evaluator — translate operator-curated publications into SignalCandidates.

Pure DB reads — no HTTP. The strategy contract (P3a) requires `scan` to emit
`SignalCandidate` objects. This module owns the read-and-filter pipeline so
`SignalFollowingStrategy.scan` stays focused on the BaseStrategy boundary.

Filter enforcement (best-effort, no HTTP available):
    blacklist                      -> always honoured (synchronous, market_id).
    categories                     -> honoured if payload['categories'] is
                                      present; conservative skip when filter
                                      is set but payload provides no
                                      category metadata (mirrors P3b
                                      copy_trade behaviour).
    min_liquidity                  -> NOT enforced. Polymarket metadata
                                      requires HTTP; the issue spec forbids
                                      HTTP fetches inside scan(). Operators
                                      are trusted to pre-filter on liquidity
                                      before publishing.
    max_time_to_resolution_days    -> ENFORCED via the local markets table.
                                      ``markets.resolution_at`` is a synchronous
                                      DB column (synced by the scanner), so the
                                      no-HTTP constraint is satisfied. Publications
                                      whose market resolves beyond the profile
                                      horizon are dropped at the SQL boundary,
                                      preventing entry into far-dated futures that
                                      never hit TP/SL and lock a concurrency slot.
                                      The sentinel value
                                      (RESOLUTION_DISTANCE_DISABLED_DAYS = 365)
                                      disables the check. Markets with a NULL
                                      resolution_at (not yet synced) are kept.

The downstream signal scan loop (P3d) is responsible for risk gate
enforcement and per-publication-per-user dedup. This module emits one
SignalCandidate per publication that survives the filter envelope.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from ...database import get_pool
from ...domain.strategy.types import (
    VALID_SIDES,
    MarketFilters,
    SignalCandidate,
    UserContext,
)

logger = logging.getLogger(__name__)

DEFAULT_CONFIDENCE = 0.6
DEFAULT_TRADE_SIZE_USDC = 10.0
MIN_TRADE_SIZE_USDC = 1.0
# A max_time_to_resolution_days at or above this value disables the
# resolution-horizon filter (mirrors copy_trade.RESOLUTION_DISTANCE_DISABLED_DAYS).
RESOLUTION_DISTANCE_DISABLED_DAYS = 365


# ---------------------------------------------------------------------------
# Coercion helpers.
# ---------------------------------------------------------------------------


def _coerce_uuid(value: Any) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _payload_dict(raw: Any) -> dict[str, Any]:
    """Coerce a payload column value into a plain dict.

    asyncpg returns JSONB as a Python str by default unless a codec is
    registered. Both the str path and the (already-decoded) dict path are
    handled so this module is decoupled from the connection setup.
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


# ---------------------------------------------------------------------------
# Filter + scoring.
# ---------------------------------------------------------------------------


def _passes_market_filters(
    market_id: str,
    payload: dict[str, Any],
    market_filters: MarketFilters,
) -> bool:
    """Synchronous filter enforcement (no I/O)."""
    if market_id in market_filters.blacklisted_market_ids:
        return False
    if market_filters.categories:
        raw_cats = payload.get("categories")
        if isinstance(raw_cats, list):
            cats = {str(c) for c in raw_cats if isinstance(c, (str, int))}
        elif isinstance(raw_cats, str) and raw_cats:
            cats = {raw_cats}
        else:
            return False
        if not cats.intersection(market_filters.categories):
            return False
    return True


def _resolve_size_usdc(
    payload: dict[str, Any],
    user_context: UserContext,
) -> float:
    """Resolve the suggested trade size for a publication.

    Priority:
        1. payload['size_usdc'] (operator-suggested, when > 0)
        2. DEFAULT_TRADE_SIZE_USDC ($10) fallback

    The chosen size is then capped to ``user_available × capital_pct`` so
    the candidate respects the user's per-strategy allocation cap. Returns
    0.0 if the final size is below the $1 floor — caller drops the
    candidate (mirrors the P3b scaler floor).
    """
    raw = _coerce_float(payload.get("size_usdc"))
    target = raw if raw > 0 else DEFAULT_TRADE_SIZE_USDC
    cap = (
        user_context.available_balance_usdc
        * user_context.capital_allocation_pct
    )
    if cap <= 0:
        return 0.0
    sized = min(target, cap)
    if sized < MIN_TRADE_SIZE_USDC:
        return 0.0
    return sized


def _resolve_confidence(payload: dict[str, Any]) -> float:
    """Clamp payload['confidence'] into [0.0, 1.0]; default 0.6."""
    raw = payload.get("confidence")
    try:
        c = float(raw) if raw is not None else DEFAULT_CONFIDENCE
    except (TypeError, ValueError):
        c = DEFAULT_CONFIDENCE
    if c < 0.0:
        return 0.0
    if c > 1.0:
        return 1.0
    return c


# ---------------------------------------------------------------------------
# DB reads.
# ---------------------------------------------------------------------------


async def _load_active_subscriptions(user_id: UUID) -> list[dict[str, Any]]:
    """Active subscriptions joined to active feeds only."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT s.id, s.feed_id, s.subscribed_at,
                   f.status AS feed_status
              FROM user_signal_subscriptions s
              JOIN signal_feeds f ON f.id = s.feed_id
             WHERE s.user_id = $1
               AND s.unsubscribed_at IS NULL
               AND f.status = 'active'
             ORDER BY s.subscribed_at ASC
            """,
            user_id,
        )
    return [dict(r) for r in rows]


async def _load_active_publications(
    feed_id: UUID,
    subscribed_at: datetime,
    max_resolution_days: int,
) -> list[dict[str, Any]]:
    """Entry publications since user subscribed that haven't expired/exited.

    Three suppression rules apply, mirroring the exit-symmetry that
    ``SignalFollowingStrategy.evaluate_exit`` enforces:

        (1) the row is itself an entry (``exit_signal = FALSE``),
        (2) the entry has not been retired in place
            (``exit_published_at IS NULL``),
        (3) no LATER ``exit_signal = TRUE`` row exists on the same feed +
            market (the ``publish_exit`` separate-row pattern).

    Without (3), a user subscribed mid-cycle could pull an entry whose
    separate-exit-row peer has already been published, and a fresh
    position would be opened on a signal the operator has already closed.
    The downstream scan loop (P3d) is the next line of defence with
    per-publication-per-user dedup, but the SQL boundary is the cheaper
    place to keep the surface clean.
    """
    # Resolution-horizon guard: drop publications whose market resolves beyond
    # the user's profile horizon (LEFT JOIN markets — NULL resolution_at, i.e.
    # not-yet-synced markets, are kept). Disabled when the caller passes the
    # sentinel so the JOIN/clause cost is skipped entirely.
    enforce_horizon = (
        max_resolution_days < RESOLUTION_DISTANCE_DISABLED_DAYS
        and max_resolution_days >= 0
    )
    horizon_clause = (
        " AND (m.resolution_at IS NULL"
        " OR m.resolution_at <= NOW() + make_interval(days => $3::int))"
        if enforce_horizon
        else ""
    )
    query = f"""
        SELECT p.id, p.feed_id, p.market_id, p.side, p.target_price,
               p.signal_type, p.payload, p.exit_signal, p.published_at,
               p.expires_at, p.exit_published_at
          FROM signal_publications p
          LEFT JOIN markets m ON m.id = p.market_id
         WHERE p.feed_id = $1
           AND p.exit_signal = FALSE
           AND p.exit_published_at IS NULL
           AND p.published_at > $2
           AND (p.expires_at IS NULL OR p.expires_at > NOW())
           {horizon_clause}
           AND NOT EXISTS (
             SELECT 1
               FROM signal_publications x
              WHERE x.feed_id = p.feed_id
                AND x.market_id = p.market_id
                AND x.exit_signal = TRUE
                AND x.published_at > p.published_at
           )
         ORDER BY p.published_at ASC
    """
    params: list[Any] = [feed_id, subscribed_at]
    if enforce_horizon:
        params.append(int(max_resolution_days))
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------


async def evaluate_publications_for_user(
    *,
    user_context: UserContext,
    market_filters: MarketFilters,
    strategy_name: str,
) -> list[SignalCandidate]:
    """Read user's subscriptions + publications and emit SignalCandidates.

    A publication that fails any filter is dropped silently. A malformed
    publication that raises during candidate construction is logged and
    skipped — one bad row must not crash the user's whole scan tick.
    """
    user_uuid = _coerce_uuid(user_context.user_id)
    if user_uuid is None:
        return []
    subscriptions = await _load_active_subscriptions(user_uuid)
    if not subscriptions:
        return []

    candidates: list[SignalCandidate] = []
    for sub in subscriptions:
        feed_id = sub["feed_id"]
        try:
            publications = await _load_active_publications(
                feed_id, sub["subscribed_at"],
                market_filters.max_time_to_resolution_days,
            )
        except Exception as exc:
            logger.warning(
                "signal_evaluator publication fetch failed feed=%s err=%s",
                feed_id, exc,
            )
            continue
        for pub in publications:
            try:
                candidate = _build_candidate(
                    pub=pub,
                    user_context=user_context,
                    market_filters=market_filters,
                    strategy_name=strategy_name,
                )
            except Exception as exc:
                logger.warning(
                    "signal_evaluator candidate build failed pub=%s err=%s",
                    pub.get("id"), exc,
                )
                continue
            if candidate is not None:
                candidates.append(candidate)
    return _diversify_order(candidates, user_uuid)


def _diversify_order(
    candidates: list[SignalCandidate], user_id: Any
) -> list[SignalCandidate]:
    """Order candidates by a stable per-user key so subscribers do not all
    converge on the same published prefix.

    Publications are loaded in identical ``published_at`` order for every
    subscriber, and the downstream scan enters that prefix until the
    concurrency cap stops it — so N users ended up holding the *same* handful
    of markets ("bot only ever trades the same 5"). Every candidate here has
    already cleared the edge / liquidity / resolution-horizon filters, so any
    is an acceptable entry; ordering by sha1(user_id:market_id) spreads the
    eligible set across users (distinct holdings) while staying deterministic
    per (user, market) so a user does not churn positions between ticks.
    """
    seed = str(user_id)

    def _key(c: SignalCandidate) -> str:
        return hashlib.sha1(f"{seed}:{c.market_id}".encode()).hexdigest()

    return sorted(candidates, key=_key)


def _build_candidate(
    *,
    pub: dict[str, Any],
    user_context: UserContext,
    market_filters: MarketFilters,
    strategy_name: str,
) -> SignalCandidate | None:
    """Translate one publication row into a SignalCandidate or None to skip."""
    market_id = str(pub.get("market_id") or "")
    if not market_id:
        return None
    side = str(pub.get("side") or "").upper()
    if side not in VALID_SIDES:
        return None

    payload = _payload_dict(pub.get("payload"))
    if not _passes_market_filters(market_id, payload, market_filters):
        return None

    size_usdc = _resolve_size_usdc(payload, user_context)
    if size_usdc <= 0:
        return None

    confidence = _resolve_confidence(payload)
    condition_id = str(payload.get("condition_id") or "") or market_id

    signal_ts = pub.get("published_at") or datetime.now(timezone.utc)
    if not isinstance(signal_ts, datetime):
        signal_ts = datetime.now(timezone.utc)
    elif signal_ts.tzinfo is None:
        signal_ts = signal_ts.replace(tzinfo=timezone.utc)

    target_price = pub.get("target_price")
    metadata: dict[str, Any] = {
        "feed_id": str(pub["feed_id"]),
        "publication_id": str(pub["id"]),
        "signal_type": str(pub.get("signal_type") or "entry"),
        "market_id": market_id,
    }
    if target_price is not None:
        metadata["target_price"] = float(target_price)
    signal_reason = payload.get("signal_reason")
    if signal_reason:
        metadata["signal_reason"] = str(signal_reason)

    return SignalCandidate(
        market_id=market_id,
        condition_id=condition_id,
        side=side,
        confidence=confidence,
        suggested_size_usdc=size_usdc,
        strategy_name=strategy_name,
        signal_ts=signal_ts,
        metadata=metadata,
    )


__all__ = [
    "DEFAULT_CONFIDENCE",
    "DEFAULT_TRADE_SIZE_USDC",
    "MIN_TRADE_SIZE_USDC",
    "evaluate_publications_for_user",
]
