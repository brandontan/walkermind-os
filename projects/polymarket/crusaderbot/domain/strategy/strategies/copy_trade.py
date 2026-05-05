"""CopyTradeStrategy — mirror up to three Polymarket wallets per user.

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
from ....services.copy_trade.scaler import scale_size
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


class CopyTradeStrategy(BaseStrategy):
    """Mirror entries from up to 3 leader wallets, follow leader exits.

    Per-user state lives in the `copy_targets` table (max 3 active rows enforced
    at the Telegram handler boundary). Per-trade dedup uses the unique
    `copy_trade_events.source_tx_hash` index — re-scans of the same leader
    trade will not emit duplicate signals.
    """

    name = "copy_trade"
    version = "1.0.0"
    risk_profile_compatibility = ["conservative", "balanced", "aggressive"]

    def default_tp_sl(self) -> tuple[float, float]:
        return (DEFAULT_TP_PCT, DEFAULT_SL_PCT)

    async def scan(
        self,
        market_filters: MarketFilters,
        user_context: UserContext,
    ) -> list[SignalCandidate]:
        """Emit one SignalCandidate per fresh leader entry, deduped by tx hash.

        Pipeline:
            1. load active copy_targets for user (max 3)
            2. per target: poll Polymarket Data API for recent trades
               (5s timeout, 1 req/s global rate limit — handled in watcher)
            3. drop trades older than 5 minutes
            4. drop trades whose source_tx_hash is already in copy_trade_events
            5. scale leader size to user bankroll (scaler.scale_size)
            6. build SignalCandidate; metadata carries leader linkage so the
               downstream consumer can persist the copy_trade_events row
        """
        targets = await _load_active_copy_targets(user_context.user_id)
        if not targets:
            return []

        candidates: list[SignalCandidate] = []
        cutoff = datetime.now(timezone.utc) - RECENT_TRADE_WINDOW

        for target in targets:
            wallet = target["target_wallet_address"]
            try:
                trades = await fetch_recent_wallet_trades(
                    wallet, limit=MAX_TRADES_PER_WALLET,
                )
            except Exception as exc:
                # wallet_watcher swallows expected errors; this is a final
                # belt-and-braces guard so a single rogue target can never
                # crash the scan loop for the user's other targets.
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
                if not tx_hash or await _already_mirrored(target["id"], tx_hash):
                    continue

                side = _normalise_side(trade)
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

                leader_bankroll = _coerce_float(target.get("leader_bankroll_estimate"))
                if leader_bankroll <= 0:
                    leader_bankroll = max(leader_size_usdc, 1.0)

                sized = scale_size(
                    leader_size=leader_size_usdc,
                    leader_bankroll=leader_bankroll,
                    user_available=user_context.available_balance_usdc,
                    max_position_pct=user_context.capital_allocation_pct,
                )
                if sized <= 0.0:
                    # scale_size returns 0.0 to signal "skip" (below $1 floor
                    # or any degenerate input). Honour the skip — never emit
                    # a SignalCandidate the risk gate would have to drop.
                    continue

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
                            "copy_target_id": str(target["id"]),
                            "leader_size_usdc": leader_size_usdc,
                            "leader_price": _coerce_float(trade.get("price")),
                            "leader_trade_ts": ts.isoformat(),
                        },
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
    """Return active copy_targets rows for ``user_id`` (≤3 by table cap).

    Foundation cap: the Telegram handler refuses to insert a 4th active row,
    so the LIMIT here is defensive against a manual DB row that bypassed the
    handler.
    """
    pool = get_pool()
    user_uuid = _coerce_uuid(user_id)
    if user_uuid is None:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, user_id, target_wallet_address, scale_factor,
                   trades_mirrored, created_at
              FROM copy_targets
             WHERE user_id = $1 AND status = 'active'
             ORDER BY created_at ASC
             LIMIT $2
            """,
            user_uuid, MAX_TARGETS_PER_USER,
        )
    return [dict(r) for r in rows]


async def _already_mirrored(copy_target_id: Any, source_tx_hash: str) -> bool:
    """Return True iff this follower has already mirrored this leader trade.

    Dedup is per-follower: the unique boundary is the composite
    `(copy_target_id, source_tx_hash)` index on `copy_trade_events`. The same
    leader transaction may legitimately be mirrored by every follower of the
    leader (each owns a distinct `copy_target_id`), but a single follower
    must not double-mirror after a re-scan. The strategy reads here for
    early-exit; the downstream consumer that persists the row catches the
    constraint as the second line of defence against a concurrent re-scan.
    """
    target_uuid = _coerce_uuid(copy_target_id)
    if target_uuid is None or not source_tx_hash:
        return False
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM copy_trade_events "
            "WHERE copy_target_id = $1 AND source_tx_hash = $2",
            target_uuid, source_tx_hash,
        )
    return row is not None


def _normalise_side(trade: dict) -> str | None:
    """Map a Polymarket Data API trade row to our ('YES' | 'NO') side.

    Polymarket exposes trade direction two ways:
        * `outcome` == 'Yes' | 'No' (binary market outcome label)
        * `side`    == 'BUY' | 'SELL' (taker direction on the outcome token)

    Copy-trade only mirrors `BUY` legs — selling is captured by leader_exit.
    """
    side = (trade.get("side") or "").upper()
    if side and side != "BUY":
        return None
    outcome = (trade.get("outcome") or "").upper()
    if outcome in ("YES", "NO"):
        return outcome
    return None


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
