"""CopyTradeStrategy — mirror active copy_trade_tasks per user.

Foundation contract (P3a):
    BaseStrategy.scan          — emit SignalCandidates, no execution side-effects
    BaseStrategy.evaluate_exit — leader_exit detection, no order placement
    BaseStrategy.default_tp_sl — TP 25% / SL 10%

Pipeline boundary (P3b scope):
    DATA -> [STRATEGY <-- this file] -> INTELLIGENCE -> RISK -> EXECUTION

This module never places orders, never touches the risk gate, never bypasses
activation guards. SignalCandidates returned from `scan()` are handed to the
downstream signal scan loop (P3d) which routes them through risk + execution.

Exit reason encoding:
    The foundation `ExitDecision` invariant pins `should_exit=True` to
    `reason="strategy_exit"`. The leader-driven sub-reason is preserved in
    `metadata["reason"] = "leader_exit"` so downstream telemetry can attribute
    closes to the leader wallet without breaking the foundation contract.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from ....database import get_pool
from ....integrations import polymarket as pm
from ....services.copy_trade.scaler import mirror_size_direct
from ....services.copy_trade.wallet_watcher import (
    fetch_leader_open_condition_ids,
    fetch_recent_wallet_trades,
)
from ..base import BaseStrategy
from ..types import ExitDecision, MarketFilters, SignalCandidate, UserContext

logger = logging.getLogger(__name__)

COPY_TRADE_CONFIDENCE = 0.75
DEFAULT_TP_PCT = 0.25
DEFAULT_SL_PCT = 0.10
RECENT_TRADE_WINDOW = timedelta(minutes=5)
MAX_TRADES_PER_WALLET = 20
MAX_TARGETS_PER_USER = 3
# Sentinel: a max_time_to_resolution_days at or above this value is treated
# as "no resolution-distance constraint" — the strategy skips the metadata
# fetch and the corresponding check. Anything below it triggers the fetch.
RESOLUTION_DISTANCE_DISABLED_DAYS = 365


class CopyTradeStrategy(BaseStrategy):
    """Mirror entries from active copy_trade_tasks, follow leader exits.

    Per-user state lives in the `copy_trade_tasks` table. Per-trade dedup uses
    `copy_trade_idempotency` keyed on (user_id, task_id, leader_trade_id) —
    re-scans of the same leader trade will not emit duplicate signals.
    """

    name = "copy_trade"
    version = "1.0.0"
    risk_profile_compatibility = ["conservative", "balanced", "aggressive", "custom"]

    def default_tp_sl(self) -> tuple[float, float]:
        return (DEFAULT_TP_PCT, DEFAULT_SL_PCT)

    async def scan(
        self,
        market_filters: MarketFilters,
        user_context: UserContext,
    ) -> list[SignalCandidate]:
        """Emit one SignalCandidate per fresh leader entry, deduped by tx hash.

        Pipeline:
            1. load active copy_trade_tasks for user
            2. per task: poll Polymarket Data API for recent trades
               (5s timeout, 1 req/s global rate limit — handled in watcher)
            3. drop trades older than 5 minutes
            4. drop trades already in copy_trade_idempotency
            5. size trade from task copy_mode/copy_amount/copy_pct
            6. build SignalCandidate with leader linkage + reasoning
        """
        targets = await _load_active_copy_targets(user_context.user_id)
        if not targets:
            return []

        candidates: list[SignalCandidate] = []
        cutoff = datetime.now(timezone.utc) - RECENT_TRADE_WINDOW

        for target in targets:
            wallet = target["wallet_address"]
            copy_direction = target.get("copy_direction", "buys_only")
            copy_mode = target.get("copy_mode", "fixed")
            cap_usdc = (
                user_context.available_balance_usdc
                * user_context.capital_allocation_pct
            )
            try:
                trades = await fetch_recent_wallet_trades(
                    wallet, limit=MAX_TRADES_PER_WALLET,
                )
            except Exception as exc:
                logger.warning(
                    "copy_trade scan: wallet fetch failed wallet=%s err=%s",
                    wallet, exc,
                )
                continue

            for trade in trades:
                ts = _parse_trade_timestamp(trade)
                if ts is None or ts < cutoff:
                    continue
                tx_hash = trade.get("transactionHash") or trade.get("tx_hash")
                if not tx_hash or await _already_mirrored(
                    user_context.user_id, target["id"], tx_hash
                ):
                    continue

                side = _normalise_side(trade, copy_direction)
                if side is None:
                    continue
                market_id = trade.get("market") or trade.get("market_id")
                condition_id = trade.get("conditionId") or trade.get("condition_id")
                leader_size_usdc = _coerce_float(
                    trade.get("usdcSize") or trade.get("size_usdc")
                    or trade.get("usdc_size")
                )
                if not market_id or not condition_id or leader_size_usdc <= 0:
                    continue
                if not await _passes_market_filters(
                    str(market_id), market_filters,
                ):
                    continue

                if copy_mode == "proportional":
                    pct = _coerce_float(target.get("copy_pct"))
                    if pct > 0:
                        sized = min(
                            user_context.available_balance_usdc * float(pct),
                            cap_usdc,
                        )
                    else:
                        sized = mirror_size_direct(
                            leader_size=leader_size_usdc,
                            user_available=user_context.available_balance_usdc,
                            max_position_pct=user_context.capital_allocation_pct,
                        )
                else:
                    fixed_amount = _coerce_float(target.get("copy_amount") or 5.0)
                    sized = min(fixed_amount, cap_usdc) if fixed_amount > 0 else 0.0

                min_size = _coerce_float(target.get("min_trade_size") or 0.50)
                if sized <= 0.0 or sized < min_size:
                    continue

                task_name = target.get("task_name") or wallet[:8]
                reasoning = (
                    f"CopyTrade: Mirroring {task_name} ({wallet[:8]}…). "
                    f"Mode={copy_mode}, Size=${sized:.2f}."
                )
                candidates.append(
                    SignalCandidate(
                        market_id=str(market_id),
                        condition_id=str(condition_id),
                        side=side,
                        confidence=COPY_TRADE_CONFIDENCE,
                        suggested_size_usdc=sized,
                        strategy_name=self.name,
                        signal_ts=datetime.now(timezone.utc),
                        metadata={
                            "source_tx_hash": str(tx_hash),
                            "leader_wallet": wallet,
                            "copy_task_id": str(target["id"]),
                            "leader_size_usdc": leader_size_usdc,
                            "leader_price": _coerce_float(trade.get("price")),
                            "leader_trade_ts": ts.isoformat(),
                        },
                        reasoning=reasoning,
                    )
                )

        return candidates

    async def evaluate_exit(self, position: dict) -> ExitDecision:
        """Close when the leader wallet has closed its mirrored position.

        Encoding (foundation contract):
            * leader closed   -> should_exit=True,  reason='strategy_exit',
                                 metadata['reason']='leader_exit'
            * leader still in -> should_exit=False, reason='hold'
            * unknown linkage -> should_exit=False, reason='hold'
        """
        meta = position.get("metadata") or {}
        leader_wallet = meta.get("leader_wallet")
        condition_id = meta.get("condition_id") or position.get("condition_id")
        if not leader_wallet or not condition_id:
            return ExitDecision(should_exit=False, reason="hold")

        try:
            open_conditions = await fetch_leader_open_condition_ids(leader_wallet)
        except Exception as exc:
            # Treat fetch failure as "do not exit" — the platform-level exit
            # watcher will retry on its next tick. Closing on a transient
            # failure would be worse than a delayed close.
            logger.warning(
                "copy_trade evaluate_exit: leader fetch failed wallet=%s err=%s",
                leader_wallet, exc,
            )
            return ExitDecision(should_exit=False, reason="hold")

        if str(condition_id) in open_conditions:
            return ExitDecision(should_exit=False, reason="hold")
        return ExitDecision(
            should_exit=True,
            reason="strategy_exit",
            metadata={"reason": "leader_exit", "leader_wallet": leader_wallet},
        )


# ---------------------------------------------------------------------------
# Internal helpers — not part of the public surface.
# ---------------------------------------------------------------------------


async def _load_active_copy_targets(user_id: str) -> list[dict[str, Any]]:
    """Return active copy_trade_tasks rows for ``user_id``."""
    pool = get_pool()
    user_uuid = _coerce_uuid(user_id)
    if user_uuid is None:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, user_id, wallet_address, task_name,
                   copy_mode, copy_amount, copy_pct,
                   copy_direction, min_trade_size, created_at
              FROM copy_trade_tasks
             WHERE user_id = $1 AND status = 'active'
             ORDER BY created_at ASC
             LIMIT $2
            """,
            user_uuid, MAX_TARGETS_PER_USER,
        )
    return [dict(r) for r in rows]


async def _passes_market_filters(
    market_id: str,
    market_filters: MarketFilters,
) -> bool:
    """Return True iff the market clears every active filter.

    Two cost classes:
      * blacklist + "all-permissive" check — synchronous, no I/O. Honoured
        always so a non-default `blacklisted_market_ids` is enforced even
        if every other filter is at its default.
      * categories / min_liquidity / max_time_to_resolution_days — require
        Gamma market metadata (`pm.get_market`, cached 120 s). The fetch
        happens only when at least one of those filter fields is set to
        a non-default value, so default-permissive scans pay no extra I/O.

    Conservative on metadata failure: if a filter that needs metadata is
    active and the Gamma fetch returns None, the candidate is skipped
    rather than emitted unverified — emitting a signal we cannot prove
    satisfies the user's filter envelope is the wrong default.
    """
    if market_id in market_filters.blacklisted_market_ids:
        return False

    needs_metadata = (
        bool(market_filters.categories)
        or market_filters.min_liquidity > 0.0
        or (
            market_filters.max_time_to_resolution_days
            < RESOLUTION_DISTANCE_DISABLED_DAYS
        )
    )
    if not needs_metadata:
        return True

    market_meta: dict | None = None
    try:
        market_meta = await pm.get_market(market_id)
    except Exception as exc:
        # pm.get_market already swallows HTTP failures and returns None,
        # but we keep this defensive belt-and-braces in case the
        # underlying client is replaced.
        logger.warning(
            "copy_trade filter: get_market failed market=%s err=%s",
            market_id, exc,
        )
        return False
    if not market_meta:
        return False

    if market_filters.categories:
        market_categories = _extract_market_categories(market_meta)
        if not market_categories.intersection(market_filters.categories):
            return False

    if market_filters.min_liquidity > 0.0:
        liquidity = _coerce_float(
            market_meta.get("liquidity")
            or market_meta.get("liquidityNum")
        )
        if liquidity < market_filters.min_liquidity:
            return False

    if (
        market_filters.max_time_to_resolution_days
        < RESOLUTION_DISTANCE_DISABLED_DAYS
    ):
        days_to_resolution = _days_to_resolution(market_meta)
        if days_to_resolution is None:
            return False
        if days_to_resolution > market_filters.max_time_to_resolution_days:
            return False

    return True


def _extract_market_categories(market_meta: dict) -> set[str]:
    """Best-effort category extraction from a Gamma market dict.

    Polymarket returns categories under both `category` (single string) and
    `tags` (list of strings) depending on the endpoint; we coalesce both.
    """
    out: set[str] = set()
    cat = market_meta.get("category")
    if isinstance(cat, str) and cat:
        out.add(cat)
    tags = market_meta.get("tags")
    if isinstance(tags, list):
        for t in tags:
            if isinstance(t, str) and t:
                out.add(t)
    return out


def _days_to_resolution(market_meta: dict) -> int | None:
    """Days from now until market resolution, or None if unknown.

    Tries the documented Gamma fields in order. Negative results (already
    resolved) are returned as 0 so a `max_time_to_resolution_days = 30`
    filter still excludes already-resolved markets via the `>` test.
    """
    raw = (
        market_meta.get("endDate")
        or market_meta.get("endDateIso")
        or market_meta.get("end_date")
        or market_meta.get("resolutionDate")
    )
    if not raw:
        return None
    try:
        if isinstance(raw, (int, float)):
            end_dt = datetime.fromtimestamp(int(raw), tz=timezone.utc)
        else:
            stripped = str(raw).strip()
            if stripped.endswith("Z"):
                stripped = stripped[:-1] + "+00:00"
            end_dt = datetime.fromisoformat(stripped)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    delta = end_dt - datetime.now(timezone.utc)
    days = int(delta.total_seconds() // 86400)
    return max(days, 0)


async def _already_mirrored(
    user_id: str, task_id: Any, source_tx_hash: str
) -> bool:
    """Return True iff this user+task has already processed this leader trade.

    Dedup key: (user_id, task_id, leader_trade_id) on copy_trade_idempotency.
    Strategy checks here for early exit; the downstream execution consumer
    re-asserts via INSERT ON CONFLICT as the second defence against concurrent
    re-scans.
    """
    user_uuid = _coerce_uuid(user_id)
    task_uuid = _coerce_uuid(task_id)
    if user_uuid is None or task_uuid is None or not source_tx_hash:
        return False
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM copy_trade_idempotency "
            "WHERE user_id = $1 AND task_id = $2 AND leader_trade_id = $3",
            user_uuid, task_uuid, source_tx_hash,
        )
    return row is not None


def _normalise_side(
    trade: dict, copy_direction: str = "buys_only"
) -> str | None:
    """Map a Polymarket Data API trade row to our ('YES' | 'NO') side.

    copy_direction='buys_only': only BUY legs are mirrored (default).
    copy_direction='buys_and_sells': SELL YES → bet NO, SELL NO → bet YES.
    """
    side = (trade.get("side") or "").upper()
    outcome = (trade.get("outcome") or "").upper()

    if copy_direction == "buys_only":
        if side and side != "BUY":
            return None
        return outcome if outcome in ("YES", "NO") else None

    # buys_and_sells: invert side for SELL trades
    if side == "SELL":
        if outcome == "YES":
            return "NO"
        if outcome == "NO":
            return "YES"
        return None
    return outcome if outcome in ("YES", "NO") else None


def _parse_trade_timestamp(trade: dict) -> datetime | None:
    """Best-effort parse of a Polymarket trade timestamp.

    Accepts:
        * unix int / str ('1700000000')
        * ISO-8601 string ('2026-05-04T12:00:00Z')

    Returns None if no usable timestamp field is present — the caller drops
    the trade rather than emitting a signal with an unknown signal time.
    """
    raw = trade.get("timestamp") or trade.get("ts") or trade.get("created_at")
    if raw is None:
        return None
    try:
        if isinstance(raw, (int, float)):
            return datetime.fromtimestamp(int(raw), tz=timezone.utc)
        if isinstance(raw, str):
            stripped = raw.strip()
            if stripped.isdigit():
                return datetime.fromtimestamp(int(stripped), tz=timezone.utc)
            if stripped.endswith("Z"):
                stripped = stripped[:-1] + "+00:00"
            dt = datetime.fromisoformat(stripped)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return None


def _coerce_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _coerce_uuid(value: Any) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


__all__ = ["CopyTradeStrategy"]
