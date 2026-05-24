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
import json
import uuid as _uuid_mod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog

from ...core import event_bus as _event_bus
from ...database import get_pool
from ...domain.execution.router import execute as router_execute
from ...domain.ops.kill_switch import is_active as kill_switch_is_active
from ...domain.risk.constants import PROFILES
from ...domain.strategy.registry import StrategyRegistry
from ...domain.strategy.types import MarketFilters, SignalCandidate, UserContext
from ...integrations import polymarket as _polymarket
from ...integrations.polymarket import get_live_market_price
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

# Maximum allowed drift between a signal's target_price and the current
# cached market price before the candidate is rejected. 25% tolerates
# normal intra-day volatility while blocking 300–1000% stale fills.
# No API call required — uses market data already loaded in step 2.
_MAX_TARGET_DRIFT_PCT: float = 0.25  # 25%

# ---------------------------------------------------------------------------
# Preset → lib strategy name mapping
# ---------------------------------------------------------------------------

_LIB_STRATEGY_NAMES: frozenset[str] = frozenset(ENABLED_STRATEGIES) | frozenset(DEFERRED_STRATEGIES)

# Domain strategies wired into the scan loop alongside lib/ strategies.
# These live in domain/strategy/strategies/ and are registered via
# bootstrap_default_strategies(). The scan loop runs them explicitly per user
# when the active_preset permits. Crypto-only eligibility for the scalper
# lives in domain/strategy/eligibility.py and is enforced INSIDE
# ConfluenceScalperStrategy.scan(), so emitted candidates already satisfy
# the asset whitelist when they reach this loop.
_CONFLUENCE_SCALPER_NAME = "confluence_scalper"

_PRESET_ALLOWED: dict[str | None, frozenset[str]] = {
    "whale_mirror":        frozenset({"whale_tracking"}),
    "trend_breakout":      frozenset({"trend_breakout"}),
    "contrarian":          frozenset({"momentum"}),
    "value_hunter":        frozenset({"value_investor"}),
    "close_sweep":         frozenset({"expiration_timing"}),
    "pair_arb":            frozenset({"pair_arb"}),
    "ensemble":            frozenset({"ensemble", "trend_breakout", "momentum", "value_investor"}),
    "confluence_scalper":  frozenset({_CONFLUENCE_SCALPER_NAME}),
    "full_auto":           _LIB_STRATEGY_NAMES | frozenset({_CONFLUENCE_SCALPER_NAME}),
    None:                  _LIB_STRATEGY_NAMES | frozenset({_CONFLUENCE_SCALPER_NAME}),  # no preset set → full_auto behaviour
}


# ---------------------------------------------------------------------------
# Scan run telemetry
# ---------------------------------------------------------------------------


@dataclass
class ScanTelemetry:
    """Accumulates per-scan-run observability counts for the scan_runs table."""

    users_evaluated: int = 0
    markets_seen: int = 0
    markets_eligible: int = 0
    candidates_emitted: int = 0
    risk_approved: int = 0
    risk_rejected: int = 0
    paper_orders_created: int = 0
    positions_created: int = 0
    snapshots_written: int = 0
    skip_breakdown: dict[str, int] = field(default_factory=dict)
    zero_reason_breakdown: dict[str, int] = field(default_factory=dict)
    rejection_breakdown: dict[str, int] = field(default_factory=dict)

    def record_skip(self, reason: str) -> None:
        self.skip_breakdown[reason] = self.skip_breakdown.get(reason, 0) + 1

    def record_zero_reason(self, strategy: str, reason: str) -> None:
        key = f"{strategy}:{reason}"
        self.zero_reason_breakdown[key] = self.zero_reason_breakdown.get(key, 0) + 1

    def record_rejection(self, step: int | None, reason: str) -> None:
        key = f"step_{step}_{reason}" if step is not None else f"unknown_{reason}"
        self.rejection_breakdown[key] = self.rejection_breakdown.get(key, 0) + 1
        self.risk_rejected += 1

    def record_approved(self) -> None:
        self.risk_approved += 1
        self.paper_orders_created += 1
        self.positions_created += 1


def _preset_allows(active_preset: str | None, strategy_name: str) -> bool:
    """Return True if user's active_preset permits signals from strategy_name."""
    return strategy_name in _PRESET_ALLOWED.get(active_preset, _LIB_STRATEGY_NAMES)


def _coerce_jsonb(val: object, fallback: dict | list | None = None) -> dict | list:
    """asyncpg may return JSONB columns as str — coerce to dict/list.

    Narrows to the same shape as ``fallback`` (dict or list). JSON scalars
    (e.g. ``'"balanced"'`` → string, ``'1'`` → int) return ``fallback`` so a
    malformed user_settings.strategy_params row cannot leak a string into
    ``strategy.initialize()`` and trigger ``ValueError: dictionary update
    sequence element #0 has length 1; 2 is required``.
    """
    if fallback is None:
        fallback = {}
    expected_type = type(fallback)  # dict or list
    if val is None:
        return fallback
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
        except (json.JSONDecodeError, ValueError):
            return fallback
        return parsed if isinstance(parsed, expected_type) else fallback
    if isinstance(val, expected_type):
        return val
    return fallback

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
                u.role,
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
                COALESCE(s.min_liquidity, 0)         AS min_liquidity_threshold,
                COALESCE(s.strategy_params, '{}'::jsonb)      AS strategy_params,
                COALESCE(s.category_filters, ARRAY[]::text[]) AS category_filters
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
# Scan run DB helpers (telemetry)
# ---------------------------------------------------------------------------


async def _insert_scan_run(
    run_id: str,
    *,
    strategies_loaded: int,
    live_trading: bool,
    mode: str,
) -> None:
    """Insert a scan_runs row at tick start. Non-fatal on error."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO scan_runs (id, strategies_loaded, live_trading, mode)
                VALUES ($1::uuid, $2, $3, $4)
                ON CONFLICT (id) DO NOTHING
                """,
                run_id, strategies_loaded, live_trading, mode,
            )
    except Exception as exc:
        logger.warning("scan_run_insert_failed", run_id=run_id, error=str(exc))


async def _finish_scan_run(run_id: str, tel: ScanTelemetry) -> None:
    """UPDATE the scan_runs row at tick end with full telemetry. Non-fatal on error."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE scan_runs SET
                    finished_at           = NOW(),
                    users_evaluated       = $2,
                    markets_seen          = $3,
                    markets_eligible      = $4,
                    candidates_emitted    = $5,
                    risk_approved         = $6,
                    risk_rejected         = $7,
                    paper_orders_created  = $8,
                    positions_created     = $9,
                    snapshots_written     = $10,
                    skip_breakdown        = $11::jsonb,
                    zero_reason_breakdown = $12::jsonb,
                    rejection_breakdown   = $13::jsonb
                WHERE id = $1::uuid
                """,
                run_id,
                tel.users_evaluated,
                tel.markets_seen,
                tel.markets_eligible,
                tel.candidates_emitted,
                tel.risk_approved,
                tel.risk_rejected,
                tel.paper_orders_created,
                tel.positions_created,
                tel.snapshots_written,
                json.dumps(tel.skip_breakdown),
                json.dumps(tel.zero_reason_breakdown),
                json.dumps(tel.rejection_breakdown),
            )
    except Exception as exc:
        logger.warning("scan_run_finish_failed", run_id=run_id, error=str(exc))


async def fetch_latest_scan_run() -> dict[str, Any] | None:
    """Return the most recent ``scan_runs`` row as a dict, or None.

    Read-only observability accessor for the real feed-eval engine (this
    module). The Telegram operator panel reads this instead of the legacy
    ``run_signal_scan`` job_runs row, which only loads copy_trade and always
    reports zero candidates. Mirrors the column set served by
    ``api/admin.py`` GET /scan/last.
    """
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, started_at, finished_at,
                       users_evaluated, markets_seen, markets_eligible,
                       strategies_loaded, candidates_emitted,
                       risk_approved, risk_rejected,
                       paper_orders_created, positions_created, snapshots_written,
                       skip_breakdown, zero_reason_breakdown, rejection_breakdown,
                       mode, live_trading
                  FROM scan_runs
                 ORDER BY started_at DESC
                 LIMIT 1
                """
            )
    except Exception as exc:
        logger.warning("scan_run_fetch_latest_failed", error=str(exc))
        return None
    return dict(row) if row else None


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


def _build_market_filters(profile: str) -> MarketFilters:
    # Resolution-horizon and liquidity floor are derived from the user's risk
    # profile (PROFILES in domain/risk/constants). Conservative=7d / Balanced=30d
    # / Aggressive=90d. This stops the scanner from entering far-dated futures
    # (e.g. championship winners resolving months out) that never hit TP/SL and
    # permanently occupy a concurrent-trade slot. Category filter and blacklist
    # remain opt-in extensions reserved for a future lane.
    preset = PROFILES.get((profile or "balanced").lower(), PROFILES["balanced"])
    return MarketFilters(
        categories=[],
        min_liquidity=float(preset["min_liquidity"]),
        max_time_to_resolution_days=int(preset["max_days"]),
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
    live_price_override: float | None = None,
) -> TradeSignal:
    """Build a typed TradeSignal from scan-loop data for TradeEngine.execute()."""
    _side = cand.side.lower()
    if live_price_override is not None:
        # Use live price from Gamma/CLOB — same source as exit_watcher.
        # This keeps paper entry consistent with exit evaluation so
        # return_pct reflects real market movement, not a DB cache gap.
        # is-not-None (not > 0) so a live price of exactly 0.0 is honoured.
        _price = live_price_override
    else:
        # Fallback: cached DB price when live fetch unavailable.
        if _side == "no":
            _primary, _fallback = market.get("no_price"), market.get("yes_price")
        else:
            _primary, _fallback = market.get("yes_price"), market.get("no_price")
        _price = float(
            _primary if _primary is not None else (_fallback if _fallback is not None else 0.5)
        )
    return TradeSignal(
        user_id=UUID(str(row["user_id"])),
        telegram_user_id=int(row["telegram_user_id"]),
        role=str(row.get("role") or "user"),
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
    telemetry: ScanTelemetry | None = None,
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
                if telemetry is not None:
                    telemetry.record_skip("skipped_kill_switch")
                return  # leave row as 'queued' — retry when switch is off
            stale_market = await _load_market(stale["market_id"])
            if stale_market is None:
                log.info("scan_outcome", outcome="skipped_market_not_synced")
                if telemetry is not None:
                    telemetry.record_skip("skipped_market_not_synced")
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
                    role=str(row.get("role") or "user"),
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
            if telemetry is not None:
                telemetry.record_skip("skipped_dedup")
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
            if telemetry is not None:
                telemetry.record_skip("skipped_open_position_exists")
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
            if telemetry is not None:
                telemetry.record_skip("skipped_signal_stale")
            return

    # 2. Market lookup.
    market = await _load_market(cand.market_id)
    if market is None:
        log.info("scan_outcome", outcome="skipped_market_not_synced")
        if telemetry is not None:
            telemetry.record_skip("skipped_market_not_synced")
        return

    # 2b. Target price drift guard — compare signal's target_price against
    #     current cached DB price for this side. If drift exceeds
    #     _MAX_TARGET_DRIFT_PCT the market has moved too far since the
    #     signal was published; executing would produce an unrealistic fill.
    #     Guard only applies to feed signals (pub_uuid is not None) because
    #     lib-strategy candidates always carry fresh prices (signal_ts=now).
    #     Uses same primary→fallback→0.5 resolution as _build_trade_signal so
    #     the guard evaluates the identical price the trade engine will use.
    if pub_uuid is not None:
        _target = float(cand.metadata.get("target_price") or 0.0)
        _price_primary = market.get(f"{side}_price")
        _price_fallback = market.get("no_price" if side == "yes" else "yes_price")
        _current = float(
            _price_primary if _price_primary is not None
            else (_price_fallback if _price_fallback is not None else 0.5)
        )
        if _target > 0:
            _drift = abs(_current - _target) / _target
            if _drift > _MAX_TARGET_DRIFT_PCT:
                log.info(
                    "scan_outcome",
                    outcome="skipped_price_drifted",
                    side=side,
                    target_price=_target,
                    current_price=_current,
                    drift_pct=round(_drift * 100, 1),
                    threshold_pct=round(_MAX_TARGET_DRIFT_PCT * 100, 1),
                    message=(
                        f"Price drifted {round(_drift * 100, 1)}% "
                        f"(target={_target:.4f} current={_current:.4f}) "
                        f"> {round(_MAX_TARGET_DRIFT_PCT * 100)}% threshold"
                    ),
                )
                if telemetry is not None:
                    telemetry.record_skip("skipped_price_drifted")
                return

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
            if telemetry is not None:
                telemetry.record_skip("skipped_liquidity")
            return

    # 3. Build TradeSignal — typed contract for TradeEngine (gate + paper fill).
    idem_key = _build_idempotency_key(user_id, cand.market_id, side, pub_uuid)

    # 3b. Fetch live price so paper fill uses same source as exit_watcher.
    #     Falls back to DB cached price silently on any API error so a
    #     Gamma outage does not block all trading.
    _live_fill_price: float | None = None
    try:
        _live_fill_price = await get_live_market_price(cand.market_id, side)
    except Exception as exc:
        log.warning("live_price_fetch_failed", market_id=cand.market_id, error=str(exc))

    try:
        signal = _build_trade_signal(
            row=row, cand=cand, market=market, idempotency_key=idem_key,
            live_price_override=_live_fill_price,
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
        if telemetry is not None:
            telemetry.record_rejection(result.failed_gate_step, result.rejection_reason or "unknown")
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
        logger.info(
            "paper_execution",
            market_id=cand.market_id,
            side=side,
            size=str(final_size),
            mode=result.chosen_mode,
            strategy=cand.strategy_name,
        )
        log.info(
            "scan_outcome",
            outcome="accepted",
            mode=result.chosen_mode,
            size=str(final_size),
        )
        if telemetry is not None:
            telemetry.record_approved()
    else:
        log.info("scan_outcome", outcome="duplicate", mode=result.chosen_mode)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _filter_markets_by_category(markets: list[dict], filters: list[str]) -> list[dict]:
    """Filter Gamma market dicts by category. Empty filters = all markets."""
    if not filters:
        return markets
    lower = {f.lower() for f in filters}
    result = []
    for m in markets:
        cat = (
            m.get("category")
            or m.get("groupItemTitle")
            or m.get("slug", "")
        ).lower()
        if any(f in cat for f in lower):
            result.append(m)
    return result


async def _fetch_markets_for_lib_strategies() -> list[dict]:
    """Fetch active markets from Gamma /events, annotated with event-level tags.

    Uses get_events_with_markets() so each returned dict carries a ``category``
    field built from the parent event's tag labels (e.g. ``"crypto finance"``).
    _filter_markets_by_category() can then correctly match dashboard categories
    (Politics/Sports/Crypto/Finance/…) instead of substring-matching the raw
    event slug that Gamma /markets returns in ``groupItemTitle`` / ``slug``.

    Returns empty list on failure — lib strategies handle empty input gracefully.
    """
    try:
        return await _polymarket.get_events_with_markets(limit=200)
    except Exception as exc:
        logger.warning("lib_strategy_market_fetch_failed", error=str(exc))
        return []


async def run_once() -> None:
    """Run one tick of the lib-strategy scan loop for all enrolled users.

    Per-user execution:
      Markets are fetched once from Gamma API then filtered per-user by
      category_filters before being passed to each lib strategy. strategy_params
      from user_settings are forwarded as config so strategies apply user-specific
      thresholds (drop_threshold, min_liquidity, etc.).

    Each user is processed independently — an exception for one user does
    not prevent other users from being scanned on the same tick.
    """
    from ...config import get_settings as _get_settings
    from ...domain.strategy.registry import StrategyRegistry as _Registry

    try:
        _live_trading: bool = bool(_get_settings().ENABLE_LIVE_TRADING)
    except Exception:
        _live_trading = False
    _mode: str = "LIVE" if _live_trading else "PAPER"

    # Count all strategies known to the process (lib + domain registry).
    _lib_count = len(ENABLED_STRATEGIES) + len(DEFERRED_STRATEGIES)
    _domain_count = len(_Registry.instance().list_available())
    _strategies_loaded = _lib_count + _domain_count

    tel = ScanTelemetry()
    run_id: str = str(_uuid_mod.uuid4())

    await _insert_scan_run(
        run_id,
        strategies_loaded=_strategies_loaded,
        live_trading=_live_trading,
        mode=_mode,
    )

    logger.info("signal_scan_job_started", scan_run_id=run_id, strategies_loaded=_strategies_loaded)

    try:
        users = await _load_enrolled_users()
    except Exception as exc:
        logger.error("signal_scan_load_users_failed", error=str(exc))
        await _finish_scan_run(run_id, tel)
        return

    await _event_bus.emit("pipeline.strategy_scan_started", user_count=len(users))

    if not users:
        await _finish_scan_run(run_id, tel)
        return

    markets = await _fetch_markets_for_lib_strategies()
    strategies_to_run = list(ENABLED_STRATEGIES) + list(DEFERRED_STRATEGIES)

    tel.users_evaluated = len(users)
    tel.markets_seen = len(markets)

    # Hoist the domain confluence_scalper instance once per tick — registry
    # state is process-wide and the lookup does not depend on per-user data.
    try:
        confluence_strat = StrategyRegistry.instance().get(_CONFLUENCE_SCALPER_NAME)
    except KeyError:
        confluence_strat = None
        logger.debug("confluence_scalper_not_registered")

    candidates_processed = 0
    candidates_errored = 0
    lib_total_signals = 0
    confluence_signals = 0

    for row in users:
        active_preset = row.get("active_preset")
        category_filters: list[str] = list(row.get("category_filters") or [])
        strategy_params: dict = _coerce_jsonb(row.get("strategy_params"), {})
        user_log = logger.bind(user_id=str(row["user_id"]), preset=active_preset)

        # Filter market list to user's chosen categories (empty = all markets).
        user_markets = _filter_markets_by_category(markets, category_filters)

        for lib_name in strategies_to_run:
            if not _preset_allows(active_preset, lib_name):
                continue
            # Per-strategy params come from user_settings.strategy_params (JSONB,
            # user-controlled). _coerce_jsonb guarantees the top-level value is a
            # dict, but a malformed row (e.g. {"momentum_reversal": "balanced"})
            # can still hold a non-dict sub-value. Passing that into the lib
            # strategy as config would raise ValueError: dictionary update
            # sequence element #0 has length 1; 2 is required. Drop to {} + log.
            lib_params = strategy_params.get(lib_name, {})
            if not isinstance(lib_params, dict):
                user_log.warning(
                    "signal_scan_strategy_params_not_dict",
                    strategy=lib_name,
                    got=type(lib_params).__name__,
                )
                lib_params = {}
            config = {"strategy_params": lib_params}
            try:
                cands: list[SignalCandidate] = await asyncio.get_event_loop().run_in_executor(
                    None, run_lib_strategy, lib_name, user_markets, config
                )
            except Exception as exc:
                user_log.warning("lib_strategy_run_failed", strategy=lib_name, error=str(exc))
                cands = []

            user_log.info(
                "strategy_run",
                strategy=lib_name,
                candidates_emitted=len(cands),
                zero_reason="filter_or_no_match" if not cands else None,
            )
            if not cands:
                tel.record_zero_reason(lib_name, "filter_or_no_match")

            lib_total_signals += len(cands)
            tel.candidates_emitted += len(cands)
            for cand in cands:
                try:
                    await _process_candidate(row, cand, tel)
                    candidates_processed += 1
                except Exception as exc:
                    candidates_errored += 1
                    user_log.error(
                        "signal_scan_candidate_unhandled",
                        market_id=cand.market_id,
                        strategy=lib_name,
                        error=str(exc),
                    )

        # Phase B: run domain confluence_scalper strategy when the active
        # preset permits. The strategy applies the crypto-only asset whitelist
        # inside its own market loop (see domain/strategy/eligibility.py +
        # strategies/confluence_scalper.py), so emitted candidates already
        # satisfy the gate. Non-crypto markets self-skip without affecting
        # other strategies on the same scan tick.
        if confluence_strat is not None and _preset_allows(
            active_preset, _CONFLUENCE_SCALPER_NAME
        ):
            try:
                user_ctx = _build_user_context(row)
                market_filters = _build_market_filters(user_ctx.risk_profile)
                domain_cands = await confluence_strat.scan(market_filters, user_ctx)
            except Exception as exc:
                user_log.warning("confluence_scalper_run_failed", error=str(exc))
                domain_cands = []

            confluence_signals += len(domain_cands)
            user_log.info(
                "strategy_run",
                strategy=_CONFLUENCE_SCALPER_NAME,
                candidates_emitted=len(domain_cands),
                zero_reason="filter_or_no_match" if not domain_cands else None,
            )
            if not domain_cands:
                tel.record_zero_reason(_CONFLUENCE_SCALPER_NAME, "filter_or_no_match")
            tel.candidates_emitted += len(domain_cands)
            for cand in domain_cands:
                try:
                    await _process_candidate(row, cand, tel)
                    candidates_processed += 1
                except Exception as exc:
                    candidates_errored += 1
                    user_log.error(
                        "signal_scan_candidate_unhandled",
                        market_id=cand.market_id,
                        strategy=_CONFLUENCE_SCALPER_NAME,
                        error=str(exc),
                    )

        # Phase C: evaluate signal_publications feed for this user.
        # Uses signal_evaluator which reads user's subscribed feeds and
        # returns SignalCandidates with metadata["publication_id"] set.
        # _process_candidate handles dedup via (user_id, publication_id) unique key.
        try:
            user_ctx = _build_user_context(row)
            market_filters = _build_market_filters(user_ctx.risk_profile)
            feed_candidates = await evaluate_publications_for_user(
                user_context=user_ctx,
                market_filters=market_filters,
                strategy_name=_STRATEGY_NAME,
            )
        except Exception as exc:
            user_log.warning("signal_feed_eval_failed", error=str(exc))
            feed_candidates = []

        if not feed_candidates:
            tel.record_zero_reason("signal_feed", "no_publications_eligible")
        tel.candidates_emitted += len(feed_candidates)
        for cand in feed_candidates:
            try:
                await _process_candidate(row, cand, tel)
                candidates_processed += 1
            except Exception as exc:
                candidates_errored += 1
                user_log.error(
                    "signal_scan_feed_candidate_unhandled",
                    market_id=cand.market_id,
                    error=str(exc),
                )

    logger.info(
        "scan_input",
        scan_run_id=run_id,
        users_evaluated=tel.users_evaluated,
        markets_seen=tel.markets_seen,
        strategies_loaded=_strategies_loaded,
    )
    logger.info(
        "lib_strategy_scan_done",
        scan_run_id=run_id,
        strategies=len(strategies_to_run),
        total_signals=lib_total_signals,
        confluence_signals=confluence_signals,
        candidates_emitted=tel.candidates_emitted,
        risk_approved=tel.risk_approved,
        risk_rejected=tel.risk_rejected,
        paper_orders_created=tel.paper_orders_created,
        skip_breakdown=tel.skip_breakdown,
        zero_reason_breakdown=tel.zero_reason_breakdown,
        rejection_breakdown=tel.rejection_breakdown,
    )
    await _finish_scan_run(run_id, tel)
    await _event_bus.emit(
        "pipeline.strategy_scan_done",
        strategy_count=len(strategies_to_run) + 1,  # +1 for confluence_scalper
        total_signals=lib_total_signals + confluence_signals,
    )
    await _event_bus.emit(
        "pipeline.scan_completed",
        user_count=len(users),
        candidates_processed=candidates_processed,
        candidates_errored=candidates_errored,
    )


__all__ = ["run_once", "_filter_markets_by_category"]
