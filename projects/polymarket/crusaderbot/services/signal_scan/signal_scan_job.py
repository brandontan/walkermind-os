"""P3d signal scan job — per-user signal_following scan loop + execution queue.

Pipeline (per user, per scan tick):
    1. Load users enrolled in signal_following + auto_trade_on + Tier 3+
    2. Build UserContext + MarketFilters from DB row
    3. SignalFollowingStrategy.scan() -> list[SignalCandidate]  (pure DB reads)
    4. Per candidate:
       a. execution_queue pre-check: skip if publication_id already present
       b. Build TradeSignal; run TradeEngine.execute() (gate + paper fill)
       c. On approval: INSERT into execution_queue + mark executed
       d. Log outcome: accepted | duplicate | skipped_dedup | rejected | failed

Deduplication (dual-layer):
    Outer — execution_queue UNIQUE (user_id, publication_id) — permanent;
            prevents re-execution after a prior tick already submitted.
    Inner — idempotency_keys 30-min window (risk gate step 10) — short-circuit
            for recent risk rejections so the gate is not re-evaluated every
            30 s during a transient block (e.g. max_concurrent_trades).

Crash recovery:
    A prior tick may have inserted a 'queued' row and crashed before the
    paper engine completed. This path resumes via router_execute directly
    (bypassing TradeEngine / re-running the risk gate) because:
      * Gate step 10 rejects the same idempotency_key for 30 min.
      * Gate step 9 rejects stale signals after the 4h staleness window
        (SIGNAL_STALE_SECONDS=14400). Step 1c in _process_candidate enforces
        a tighter 30-min window for feed publications before gate execution.
      * Crash-recovery re-fetches current market prices at resume time, so
        stale entry prices are not a concern on this path.
    The crash-recovery router call is the ONLY place router_execute is used
    directly in this module. All normal execution paths go through TradeEngine.

Safety:
    * No activation guard mutations.
    * Risk gate is mandatory inside TradeEngine; router_execute is never
      called without approval on the normal path.
    * No HTTP fetches.  No threading — asyncio only.
    * Every exception is caught, logged, and does NOT propagate to the caller
      so one bad user/publication cannot crash the whole scan tick.
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog

from ...core import event_bus as _event_bus
from ...database import get_pool
from ...domain.execution.router import execute as router_execute
from ...domain.ops.kill_switch import is_active as kill_switch_is_active
from ...domain.strategy.registry import StrategyRegistry
from ...domain.strategy.types import MarketFilters, SignalCandidate, UserContext
from ...integrations import polymarket as _polymarket
from ..trade_engine import TradeEngine, TradeResult, TradeSignal
from .lib_strategy_runner import ENABLED_STRATEGIES, DEFERRED_STRATEGIES, run_lib_strategy
from ..signal_feed.signal_evaluator import evaluate_publications_for_user

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STRATEGY_NAME = "signal_following"

# Maximum age of a signal_publication before it is rejected for execution.
# Signals older than this window have stale entry prices — the market has
# already moved, making fills unrealistic. 30 minutes is conservative;
# the signal_publications.expires_at window (4h) is intentionally longer
# to support feed UI history display, NOT to gate execution.
_MAX_SIGNAL_AGE_SECONDS: int = 1800  # 30 minutes

# Maximum ratio of live_price / db_price before a candidate is rejected.
# Protects against stale markets table prices: if the Gamma live price
# is more than 2x the cached DB price, the DB data is too stale for a
# realistic paper fill. Guard only fires when a live price can be fetched;
# on API failure it falls through so a Gamma outage cannot block trading.
_MAX_PRICE_DIVERGENCE_RATIO: float = 2.0

# ---------------------------------------------------------------------------
# Preset → lib strategy name mapping
# ---------------------------------------------------------------------------

_LIB_STRATEGY_NAMES: frozenset[str] = frozenset(ENABLED_STRATEGIES) | frozenset(DEFERRED_STRATEGIES)

_PRESET_ALLOWED: dict[str | None, frozenset[str]] = {
    "whale_mirror":   frozenset({"whale_tracking"}),
    "trend_breakout": frozenset({"trend_breakout"}),
    "contrarian":     frozenset({"momentum"}),
    "value_hunter":   frozenset({"value_investor"}),
    "close_sweep":    frozenset({"expiration_timing"}),
    "pair_arb":       frozenset({"pair_arb"}),
    "ensemble":       frozenset({"ensemble", "trend_breakout", "momentum", "value_investor"}),
    "full_auto":      _LIB_STRATEGY_NAMES,
    None:             _LIB_STRATEGY_NAMES,  # no preset set → full_auto behaviour
}


def _preset_allows(active_preset: str | None, strategy_name: str) -> bool:
    """Return True if user's active_preset permits signals from strategy_name."""
    return strategy_name in _PRESET_ALLOWED.get(active_preset, _LIB_STRATEGY_NAMES)

# Module-level TradeEngine singleton — stateless; safe to share across ticks.
_engine: TradeEngine = TradeEngine()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _load_enrolled_users() -> list[dict[str, Any]]:
    """Active users enrolled in signal_following strategy with auto_trade_on."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                u.id                     AS user_id,
                u.telegram_user_id,
                u.access_tier,
                u.auto_trade_on,
                u.paused,
                COALESCE(w.balance_usdc, 0)   AS balance_usdc,
                COALESCE(s.risk_profile, 'balanced') AS risk_profile,
                COALESCE(s.trading_mode, 'paper')    AS trading_mode,
                s.tp_pct,
                s.sl_pct,
                s.daily_loss_override,
                us.weight                AS capital_allocation_pct,
                COALESCE(urp.profile_name, s.risk_profile, 'balanced') AS resolved_profile,
                s.active_preset,
                COALESCE(s.min_liquidity, 0)         AS min_liquidity_threshold
            FROM user_strategies us
            JOIN users          u   ON u.id  = us.user_id
            JOIN wallets        w   ON w.user_id = u.id
            JOIN user_settings  s   ON s.user_id = u.id
            LEFT JOIN user_risk_profile urp ON urp.user_id = u.id
            WHERE us.strategy_name = $1
              AND us.enabled        = TRUE
              AND u.auto_trade_on   = TRUE
              AND u.paused          = FALSE
            """,
            _STRATEGY_NAME,
        )
    return [dict(r) for r in rows]


async def _load_market(market_id: str) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM markets WHERE id = $1",
            market_id,
        )
    return dict(row) if row else None


async def _publication_already_queued(user_id: UUID, publication_id: UUID) -> bool:
    """Return True when (user_id, publication_id) already in execution_queue."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM execution_queue "
            " WHERE user_id = $1 AND publication_id = $2"
            "   AND status IN ('executed', 'failed')",
            user_id, publication_id,
        )
    return row is not None


async def _load_stale_queued_row(
    user_id: UUID,
    publication_id: UUID,
) -> dict[str, Any] | None:
    """Return the stale status='queued' row for crash-recovery resume, or None.

    A 'queued' row means a prior tick inserted the queue entry and approved
    the gate but crashed before router_execute completed.  The row must be
    resumed without re-running the gate because: (a) gate step 10 rejects
    the same idempotency_key for 30 min, and (b) gate step 9 rejects the
    original signal after the 4h staleness window (SIGNAL_STALE_SECONDS=14400).
    Current market prices are re-fetched at resume time, so stale entry prices
    are not a concern on this path.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT market_id, side, final_size_usdc, suggested_size_usdc, "
            "       idempotency_key, chosen_mode "
            "  FROM execution_queue "
            " WHERE user_id = $1 AND publication_id = $2 AND status = 'queued'",
            user_id, publication_id,
        )
    return dict(row) if row else None


async def _has_open_position_for_market(user_id: UUID, market_id: str) -> bool:
    """Return True when the user has an open OR recently closed (24h) position on this market.

    Runs before the risk gate so it short-circuits without creating a risk_log
    entry or idempotency_key record. Closes the race window between two
    concurrent scan ticks that both pass gate step 10 (orders-table dedup)
    before either has committed its position row — positions is the
    authoritative source because it is committed in the same atomic transaction
    as the order row.

    The 24h closed-position window prevents the scanner from immediately
    reopening the same market after a TP/SL/manual close within the same day.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT 1 FROM positions
             WHERE user_id = $1 AND market_id = $2
               AND (
                   status = 'open'
                   OR (status = 'closed' AND closed_at >= NOW() - INTERVAL '24 hours')
               )
            """,
            user_id, market_id,
        )
    return row is not None


async def _insert_execution_queue(
    *,
    user_id: UUID,
    strategy_name: str,
    market_id: str,
    side: str,
    publication_id: UUID | None,
    suggested_size_usdc: Decimal,
    final_size_usdc: Decimal,
    idempotency_key: str,
    chosen_mode: str,
) -> bool:
    """Insert execution queue entry.  Returns True on new insert, False on conflict."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO execution_queue
                (user_id, strategy_name, market_id, side, publication_id,
                 suggested_size_usdc, final_size_usdc, idempotency_key,
                 chosen_mode, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'queued')
            ON CONFLICT (user_id, publication_id) WHERE publication_id IS NOT NULL
            DO NOTHING
            RETURNING id
            """,
            user_id, strategy_name, market_id, side, publication_id,
            suggested_size_usdc, final_size_usdc, idempotency_key, chosen_mode,
        )
    return row is not None


async def _mark_executed(
    user_id: UUID,
    publication_id: UUID | None,
    idempotency_key: str,
) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE execution_queue
               SET status = 'executed', executed_at = NOW()
             WHERE user_id = $1
               AND ($2::uuid IS NULL OR publication_id = $2)
               AND idempotency_key = $3
               AND status = 'queued'
            """,
            user_id, publication_id, idempotency_key,
        )


async def _mark_failed(
    user_id: UUID,
    publication_id: UUID | None,
    idempotency_key: str,
    error: str,
) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE execution_queue
               SET status = 'failed', error_detail = $4, executed_at = NOW()
             WHERE user_id = $1
               AND ($2::uuid IS NULL OR publication_id = $2)
               AND idempotency_key = $3
               AND status = 'queued'
            """,
            user_id, publication_id, idempotency_key, error[:500],
        )


# ---------------------------------------------------------------------------
# Context builders
# ---------------------------------------------------------------------------


def _build_user_context(row: dict[str, Any]) -> UserContext:
    _alloc = row.get("capital_allocation_pct")
    allocation = float(_alloc if _alloc is not None else 0.10)
    allocation = max(0.0, min(1.0, allocation))
    sub_account_id = str(row.get("sub_account_id") or row["user_id"])
    return UserContext(
        user_id=str(row["user_id"]),
        sub_account_id=sub_account_id,
        risk_profile=str(row.get("resolved_profile") or "balanced"),
        capital_allocation_pct=allocation,
        available_balance_usdc=float(row.get("balance_usdc") or 0.0),
    )


def _build_market_filters() -> MarketFilters:
    # Permissive defaults — risk gate enforces liquidity floor; category
    # filter and blacklist are opt-in extensions reserved for a future lane.
    return MarketFilters(
        categories=[],
        min_liquidity=0.0,
        max_time_to_resolution_days=365,
        blacklisted_market_ids=[],
    )


def _build_idempotency_key(
    user_id: UUID,
    market_id: str,
    side: str,
    publication_id: UUID | None,  # retained for signature compat; no longer in hash
) -> str:
    # UTC calendar day prevents same-day re-entry on the same market.
    # Without this, distinct publication_ids for the same market produce distinct
    # keys, each passing the 30-min gate independently → duplicate open positions.
    # Cross-day re-entry is intentional — new trading day = new opportunity.
    # Explicit UTC (not date.today()) keeps rotation stable across all host timezones.
    raw = f"{user_id}:{market_id}:{side}:{datetime.now(timezone.utc).date().isoformat()}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:32]
    return f"sf:{digest}"


def _build_trade_signal(
    *,
    row: dict[str, Any],
    cand: SignalCandidate,
    market: dict[str, Any],
    idempotency_key: str,
) -> TradeSignal:
    """Build a typed TradeSignal from scan-loop data for TradeEngine.execute()."""
    _side = cand.side.lower()
    if _side == "no":
        _primary, _fallback = market.get("no_price"), market.get("yes_price")
    else:
        _primary, _fallback = market.get("yes_price"), market.get("no_price")
    # Use is-not-None so a cached price of exactly 0 is not discarded.
    _price = float(
        _primary if _primary is not None else (_fallback if _fallback is not None else 0.5)
    )
    return TradeSignal(
        user_id=UUID(str(row["user_id"])),
        telegram_user_id=int(row["telegram_user_id"]),
        access_tier=int(row["access_tier"]),
        auto_trade_on=bool(row["auto_trade_on"]),
        paused=bool(row["paused"]),
        market_id=cand.market_id,
        market_question=str(market.get("question") or ""),
        yes_token_id=market.get("yes_token_id"),
        no_token_id=market.get("no_token_id"),
        side=_side,
        proposed_size_usdc=Decimal(str(cand.suggested_size_usdc)),
        price=_price,
        market_liquidity=float(market.get("liquidity_usdc") or 0.0),
        market_status=str(market.get("status") or ""),
        idempotency_key=idempotency_key,
        strategy_type=cand.strategy_name,
        risk_profile=str(row.get("resolved_profile") or "balanced"),
        trading_mode=str(row.get("trading_mode") or "paper"),
        signal_ts=cand.signal_ts,
        edge_bps=None,
        tp_pct=float(row["tp_pct"]) if row.get("tp_pct") is not None else None,
        sl_pct=float(row["sl_pct"]) if row.get("sl_pct") is not None else None,
        daily_loss_override=(
            float(row["daily_loss_override"])
            if row.get("daily_loss_override") is not None
            else None
        ),
    )


# ---------------------------------------------------------------------------
# Per-candidate processing
# ---------------------------------------------------------------------------


async def _process_candidate(
    row: dict[str, Any],
    cand: SignalCandidate,
) -> None:
    user_id = UUID(str(row["user_id"]))
    side = cand.side.lower()  # execution engines compare lowercase; normalize once here
    pub_id_raw = cand.metadata.get("publication_id")
    pub_uuid: UUID | None = None
    if pub_id_raw:
        try:
            pub_uuid = UUID(str(pub_id_raw))
        except (TypeError, ValueError):
            pass

    log = logger.bind(
        user_id=str(user_id),
        market_id=cand.market_id,
        side=side,
        strategy=_STRATEGY_NAME,
        publication_id=str(pub_uuid) if pub_uuid else None,
    )

    # 0. Crash-recovery resume — a prior tick inserted a 'queued' row but
    #    crashed before the paper engine completed. Re-running the gate would
    #    fail at step 10 (idempotency_key already recorded for 30 min) or
    #    step 9 (signal stale after 4h / SIGNAL_STALE_SECONDS=14400), so router_execute is called
    #    directly from the stored row. This is the ONLY direct router call
    #    in this module; all normal execution paths go through TradeEngine.
    if pub_uuid is not None:
        try:
            stale = await _load_stale_queued_row(user_id, pub_uuid)
        except Exception as exc:
            log.warning("stale_queue_check_failed", error=str(exc))
            stale = None
        if stale is not None:
            if await kill_switch_is_active():
                log.info("scan_outcome", outcome="skipped_kill_switch")
                return  # leave row as 'queued' — retry when switch is off
            stale_market = await _load_market(stale["market_id"])
            if stale_market is None:
                log.info("scan_outcome", outcome="skipped_market_not_synced")
                return
            _stale_side = str(stale["side"])
            if _stale_side == "no":
                _sp, _sf = stale_market.get("no_price"), stale_market.get("yes_price")
            else:
                _sp, _sf = stale_market.get("yes_price"), stale_market.get("no_price")
            _stale_price = float(
                _sp if _sp is not None else (_sf if _sf is not None else 0.5)
            )
            _stale_idem = str(stale["idempotency_key"])
            _stale_size = Decimal(str(stale["final_size_usdc"]))
            _tp = float(row["tp_pct"]) if row.get("tp_pct") is not None else None
            _sl = float(row["sl_pct"]) if row.get("sl_pct") is not None else None
            try:
                await router_execute(
                    chosen_mode=str(stale["chosen_mode"]),
                    user_id=user_id,
                    telegram_user_id=int(row["telegram_user_id"]),
                    access_tier=int(row["access_tier"]),
                    market_id=stale["market_id"],
                    market_question=str(stale_market.get("question") or ""),
                    yes_token_id=stale_market.get("yes_token_id"),
                    no_token_id=stale_market.get("no_token_id"),
                    side=_stale_side,
                    size_usdc=_stale_size,
                    price=_stale_price,
                    idempotency_key=_stale_idem,
                    strategy_type=_STRATEGY_NAME,
                    tp_pct=_tp,
                    sl_pct=_sl,
                    trading_mode=str(row.get("trading_mode") or "paper"),
                )
                await _mark_executed(user_id, pub_uuid, _stale_idem)
                log.info(
                    "scan_outcome",
                    outcome="resumed",
                    mode=stale["chosen_mode"],
                    size=str(_stale_size),
                )
            except Exception as exc:
                err_str = f"{type(exc).__name__}: {exc}"
                log.error("scan_outcome", outcome="failed", error=err_str)
                try:
                    await _mark_failed(user_id, pub_uuid, _stale_idem, err_str)
                except Exception as mark_exc:
                    log.warning("exec_queue_mark_failed_error", error=str(mark_exc))
            return

    # 1. Permanent dedup — skip if execution_queue already has this row.
    if pub_uuid is not None:
        try:
            already = await _publication_already_queued(user_id, pub_uuid)
        except Exception as exc:
            log.warning("exec_queue_precheck_failed", error=str(exc))
            already = False
        if already:
            log.info("scan_outcome", outcome="skipped_dedup")
            return

    # 1b. Open-position market dedup — skip if user already holds an open
    #     position on this market_id. Closes the race window between concurrent
    #     ticks that both clear gate step 10 (orders-table dedup) before either
    #     has committed its position row. Crash-recovery resumes above this
    #     check so stale 'queued' rows are not blocked.
    try:
        if await _has_open_position_for_market(user_id, cand.market_id):
            log.info("scan_outcome", outcome="skipped_open_position_exists",
                     market_id=cand.market_id,
                     message="duplicate skipped — open position exists for market")
            return
    except Exception as exc:
        log.warning("open_position_market_check_failed", error=str(exc))
        # On DB error fall through — gate step 10 remains the safety net.

    # 1c. Signal freshness gate — reject publication-backed signals older than
    #     _MAX_SIGNAL_AGE_SECONDS. signal_publications.expires_at allows 4h for
    #     feed UI history; the execution engine enforces a tighter window so it
    #     never fills at a 3-hour-old market price that has already moved past
    #     the TP target. Gate is skipped for lib-strategy candidates (pub_uuid
    #     is None) because those always carry signal_ts=now (see
    #     lib_strategy_runner.py) and must not be affected by user processing order.
    if pub_uuid is not None:
        _signal_age = (datetime.now(timezone.utc) - cand.signal_ts).total_seconds()
        if _signal_age > _MAX_SIGNAL_AGE_SECONDS:
            log.info(
                "scan_outcome",
                outcome="skipped_signal_stale",
                age_seconds=round(_signal_age),
                threshold=_MAX_SIGNAL_AGE_SECONDS,
                message=f"Signal too old ({round(_signal_age)}s > {_MAX_SIGNAL_AGE_SECONDS}s threshold)",
            )
            return

    # 2. Market lookup.
    market = await _load_market(cand.market_id)
    if market is None:
        log.info("scan_outcome", outcome="skipped_market_not_synced")
        return

    # 2b. Live price divergence guard — fetch live price and compare against
    #     the cached DB price. Skips candidates where DB price is so stale
    #     that a fill would be unrealistic (entry << market). Side-aware:
    #     uses no_price/outcomePrices[1] for NO signals. Falls through
    #     silently on any API/network error so a Gamma outage does not block
    #     all trading.
    if pub_uuid is not None:  # only publication-backed signals; lib strategies use fresh prices
        _price_key = "no_price" if side == "no" else "yes_price"
        _db_price = float(market.get(_price_key) or 0.0)
        if _db_price > 0:
            try:
                _live_price = await _polymarket.get_live_market_price(cand.market_id, side)
                if _live_price is not None and _live_price > 0 and (_live_price / _db_price) > _MAX_PRICE_DIVERGENCE_RATIO:
                    log.info(
                        "scan_outcome",
                        outcome="skipped_price_moved",
                        db_price=_db_price,
                        live_price=_live_price,
                        ratio=round(_live_price / _db_price, 2),
                        threshold=_MAX_PRICE_DIVERGENCE_RATIO,
                        message=f"Price moved: DB={_db_price:.4f} live={_live_price:.4f} ratio={_live_price / _db_price:.1f}x > {_MAX_PRICE_DIVERGENCE_RATIO}x",
                    )
                    return
            except Exception as exc:
                log.debug("price_divergence_check_failed", error=str(exc))
                # Fall through — don't block trading on API error

    # 2c. Liquidity filter — skip markets below the user's configured threshold.
    min_liquidity = float(row.get("min_liquidity_threshold") or 0.0)
    if min_liquidity > 0:
        market_liquidity = float(market.get("liquidity_usdc") or 0.0)
        if market_liquidity < min_liquidity:
            log.info(
                "scan_outcome",
                outcome="skipped_liquidity",
                market_liquidity=market_liquidity,
                threshold=min_liquidity,
                message=f"Skipped: liquidity ${market_liquidity:.0f} below threshold ${min_liquidity:.0f}",
            )
            return

    # 3. Build TradeSignal — typed contract for TradeEngine (gate + paper fill).
    idem_key = _build_idempotency_key(user_id, cand.market_id, side, pub_uuid)
    try:
        signal = _build_trade_signal(
            row=row, cand=cand, market=market, idempotency_key=idem_key,
        )
    except Exception as exc:
        log.warning("trade_signal_build_failed", error=str(exc))
        return

    # 4. Execute through TradeEngine — risk gate (13 steps) is mandatory inside
    #    the engine; router_execute is never called directly on this path.
    try:
        result: TradeResult = await _engine.execute(signal)
    except Exception as exc:
        err_str = f"{type(exc).__name__}: {exc}"
        log.error("scan_outcome", outcome="failed", error=err_str)
        return

    if not result.approved:
        log.info(
            "scan_outcome",
            outcome="rejected",
            reason=result.rejection_reason,
            step=result.failed_gate_step,
        )
        return

    # 5. Record in execution_queue — post-execution audit + permanent dedup anchor.
    #    On conflict (concurrent tick filled first): skip; paper engine idempotency
    #    key ensures the second call returned mode="duplicate".
    final_size = result.final_size_usdc or signal.proposed_size_usdc
    if result.mode != "duplicate":
        try:
            inserted = await _insert_execution_queue(
                user_id=user_id,
                strategy_name=cand.strategy_name,
                market_id=cand.market_id,
                side=side,
                publication_id=pub_uuid,
                suggested_size_usdc=signal.proposed_size_usdc,
                final_size_usdc=final_size,
                idempotency_key=idem_key,
                chosen_mode=result.chosen_mode or "paper",
            )
        except Exception as exc:
            log.warning("exec_queue_insert_failed", error=str(exc))
            inserted = False
        if inserted:
            try:
                await _mark_executed(user_id, pub_uuid, idem_key)
            except Exception as exc:
                log.warning("exec_queue_mark_executed_failed", error=str(exc))
        log.info(
            "scan_outcome",
            outcome="accepted",
            mode=result.chosen_mode,
            size=str(final_size),
        )
    else:
        log.info("scan_outcome", outcome="duplicate", mode=result.chosen_mode)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def _fetch_markets_for_lib_strategies() -> list[dict]:
    """Fetch active market list from Gamma API for lib strategy scans.

    Returns empty list on failure — lib strategies handle empty input gracefully.
    """
    try:
        return await _polymarket.get_markets(limit=200)
    except Exception as exc:
        logger.warning("lib_strategy_market_fetch_failed", error=str(exc))
        return []


async def run_once() -> None:
    """Run one tick of the lib-strategy scan loop for all enrolled users.

    Two-phase execution:
      Phase A — run each enabled lib strategy once per tick against the shared
                market list; collect candidates keyed by strategy_name.
      Phase B — for each enrolled user, filter candidates by their active_preset
                via _preset_allows(); call _process_candidate for each match.

    Each user is processed independently — an exception for one user does
    not prevent other users from being scanned on the same tick.
    """
    try:
        users = await _load_enrolled_users()
    except Exception as exc:
        logger.error("signal_scan_load_users_failed", error=str(exc))
        return

    await _event_bus.emit("pipeline.strategy_scan_started", user_count=len(users))

    if not users:
        return

    # Phase A: fetch markets once, run each lib strategy, collect by name.
    markets = await _fetch_markets_for_lib_strategies()
    all_candidates: dict[str, list[SignalCandidate]] = {}
    strategies_to_run = list(ENABLED_STRATEGIES) + list(DEFERRED_STRATEGIES)
    for lib_name in strategies_to_run:
        try:
            cands = await asyncio.get_event_loop().run_in_executor(
                None, run_lib_strategy, lib_name, markets, {}
            )
            all_candidates[lib_name] = cands
        except Exception as exc:
            logger.warning("lib_strategy_run_failed", strategy=lib_name, error=str(exc))
            all_candidates[lib_name] = []

    total_signals = sum(len(v) for v in all_candidates.values())
    logger.info("lib_strategy_phase_a_done", strategies=len(strategies_to_run),
                total_signals=total_signals)
    await _event_bus.emit(
        "pipeline.strategy_scan_done",
        strategy_count=len(strategies_to_run),
        total_signals=total_signals,
    )

    # Phase B: distribute signals to users based on their active_preset.
    candidates_processed = 0
    candidates_errored = 0
    for row in users:
        active_preset = row.get("active_preset")
        user_log = logger.bind(user_id=str(row["user_id"]), preset=active_preset)

        for lib_name, candidates in all_candidates.items():
            if not _preset_allows(active_preset, lib_name):
                continue
            for cand in candidates:
                try:
                    await _process_candidate(row, cand)
                    candidates_processed += 1
                except Exception as exc:
                    candidates_errored += 1
                    user_log.error(
                        "signal_scan_candidate_unhandled",
                        market_id=cand.market_id,
                        strategy=lib_name,
                        error=str(exc),
                    )

        # Phase C: evaluate signal_publications feed for this user.
        # Uses signal_evaluator which reads user's subscribed feeds and
        # returns SignalCandidates with metadata["publication_id"] set.
        # _process_candidate handles dedup via (user_id, publication_id) unique key.
        try:
            user_ctx = _build_user_context(row)
            market_filters = _build_market_filters()
            feed_candidates = await evaluate_publications_for_user(
                user_context=user_ctx,
                market_filters=market_filters,
                strategy_name=_STRATEGY_NAME,
            )
        except Exception as exc:
            user_log.warning("signal_feed_eval_failed", error=str(exc))
            feed_candidates = []

        for cand in feed_candidates:
            try:
                await _process_candidate(row, cand)
                candidates_processed += 1
            except Exception as exc:
                candidates_errored += 1
                user_log.error(
                    "signal_scan_feed_candidate_unhandled",
                    market_id=cand.market_id,
                    error=str(exc),
                )

    await _event_bus.emit(
        "pipeline.scan_completed",
        user_count=len(users),
        candidates_processed=candidates_processed,
        candidates_errored=candidates_errored,
    )


__all__ = ["run_once"]
