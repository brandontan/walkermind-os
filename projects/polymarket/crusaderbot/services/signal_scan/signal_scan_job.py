"""P3d signal scan job — per-user signal_following scan loop + execution queue.

Pipeline (per user, per scan tick):
    1. Load users enrolled in signal_following + auto_trade_on + Tier 3+
    2. Build UserContext + MarketFilters from DB row
    3. SignalFollowingStrategy.scan() -> list[SignalCandidate]  (pure DB reads)
    4. Per candidate:
       a. execution_queue pre-check: skip if publication_id already present
       b. Build GateContext, run 13-step risk gate
       c. On approval: INSERT into execution_queue ON CONFLICT DO NOTHING
       d. Call router_execute; update queue status to executed/failed
       e. Log outcome: accepted | skipped_dedup | rejected | failed

Deduplication (dual-layer):
    Outer — execution_queue UNIQUE (user_id, publication_id) — permanent;
            prevents re-execution after a prior tick already submitted.
    Inner — idempotency_keys 30-min window (risk gate step 10) — short-circuit
            for recent risk rejections so the gate is not re-evaluated every
            30 s during a transient block (e.g. max_concurrent_trades).

Safety:
    * No activation guard mutations.
    * Risk gate is mandatory; router_execute is NEVER called without approval.
    * No HTTP fetches.  No threading — asyncio only.
    * Every exception is caught, logged, and does NOT propagate to the caller
      so one bad user/publication cannot crash the whole scan tick.
"""
from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog

from ...database import get_pool
from ...domain.execution.router import execute as router_execute
from ...domain.ops.kill_switch import is_active as kill_switch_is_active
from ...domain.risk.gate import GateContext, GateResult, evaluate as risk_evaluate
from ...domain.strategy.registry import StrategyRegistry
from ...domain.strategy.types import MarketFilters, SignalCandidate, UserContext

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STRATEGY_NAME = "signal_following"


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _load_enrolled_users() -> list[dict[str, Any]]:
    """Active users enrolled in signal_following with Tier 3+ and auto_trade_on."""
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
                COALESCE(urp.profile_name, s.risk_profile, 'balanced') AS resolved_profile
            FROM user_strategies us
            JOIN users          u   ON u.id  = us.user_id
            JOIN wallets        w   ON w.user_id = u.id
            JOIN user_settings  s   ON s.user_id = u.id
            LEFT JOIN user_risk_profile urp ON urp.user_id = u.id
            WHERE us.strategy_name = $1
              AND us.enabled        = TRUE
              AND u.auto_trade_on   = TRUE
              AND u.paused          = FALSE
              AND u.access_tier    >= 3
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
    the same idempotency_key for 30 min, and (b) gate step 9 permanently
    rejects the original signal after the 5-min staleness window expires.
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
    publication_id: UUID | None,
) -> str:
    raw = f"{user_id}:{market_id}:{side}:{publication_id or ''}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:32]
    return f"sf:{digest}"


def _build_gate_context(
    *,
    row: dict[str, Any],
    cand: SignalCandidate,
    market: dict[str, Any],
    idempotency_key: str,
) -> GateContext:
    _side = cand.side.lower()
    if _side == "no":
        _primary, _fallback = market.get("no_price"), market.get("yes_price")
    else:
        _primary, _fallback = market.get("yes_price"), market.get("no_price")
    # Use is-not-None so a cached price of exactly 0 is not discarded.
    _price = float(
        _primary if _primary is not None else (_fallback if _fallback is not None else 0.5)
    )
    return GateContext(
        user_id=UUID(str(row["user_id"])),
        telegram_user_id=int(row["telegram_user_id"]),
        access_tier=int(row["access_tier"]),
        auto_trade_on=bool(row["auto_trade_on"]),
        paused=bool(row["paused"]),
        market_id=cand.market_id,
        side=_side,
        proposed_size_usdc=Decimal(str(cand.suggested_size_usdc)),
        proposed_price=_price,
        market_liquidity=float(market.get("liquidity_usdc") or 0.0),
        market_status=str(market.get("status") or ""),
        edge_bps=None,
        signal_ts=cand.signal_ts,
        idempotency_key=idempotency_key,
        strategy_type=_STRATEGY_NAME,
        risk_profile=str(row.get("resolved_profile") or "balanced"),
        daily_loss_override=(
            float(row["daily_loss_override"])
            if row.get("daily_loss_override") is not None
            else None
        ),
        trading_mode=str(row.get("trading_mode") or "paper"),
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
    #    crashed before router_execute.  Re-running the gate would fail at
    #    step 10 (idempotency_key already recorded for 30 min) or step 9
    #    (signal stale after 5 min), so execute directly from the stored row.
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

    # 2. Market lookup.
    market = await _load_market(cand.market_id)
    if market is None:
        log.info("scan_outcome", outcome="skipped_market_not_synced")
        return

    # 3. Build idempotency key + gate context.
    idem_key = _build_idempotency_key(user_id, cand.market_id, side, pub_uuid)
    try:
        gate_ctx = _build_gate_context(
            row=row, cand=cand, market=market, idempotency_key=idem_key,
        )
    except Exception as exc:
        log.warning("gate_context_build_failed", error=str(exc))
        return

    # 4. Risk gate — mandatory before any queue insert or execution.
    try:
        result: GateResult = await risk_evaluate(gate_ctx)
    except Exception as exc:
        log.error("risk_gate_error", error=str(exc))
        return

    if not result.approved:
        log.info(
            "scan_outcome",
            outcome="rejected",
            reason=result.reason,
            step=result.failed_step,
        )
        return

    # 5. Insert execution queue entry (ON CONFLICT DO NOTHING for concurrent
    #    tick safety — the UNIQUE partial index handles the race).
    final_size = result.final_size_usdc or Decimal(str(cand.suggested_size_usdc))
    try:
        inserted = await _insert_execution_queue(
            user_id=user_id,
            strategy_name=_STRATEGY_NAME,
            market_id=cand.market_id,
            side=side,
            publication_id=pub_uuid,
            suggested_size_usdc=Decimal(str(cand.suggested_size_usdc)),
            final_size_usdc=final_size,
            idempotency_key=idem_key,
            chosen_mode=result.chosen_mode,
        )
    except Exception as exc:
        log.error("exec_queue_insert_failed", error=str(exc))
        return

    if not inserted:
        # Concurrent tick inserted first — dedup at the DB boundary.
        log.info("scan_outcome", outcome="skipped_concurrent_dedup")
        return

    # 6. Execute via router.
    tp = float(row["tp_pct"]) if row.get("tp_pct") is not None else None
    sl = float(row["sl_pct"]) if row.get("sl_pct") is not None else None
    try:
        await router_execute(
            chosen_mode=result.chosen_mode,
            user_id=user_id,
            telegram_user_id=int(row["telegram_user_id"]),
            access_tier=int(row["access_tier"]),
            market_id=cand.market_id,
            market_question=str(market.get("question") or ""),
            yes_token_id=market.get("yes_token_id"),
            no_token_id=market.get("no_token_id"),
            side=side,
            size_usdc=final_size,
            price=gate_ctx.proposed_price,
            idempotency_key=idem_key,
            strategy_type=_STRATEGY_NAME,
            tp_pct=tp,
            sl_pct=sl,
            trading_mode=str(row.get("trading_mode") or "paper"),
        )
        await _mark_executed(user_id, pub_uuid, idem_key)
        log.info(
            "scan_outcome",
            outcome="accepted",
            mode=result.chosen_mode,
            size=str(final_size),
        )
    except Exception as exc:
        err_str = f"{type(exc).__name__}: {exc}"
        log.error("scan_outcome", outcome="failed", error=err_str)
        try:
            await _mark_failed(user_id, pub_uuid, idem_key, err_str)
        except Exception as mark_exc:
            log.warning("exec_queue_mark_failed_error", error=str(mark_exc))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def run_once() -> None:
    """Run one tick of the signal_following scan loop for all enrolled users.

    Each user is processed independently — an exception for one user does
    not prevent other users from being scanned on the same tick.
    """
    try:
        users = await _load_enrolled_users()
    except Exception as exc:
        logger.error("signal_scan_load_users_failed", error=str(exc))
        return

    if not users:
        return

    reg = StrategyRegistry.instance()
    try:
        strategy = reg.get(_STRATEGY_NAME)
    except KeyError:
        logger.error("signal_scan_strategy_not_registered", strategy=_STRATEGY_NAME)
        return

    for row in users:
        user_log = logger.bind(user_id=str(row["user_id"]))
        try:
            user_ctx = _build_user_context(row)
            mkt_filters = _build_market_filters()
        except Exception as exc:
            user_log.warning("signal_scan_context_build_failed", error=str(exc))
            continue

        try:
            candidates = await strategy.scan(mkt_filters, user_ctx)
        except Exception as exc:
            user_log.warning("signal_scan_strategy_scan_failed", error=str(exc))
            continue

        for cand in candidates:
            try:
                await _process_candidate(row, cand)
            except Exception as exc:
                user_log.error(
                    "signal_scan_candidate_unhandled",
                    market_id=cand.market_id,
                    error=str(exc),
                )


__all__ = ["run_once"]
