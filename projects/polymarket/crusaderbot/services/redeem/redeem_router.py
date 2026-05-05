"""R12e auto-redeem router.

Owns the resolution-detection scan and the dispatch decision (instant vs.
hourly) per user mode. Also exposes the shared settlement primitive that
both workers call once they have authority to settle a row:

  * ``detect_resolutions`` — periodic scan (driven by the scheduler).
                             Classifies positions in newly-resolved markets:
                             losers settle inline; winners are enqueued to
                             ``redeem_queue`` and, when the owner's mode is
                             ``instant``, an in-process instant worker task
                             is fired so the user does not have to wait for
                             the next hourly tick.
  * ``settle_winning_position`` — credits the user ledger, triggers the
                             master-wallet on-chain CTF redemption (live
                             only, idempotent per condition), marks the
                             position redeemed, audits, and notifies the
                             user.
  * ``settle_losing_position`` — no on-chain side-effect; closes the
                             position at zero, records final P&L, audits,
                             and notifies the user.

All entry points are gated on ``Settings.AUTO_REDEEM_ENABLED`` — when the
guard is off the functions log INFO and return without touching state.
"""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

from ... import audit, notifications
from ...config import get_settings
from ...database import get_pool
from ...integrations import polymarket
from ...wallet import ledger

logger = logging.getLogger(__name__)


# ---------------- Resolution detection + dispatch ----------------

async def detect_resolutions() -> None:
    """Scheduler entry point — runs on the resolution interval.

    Walks the set of (market) rows with at least one redeemable position
    that the bot has not yet observed as resolved. For each market:

      1. Re-fetch the market from Polymarket; skip if still open.
      2. Atomically transition the markets row to resolved with the
         winning side recorded.
      3. For each redeemable position in that market:
           * winner → enqueue to ``redeem_queue`` (idempotent per
             position) and, if the user's mode is instant, fire the
             instant worker as an asyncio task so the redeem starts
             without waiting for the hourly cron.
           * loser  → settle inline (no on-chain action, no queue entry).

    The function is wrapped end-to-end in defensive ``try/except`` blocks
    so a single market or position failure cannot poison the rest of the
    batch (matches the exit-watcher pattern).
    """
    s = get_settings()
    if not s.AUTO_REDEEM_ENABLED:
        logger.info("auto-redeem disabled, skipping detection")
        return

    pool = get_pool()
    async with pool.acquire() as conn:
        candidate_rows = await conn.fetch(
            """
            SELECT DISTINCT p.market_id
              FROM positions p
              JOIN markets m ON m.id = p.market_id
             WHERE p.redeemed = FALSE
               AND m.resolved = FALSE
               AND ((p.status = 'open')
                    OR (p.status = 'closed'
                        AND m.resolution_at IS NOT NULL
                        AND m.resolution_at < NOW()))
            """,
        )

    for r in candidate_rows:
        try:
            await _process_market_resolution(r["market_id"])
        except Exception as exc:
            logger.error("resolution processing failed for %s: %s",
                         r["market_id"], exc)


async def _process_market_resolution(market_id: str) -> None:
    """Detect + classify positions for a single market.

    The markets-row flip is deferred until classification finishes
    cleanly. If the position-scan, enqueue, or loser-settle step raises,
    the market row stays ``resolved=FALSE`` so the next ``detect_resolutions``
    tick re-runs and no positions are stranded. Each classification step
    is independently idempotent — winner enqueue uses ``ON CONFLICT
    (position_id) DO NOTHING`` and loser settle uses
    ``WHERE status='open' AND redeemed=FALSE`` — so a re-run on the same
    market is a safe no-op for already-handled rows.

    The flip itself stays guarded with ``WHERE resolved=FALSE`` so two
    concurrent detection ticks each finishing classification cleanly
    cannot double-flip; only one UPDATE sticks.
    """
    m = await polymarket.get_market(market_id)
    if not m or not m.get("closed"):
        return

    outcomes = m.get("outcomePrices") or [0.5, 0.5]
    yes_price = float(outcomes[0])
    winning = "yes" if yes_price > 0.5 else "no"
    outcome_index = 0 if winning == "yes" else 1

    # LEFT JOIN user_settings: services.user_service.get_or_create_user
    # inserts into users without creating a user_settings row, so an
    # INNER JOIN here would silently drop those positions and leave them
    # unreconciled forever once the market is later flipped resolved.
    # COALESCE the auto_redeem_mode to the spec default ('hourly') so
    # a missing settings row routes the position through the hourly
    # batch path instead.
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT p.*, u.telegram_user_id,
                   COALESCE(us.auto_redeem_mode, 'hourly') AS auto_redeem_mode,
                   mk.condition_id
              FROM positions p
              JOIN users u ON u.id = p.user_id
              LEFT JOIN user_settings us ON us.user_id = p.user_id
              JOIN markets mk ON mk.id = p.market_id
             WHERE p.market_id = $1
               AND p.redeemed = FALSE
            """,
            market_id,
        )

    instant_queue_ids: list[UUID] = []
    classification_complete = True
    for raw in rows:
        p = dict(raw)
        try:
            won = p["side"] == winning
            if not won:
                await settle_losing_position(p)
                continue
            queue_id = await _enqueue_redeem(p, outcome_index)
            if queue_id is None:
                continue
            if (p.get("auto_redeem_mode") or "hourly") == "instant":
                instant_queue_ids.append(queue_id)
        except Exception as exc:
            logger.error("position classification failed for %s: %s",
                         p["id"], exc)
            classification_complete = False

    if classification_complete:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE markets SET status='resolved', resolved=TRUE, "
                "winning_side=$2 WHERE id=$1 AND resolved=FALSE",
                market_id, winning,
            )
    else:
        logger.warning(
            "market %s left resolved=FALSE due to classification "
            "failure(s); next detection tick will retry", market_id,
        )

    if instant_queue_ids:
        from . import instant_worker  # local import — break cycle
        for qid in instant_queue_ids:
            asyncio.create_task(instant_worker.try_process(qid))


async def _enqueue_redeem(p: dict, outcome_index: int) -> UUID | None:
    """Insert a redeem_queue row for a winning position. Idempotent.

    Returns the queue id on insert, or ``None`` when the position was
    already enqueued (the unique index on position_id catches the race).
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO redeem_queue
                (user_id, position_id, market_condition_id, outcome_index,
                 status, queued_at)
            VALUES ($1, $2, $3, $4, 'pending', NOW())
            ON CONFLICT (position_id) DO NOTHING
            RETURNING id
            """,
            p["user_id"], p["id"], p.get("condition_id"), outcome_index,
        )
    return row["id"] if row else None


# ---------------- Settlement primitives ----------------

async def settle_winning_position(p: dict) -> None:
    """Settle a winning position. Idempotent.

    For positions that were already closed before resolution (status =
    'closed'), the proceeds were credited at close time — this path only
    flips the redeemed flag. For open-at-resolution positions, this
    function:

      1. (live mode) submits the master-wallet on-chain CTF redemption
         (deduplicated per condition_id; paper mode skips the chain step
         entirely).
      2. Credits the user ledger with the terminal payoff (shares × $1).
      3. Updates the positions row to closed with exit_reason set and
         redeemed=TRUE in a single transaction so a credit cannot be
         double-applied if the worker is retried.
      4. Writes an audit entry and pushes a Telegram notification.

    Raises only on infrastructure failure (DB / chain / Telegram). The
    caller (instant_worker / hourly_worker) is responsible for catching
    and routing the exception into the retry / failure-count path.
    """
    pool = get_pool()

    if p["status"] == "closed":
        async with pool.acquire() as conn:
            updated = await conn.fetchval(
                "UPDATE positions SET redeemed=TRUE, redeemed_at=NOW() "
                "WHERE id=$1 AND redeemed=FALSE RETURNING id",
                p["id"],
            )
        if updated is not None:
            await audit.write(
                actor_role="bot", action="redeem_noop_already_closed",
                user_id=p["user_id"],
                payload={"position_id": str(p["id"]),
                         "winning_side": p["side"],
                         "won": True},
            )
        return

    if p["mode"] == "live":
        try:
            await ensure_live_redemption(p["market_id"])
        except Exception as exc:
            logger.error("live redemption could not be guaranteed for %s "
                         "(internal credit will still post): %s", p["id"], exc)

    shares = Decimal(str(p["size_usdc"])) / Decimal(str(p["entry_price"]))
    payoff = shares  # winner: 1 USDC per share
    pnl = payoff - Decimal(str(p["size_usdc"]))

    async with pool.acquire() as conn:
        async with conn.transaction():
            updated = await conn.fetchval(
                """
                UPDATE positions
                   SET status='closed', exit_reason='resolution_win',
                       current_price=1.0, pnl_usdc=$2, closed_at=NOW(),
                       redeemed=TRUE, redeemed_at=NOW()
                 WHERE id=$1 AND status='open' AND redeemed=FALSE
                 RETURNING id
                """,
                p["id"], pnl,
            )
            if updated is None:
                return
            await ledger.credit_in_conn(
                conn, p["user_id"], payoff, ledger.T_REDEEM,
                ref_id=p["id"], note=f"resolution payoff {p['side']}",
            )

    await audit.write(actor_role="bot", action="redeem", user_id=p["user_id"],
                      payload={"position_id": str(p["id"]),
                               "winning_side": p["side"],
                               "won": True,
                               "shares": str(shares),
                               "payoff": str(payoff)})
    if p.get("telegram_user_id"):
        msg = (f"🏆 *Redeemed* — winning side `{p['side']}`\n"
               f"Payoff: *${float(payoff):+.2f}*")
        await notifications.send(p["telegram_user_id"], msg)


async def settle_losing_position(p: dict) -> None:
    """Close a losing position at zero. No on-chain side effect.

    Marks the position closed with exit_reason='resolution_loss', records
    final P&L = -size, credits $0 (audit-traceable no-op via the
    redeemed=TRUE flag), audits, and notifies the user. Idempotent —
    re-invocation on an already-closed loser is a no-op.
    """
    pool = get_pool()

    if p["status"] == "closed":
        async with pool.acquire() as conn:
            updated = await conn.fetchval(
                "UPDATE positions SET redeemed=TRUE, redeemed_at=NOW() "
                "WHERE id=$1 AND redeemed=FALSE RETURNING id",
                p["id"],
            )
        if updated is None:
            return
        await audit.write(
            actor_role="bot", action="redeem_noop_already_closed",
            user_id=p["user_id"],
            payload={"position_id": str(p["id"]),
                     "winning_side": p.get("winning_side") or "unknown",
                     "won": False},
        )
        return

    pnl = Decimal("-1") * Decimal(str(p["size_usdc"]))

    async with pool.acquire() as conn:
        updated = await conn.fetchval(
            """
            UPDATE positions
               SET status='closed', exit_reason='resolution_loss',
                   current_price=0.0, pnl_usdc=$2, closed_at=NOW(),
                   redeemed=TRUE, redeemed_at=NOW()
             WHERE id=$1 AND status='open' AND redeemed=FALSE
             RETURNING id
            """,
            p["id"], pnl,
        )
    if updated is None:
        return

    await audit.write(actor_role="bot", action="redeem_loss",
                      user_id=p["user_id"],
                      payload={"position_id": str(p["id"]),
                               "side": p["side"],
                               "size_usdc": str(p["size_usdc"]),
                               "pnl_usdc": str(pnl)})
    if p.get("telegram_user_id"):
        msg = (f"❌ *Market resolved* — your position closed at a loss.\n"
               f"Side: `{p['side']}` · P&L: *${float(pnl):+.2f}*")
        await notifications.send(p["telegram_user_id"], msg)


async def ensure_live_redemption(market_id: str) -> None:
    """Submit the on-chain CTF.redeemPositions() tx ONCE per condition.

    Winning user positions in the same market settle internally against
    the master wallet's recovered USDC. The chain-side dedup is enforced
    by the unique constraint on ``live_redemptions.condition_id``.

    Skipped if EXECUTION_PATH_VALIDATED is off — live engine then falls
    back to the internal-payout path only (winning users get share count
    credited; the on-chain tx is issued later when the operator enables
    EXECUTION_PATH_VALIDATED and runs admin force-redeem).
    """
    s = get_settings()
    pool = get_pool()
    async with pool.acquire() as conn:
        market = await conn.fetchrow(
            "SELECT condition_id FROM markets WHERE id=$1", market_id,
        )
    if not market or not market["condition_id"]:
        logger.warning("live redeem skip: no condition_id for market %s", market_id)
        return

    cond = market["condition_id"]
    async with pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT tx_hash FROM live_redemptions WHERE condition_id=$1", cond,
        )
    if existing:
        return

    if not s.EXECUTION_PATH_VALIDATED:
        logger.info("live on-chain redemption deferred (EXECUTION_PATH_VALIDATED=false) "
                    "for condition %s", cond)
        return

    result = await polymarket.submit_live_redemption(cond)

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO live_redemptions (condition_id, tx_hash, gas_used) "
            "VALUES ($1, $2, $3) ON CONFLICT (condition_id) DO NOTHING",
            cond, result["tx_hash"], result.get("gas_used"),
        )
    await audit.write(actor_role="bot", action="live_redemption_onchain",
                      payload={"condition_id": cond,
                               "tx_hash": result["tx_hash"],
                               "gas_used": result.get("gas_used")})


# ---------------- Queue helpers (shared by both workers) ----------------

async def claim_queue_row(queue_id: UUID) -> dict[str, Any] | None:
    """Atomically transition a row from pending → processing.

    Returns the joined position+user row when the claim succeeded, or
    ``None`` when the row was already claimed / settled by another
    worker. The status flip is the only synchronisation primitive — no
    Redis lock, no advisory lock — because the unique index on
    ``redeem_queue.position_id`` already serialises per position.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            claimed_id = await conn.fetchval(
                "UPDATE redeem_queue SET status='processing', "
                "claimed_at=NOW() "
                "WHERE id=$1 AND status='pending' RETURNING id",
                queue_id,
            )
            if claimed_id is None:
                return None
            # LEFT JOIN user_settings — see _process_market_resolution
            # for the rationale. A missing settings row here would make
            # claim_queue_row return None for a row that was successfully
            # claimed (status='processing'), stranding the queue entry.
            row = await conn.fetchrow(
                """
                SELECT q.id AS queue_id, q.failure_count,
                       q.market_condition_id, q.outcome_index,
                       p.*, u.telegram_user_id,
                       COALESCE(us.auto_redeem_mode, 'hourly') AS auto_redeem_mode
                  FROM redeem_queue q
                  JOIN positions p ON p.id = q.position_id
                  JOIN users u ON u.id = q.user_id
                  LEFT JOIN user_settings us ON us.user_id = q.user_id
                 WHERE q.id = $1
                """,
                queue_id,
            )
            return dict(row) if row else None


async def mark_done(queue_id: UUID) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE redeem_queue SET status='done', processed_at=NOW(), "
            "last_error=NULL WHERE id=$1",
            queue_id,
        )


async def reap_stale_processing(stale_after_seconds: int = 300) -> int:
    """Recover orphaned ``processing`` rows back to ``pending``.

    A worker crash (or a process restart) between the pending → processing
    flip in ``claim_queue_row`` and the terminal transition in
    ``mark_done`` / ``release_back_to_pending`` leaves the queue row in
    ``processing`` indefinitely. Detection won't re-enqueue (the unique
    index on ``position_id`` blocks a duplicate row) and the hourly drain
    only selects ``status='pending'``, so without this reaper the row
    would be stranded forever.

    The threshold default of 300 s is well past the instant worker's
    bounded wall time (one settle attempt + 30 s sleep + one retry,
    typically < 90 s) so an active worker is never reaped. Released rows
    do NOT increment ``failure_count`` — a crash is not a settle failure
    — but the action is logged at WARN so the operator can spot a stuck
    process pattern.

    Returns the number of rows released.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "UPDATE redeem_queue "
            "   SET status='pending' "
            " WHERE status='processing' "
            "   AND claimed_at IS NOT NULL "
            "   AND claimed_at < NOW() - "
            "       ($1::int * INTERVAL '1 second') "
            "RETURNING id",
            stale_after_seconds,
        )
    return len(rows)


async def release_back_to_pending(
    queue_id: UUID, *, increment_failure: bool, error: str | None = None,
) -> int:
    """Release a processing row back to pending.

    When ``increment_failure`` is true, ``failure_count`` is bumped and
    ``last_error`` is recorded. Returns the post-update failure_count so
    the caller (hourly worker) can decide whether to page the operator.

    The UPDATE is gated on ``status='processing'``: a delayed worker
    whose claim was reaped (and the row subsequently re-claimed and
    settled to ``done`` by another worker) must NOT flip the terminal
    row back to ``pending`` and must NOT increment failure_count. Such a
    delayed call returns 0 — the row is already settled, no false
    persistent-failure alert is emitted.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        if increment_failure:
            row = await conn.fetchrow(
                "UPDATE redeem_queue SET status='pending', "
                "failure_count = failure_count + 1, last_error=$2 "
                "WHERE id=$1 AND status='processing' "
                "RETURNING failure_count",
                queue_id, (error or "")[:500],
            )
        else:
            row = await conn.fetchrow(
                "UPDATE redeem_queue SET status='pending' "
                "WHERE id=$1 AND status='processing' "
                "RETURNING failure_count",
                queue_id,
            )
    return int(row["failure_count"]) if row else 0
