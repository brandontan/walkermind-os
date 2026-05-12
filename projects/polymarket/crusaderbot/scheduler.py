"""APScheduler jobs — single async loop, all background work."""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal

import asyncio
from apscheduler.events import (
    EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_SUBMITTED,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from . import audit, notifications
from .config import get_settings
from .database import get_pool
from .domain.execution import exit_watcher
from .domain.execution import lifecycle as order_lifecycle
from .integrations.clob import ClobWebSocketClient
from .domain.execution.router import execute as router_execute
from .domain.ops import job_tracker
from .domain.risk.gate import GateContext, evaluate
from .domain.signal.copy_trade import CopyTradeStrategy
from .integrations import polygon, polymarket
from .domain.activation.auto_fallback import (
    JOB_ID as AUTO_FALLBACK_JOB_ID,
    LOOKBACK_SECONDS as AUTO_FALLBACK_INTERVAL,
    run_auto_fallback_check,
)
from .jobs import daily_pnl_summary, hourly_report, market_signal_scanner, market_sync, weekly_insights
from .services.signal_scan import signal_scan_job as sf_scan_job
from .services.copy_trade import monitor as copy_trade_monitor
from .services.redeem import hourly_worker as redeem_hourly_worker
from .services.redeem import redeem_router
from .wallet import ledger

logger = logging.getLogger(__name__)


# ---------------- Market sync ----------------

async def sync_markets() -> None:
    try:
        markets = await polymarket.get_markets(limit=100)
    except Exception as exc:
        logger.warning("sync_markets fetch failed: %s", exc)
        return
    if not markets:
        return
    pool = get_pool()
    upserts = 0
    async with pool.acquire() as conn:
        for m in markets:
            try:
                mid = str(m.get("id") or m.get("conditionId") or "")
                if not mid:
                    continue
                outcomes = m.get("outcomePrices") or m.get("outcome_prices") or [None, None]
                yes_p = float(outcomes[0]) if outcomes and outcomes[0] is not None else None
                no_p = float(outcomes[1]) if len(outcomes) > 1 and outcomes[1] is not None else None
                tokens = m.get("clobTokenIds") or m.get("tokenIds") or [None, None]
                yes_tok = str(tokens[0]) if tokens and tokens[0] else None
                no_tok = str(tokens[1]) if len(tokens) > 1 and tokens[1] else None
                liq = float(m.get("liquidity") or 0)
                resolved = bool(m.get("closed") or False)
                end = m.get("endDate") or m.get("end_date")
                resolution_at = None
                if end:
                    try:
                        resolution_at = datetime.fromisoformat(end.replace("Z", "+00:00"))
                    except Exception:
                        resolution_at = None
                category = (m.get("category") or m.get("groupItemTitle") or "")[:50]
                cond_id = (m.get("conditionId") or m.get("condition_id")
                           or m.get("conditionID"))
                cond_id = str(cond_id) if cond_id else None
                await conn.execute(
                    """
                    INSERT INTO markets
                        (id, slug, question, category, status, yes_price, no_price,
                         yes_token_id, no_token_id, liquidity_usdc, resolution_at,
                         resolved, condition_id, synced_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,NOW())
                    ON CONFLICT (id) DO UPDATE SET
                        slug=EXCLUDED.slug, question=EXCLUDED.question,
                        category=EXCLUDED.category, status=EXCLUDED.status,
                        condition_id=COALESCE(EXCLUDED.condition_id, markets.condition_id),
                        yes_price=EXCLUDED.yes_price, no_price=EXCLUDED.no_price,
                        yes_token_id=EXCLUDED.yes_token_id,
                        no_token_id=EXCLUDED.no_token_id,
                        liquidity_usdc=EXCLUDED.liquidity_usdc,
                        resolution_at=EXCLUDED.resolution_at,
                        resolved=EXCLUDED.resolved, synced_at=NOW()
                    """,
                    mid, m.get("slug"), m.get("question"), category,
                    "resolved" if resolved else "active",
                    yes_p, no_p, yes_tok, no_tok, liq, resolution_at, resolved,
                    cond_id,
                )
                upserts += 1
            except Exception as exc:
                logger.warning("market upsert failed for %s: %s",
                               m.get("id"), exc)
    logger.info("sync_markets: upserted %d", upserts)


# ---------------- Deposit watcher ----------------

async def watch_deposits() -> None:
    """Atomic deposit insert + ledger credit. Cursor only advances on success.

    A failed credit ROLLS BACK the deposit insert so the same tx_hash will be
    re-processed on the next scan. The block-cursor itself is only advanced
    after the chain scan succeeds AND every transfer in that range has been
    persisted (or non-credited because the address belongs to no user).
    """
    pool = get_pool()
    settings = get_settings()
    min_deposit = Decimal(str(settings.MIN_DEPOSIT_USDC))
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT user_id, deposit_address FROM wallets",
        )
    if not rows:
        return
    addr_by_lower = {r["deposit_address"].lower(): r["user_id"] for r in rows}
    addresses = [r["deposit_address"] for r in rows]

    cursor_start = await _read_cursor("usdc_deposits")
    try:
        transfers, scanned_to = await polygon.scan_from_cursor(
            addresses, cursor_start,
        )
    except Exception as exc:
        logger.warning("watch_deposits scan failed (no cursor advance): %s", exc)
        return

    notify_after: list[tuple[int, Decimal, str, bool]] = []
    all_ok = True
    for t in transfers:
        to_addr = t["to"].lower()
        user_id = addr_by_lower.get(to_addr)
        if not user_id:
            continue  # address not ours — safe to skip and advance cursor
        amount = Decimal(str(t["amount"]))
        # log_index disambiguates multiple USDC Transfer logs in the same tx
        # routed to distinct tracked addresses. Without it, ON CONFLICT would
        # silently drop every Transfer past the first and under-credit users.
        log_index = int(t.get("log_index", 0))
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    row = await conn.fetchrow(
                        """
                        INSERT INTO deposits (user_id, tx_hash, log_index,
                                              amount_usdc, block_number,
                                              confirmed_at)
                        VALUES ($1,$2,$3,$4,$5,NOW())
                        ON CONFLICT (tx_hash, log_index) DO NOTHING
                        RETURNING id
                        """,
                        user_id, t["tx_hash"], log_index, amount,
                        t["block_number"],
                    )
                    if row is None:
                        continue  # already credited
                    await ledger.credit_in_conn(
                        conn, user_id, amount, ledger.T_DEPOSIT,
                        ref_id=row["id"], note=t["tx_hash"],
                    )
                    # Tier 3 promotion gated on cumulative confirmed deposits
                    # >= MIN_DEPOSIT_USDC. Dust deposits must not bypass the
                    # funded-beta tier gate.
                    total_balance = Decimal(str(await conn.fetchval(
                        "SELECT COALESCE(SUM(amount_usdc), 0) FROM deposits "
                        "WHERE user_id = $1 AND confirmed_at IS NOT NULL",
                        user_id,
                    ) or 0))
                    tier_promoted = total_balance >= min_deposit
                    if tier_promoted:
                        await conn.execute(
                            "UPDATE users SET access_tier = GREATEST(access_tier, 3) "
                            "WHERE id = $1",
                            user_id,
                        )
                        logger.info(
                            "user promoted to Tier 3: user_id=%s "
                            "total_balance=%s min_required=%s",
                            user_id, float(total_balance),
                            float(settings.MIN_DEPOSIT_USDC),
                        )
                    else:
                        logger.info(
                            "deposit credited but below MIN_DEPOSIT_USDC — "
                            "Tier 3 not granted: user_id=%s total_balance=%s "
                            "min_required=%s",
                            user_id, float(total_balance),
                            float(settings.MIN_DEPOSIT_USDC),
                        )
                    u = await conn.fetchrow(
                        "SELECT telegram_user_id FROM users WHERE id=$1",
                        user_id,
                    )
            await audit.write(actor_role="bot", action="deposit_confirmed",
                              user_id=user_id,
                              payload={"tx_hash": t["tx_hash"],
                                       "amount": str(amount),
                                       "tier_promoted": tier_promoted})
            if u:
                notify_after.append(
                    (u["telegram_user_id"], amount, t["tx_hash"], tier_promoted)
                )
        except Exception as exc:
            logger.error("deposit credit failed for %s: %s — cursor will not advance",
                         t["tx_hash"], exc)
            all_ok = False

    if all_ok:
        await _write_cursor("usdc_deposits", scanned_to)

    for tg_id, amt, tx, tier_promoted in notify_after:
        if tier_promoted:
            tail = "You're now Tier 3 — auto-trade unlocked."
        else:
            tail = (
                f"Below minimum (${float(min_deposit):.2f} USDC) — "
                "Tier 3 not yet unlocked. Top up to enable auto-trade."
            )
        await notifications.send(
            tg_id,
            f"✅ *Deposit confirmed:* ${float(amt):.2f} USDC\n"
            f"`{tx}`\n{tail}",
        )


async def _read_cursor(name: str) -> int:
    pool = get_pool()
    async with pool.acquire() as conn:
        v = await conn.fetchval(
            "SELECT block_number FROM chain_cursor WHERE name=$1", name,
        )
    return int(v or 0)


async def _write_cursor(name: str, block_number: int) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO chain_cursor (name, block_number, updated_at) "
            "VALUES ($1,$2,NOW()) "
            "ON CONFLICT (name) DO UPDATE SET block_number=EXCLUDED.block_number, "
            "updated_at=NOW()",
            name, block_number,
        )


# ---------------- Signal scan + auto-trade ----------------

_strategies = {"copy_trade": CopyTradeStrategy()}


async def run_signal_scan() -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        users = await conn.fetch(
            """
            SELECT u.id, u.telegram_user_id, u.access_tier, u.auto_trade_on,
                   u.paused, w.balance_usdc, s.*
              FROM users u
              JOIN wallets w ON w.user_id = u.id
              JOIN user_settings s ON s.user_id = u.id
             WHERE u.auto_trade_on = TRUE AND u.paused = FALSE
               AND u.access_tier >= 3
            """
        )
    for u_row in users:
        user = dict(u_row)
        user["balance_usdc"] = float(user.get("balance_usdc") or 0)
        for strat_name in (user.get("strategy_types") or []):
            strat = _strategies.get(strat_name)
            if not strat:
                continue
            try:
                candidates = await strat.scan(user, user)
            except Exception as exc:
                logger.warning("strategy %s scan failed for user %s: %s",
                               strat_name, user["id"], exc)
                continue
            for cand in candidates:
                try:
                    await _process_candidate(user, cand)
                except Exception as exc:
                    logger.error("candidate processing failed: %s", exc)


async def _process_candidate(user: dict, cand) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        market = await conn.fetchrow(
            "SELECT * FROM markets WHERE id=$1", cand.market_id,
        )
    if market is None:
        # market not synced yet — skip
        return
    idem_key = f"{user['id']}:{cand.market_id}:{cand.side}:" \
               f"{cand.extra.get('src_tx', '')[:32]}"
    ctx_g = GateContext(
        user_id=user["id"],
        telegram_user_id=user["telegram_user_id"],
        access_tier=user["access_tier"],
        auto_trade_on=user["auto_trade_on"],
        paused=user["paused"],
        market_id=cand.market_id,
        side=cand.side,
        proposed_size_usdc=cand.size_usdc,
        proposed_price=cand.price,
        market_liquidity=float(market["liquidity_usdc"] or 0),
        market_status=market["status"],
        edge_bps=cand.edge_bps,
        signal_ts=cand.signal_ts,
        idempotency_key=idem_key,
        strategy_type=cand.strategy_type,
        risk_profile=user["risk_profile"],
        daily_loss_override=float(user["daily_loss_override"])
            if user["daily_loss_override"] is not None else None,
        trading_mode=user["trading_mode"],
    )
    result = await evaluate(ctx_g)
    if not result.approved:
        logger.info("trade rejected user=%s market=%s reason=%s step=%s",
                    user["id"], cand.market_id, result.reason, result.failed_step)
        return
    try:
        await router_execute(
            chosen_mode=result.chosen_mode,
            user_id=user["id"],
            telegram_user_id=user["telegram_user_id"],
            access_tier=user["access_tier"],
            trading_mode=user["trading_mode"],
            market_id=cand.market_id,
            market_question=market["question"],
            yes_token_id=market["yes_token_id"],
            no_token_id=market["no_token_id"],
            side=cand.side,
            size_usdc=result.final_size_usdc or cand.size_usdc,
            price=cand.price,
            idempotency_key=idem_key,
            strategy_type=cand.strategy_type,
            tp_pct=float(user["tp_pct"]) if user["tp_pct"] is not None else None,
            sl_pct=float(user["sl_pct"]) if user["sl_pct"] is not None else None,
        )
    except Exception as exc:
        logger.error("router execute failed user=%s market=%s mode=%s: %s",
                     user["id"], cand.market_id, result.chosen_mode, exc)


# ---------------- Exit watcher ----------------

async def check_exits() -> None:
    """Drive the exit-watcher worker for one tick.

    Priority chain (force_close_intent > tp_hit > sl_hit > strategy_exit >
    hold), TP/SL snapshot enforcement, retry-once-on-CLOB-error, and the
    per-position close_failure_count tracking all live in
    ``domain.execution.exit_watcher``. This wrapper exists so APScheduler's
    job table keeps its long-standing ``check_exits`` entry point.
    """
    await exit_watcher.run_once()


# ---------------- Order lifecycle ----------------

async def poll_order_lifecycle() -> None:
    """Drive one OrderLifecycleManager poll sweep.

    The manager handles its own per-order error containment so a single
    broker failure does not abort other orders in the same sweep. The
    APScheduler job id ``order_lifecycle`` is reserved for this entry
    point so job_runs traces stay stable.
    """
    await order_lifecycle.poll_once()


# ---------------- CLOB WebSocket (Phase 4D) ----------------
# A single ``ClobWebSocketClient`` instance lives for the lifetime of the
# scheduler. ``ws_connect`` spawns it on startup; ``ws_watchdog`` reconnects
# if the run loop ever exits unexpectedly. Both jobs are no-ops when
# USE_REAL_CLOB=False — the client itself enforces that contract, but the
# scheduler also short-circuits to keep job_runs noise-free in paper mode.

_ws_client: ClobWebSocketClient | None = None


def get_ws_client() -> ClobWebSocketClient | None:
    """Return the active WebSocket client, or None when paper-mode."""
    return _ws_client


async def ws_connect() -> None:
    """One-shot startup job: build + start the WebSocket client.

    Idempotent — calling twice is safe; the second call returns
    immediately because the client refuses to start a second run loop.
    """
    global _ws_client
    s = get_settings()
    if not s.USE_REAL_CLOB:
        return
    if _ws_client is None:
        _ws_client = ClobWebSocketClient(
            settings=s,
            on_fill=order_lifecycle.dispatch_ws_fill,
            on_order_update=order_lifecycle.dispatch_ws_order_update,
        )
    await _ws_client.start()


async def ws_watchdog() -> None:
    """Periodic liveness check.

    Triggers a reconnect when the run loop task has exited. Treats a
    missing client as "needs construction" so an operator who flips
    USE_REAL_CLOB at runtime gets a fresh client without a process
    restart.
    """
    s = get_settings()
    if not s.USE_REAL_CLOB:
        return
    global _ws_client
    if _ws_client is None or not _ws_client.is_alive():
        logger.warning("ws_watchdog: client not alive, reconnecting")
        if _ws_client is not None:
            try:
                await _ws_client.stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning("ws_watchdog: stale client stop failed: %s", exc)
            _ws_client = None
        await ws_connect()


async def ws_shutdown() -> None:
    """Close the WebSocket client cleanly. Called on bot shutdown."""
    global _ws_client
    if _ws_client is None:
        return
    try:
        await _ws_client.stop()
    finally:
        _ws_client = None


# ---------------- Resolution + redeem ----------------
# Detection, dispatch, and settlement live in services.redeem.
# These wrappers preserve the long-standing scheduler entry points so the
# APScheduler job table does not have to change when the implementation
# moves out of this module.

async def check_resolutions() -> None:
    """Drive the redeem router's resolution scan for one tick.

    Detection + per-position classification (winners → redeem_queue,
    instant-mode dispatch; losers → settle inline) lives in
    ``services.redeem.redeem_router``. This wrapper only exists so the
    APScheduler job id ``resolution`` keeps pointing at the same callable.
    """
    await redeem_router.detect_resolutions()


async def redeem_hourly() -> None:
    """Drive the hourly redeem worker for one cron tick.

    Drains pending rows in ``redeem_queue`` sequentially and pages the
    operator at >= 2 consecutive failures on the same row.
    """
    await redeem_hourly_worker.run_once()


async def sweep_deposits() -> None:
    """Nightly batch sweep stub — would move per-user balances to hot pool.

    For MVP we only mark deposits as swept in DB (logical sweep, not on-chain).
    Real on-chain sweep is gated behind EXECUTION_PATH_VALIDATED.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        n = await conn.fetchval(
            "UPDATE deposits SET swept=TRUE WHERE swept=FALSE RETURNING 1"
        )
    logger.info("sweep_deposits: %s deposits marked", n)


def _job_tracker_listener(event) -> None:
    """APScheduler listener that mirrors job outcomes into ``job_runs``.

    Three event classes feed into a single sink:
      * EVENT_JOB_SUBMITTED - capture a wallclock start so duration is
        accurate even when ``scheduled_run_time`` is shifted by a misfire.
      * EVENT_JOB_EXECUTED  - happy-path terminal event.
      * EVENT_JOB_ERROR     - failure terminal event with exception text.

    The DB write is dispatched onto the running event loop because
    APScheduler invokes listeners synchronously. ``call_soon_threadsafe``
    is used defensively in case APScheduler ever upgrades to a thread
    pool — today the AsyncIO scheduler runs listeners on the loop thread.
    """
    if event.code == EVENT_JOB_SUBMITTED:
        job_tracker.mark_job_submitted(event.job_id)
        return
    success = event.code == EVENT_JOB_EXECUTED
    err = None
    if not success:
        exc = getattr(event, "exception", None)
        if exc is not None:
            err = f"{type(exc).__name__}: {exc}"
    # Pop the start timestamp SYNCHRONOUSLY here so the next SUBMITTED
    # event for the same job_id cannot overwrite it before our
    # create_task'd record_job_event reads it. This closes the race
    # Codex flagged on PR #874 (job_tracker.py:34).
    started_at = job_tracker.pop_job_start(event.job_id)
    coro = job_tracker.record_job_event(
        job_id=event.job_id, success=success, error=err,
        started_at=started_at,
    )
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop (shouldn't happen with AsyncIOScheduler) — fire
        # a fresh task so the write still lands.
        try:
            asyncio.run(coro)
        except Exception as exc:  # noqa: BLE001
            logger.error("job_runs sync write failed: %s", exc)
        return
    loop.create_task(coro)


def setup_scheduler() -> AsyncIOScheduler:
    s = get_settings()
    sched = AsyncIOScheduler(timezone=s.TIMEZONE)
    sched.add_job(sync_markets, "interval", seconds=s.MARKET_SCAN_INTERVAL,
                  id="market_sync", max_instances=1, coalesce=True)
    sched.add_job(watch_deposits, "interval", seconds=s.DEPOSIT_WATCH_INTERVAL,
                  id="deposit_watch", max_instances=1, coalesce=True)
    sched.add_job(run_signal_scan, "interval", seconds=s.SIGNAL_SCAN_INTERVAL,
                  id="signal_scan", max_instances=1, coalesce=True)
    sched.add_job(sf_scan_job.run_once, "interval", seconds=s.SIGNAL_SCAN_INTERVAL,
                  id="signal_following_scan", max_instances=1, coalesce=True)
    sched.add_job(market_signal_scanner.run_job, "interval",
                  seconds=s.MARKET_SIGNAL_SCAN_INTERVAL,
                  id=market_signal_scanner.JOB_ID, max_instances=1, coalesce=True,
                  replace_existing=True)
    sched.add_job(market_sync.run_job, "interval",
                  seconds=1800,
                  id=market_sync.JOB_ID, max_instances=1, coalesce=True)
    sched.add_job(copy_trade_monitor.run_once, "interval",
                  seconds=s.COPY_TRADE_MONITOR_INTERVAL,
                  id="copy_trade_monitor", max_instances=1, coalesce=True)
    sched.add_job(check_exits, "interval", seconds=s.EXIT_WATCH_INTERVAL,
                  id="exit_watch", max_instances=1, coalesce=True)
    sched.add_job(poll_order_lifecycle, "interval",
                  seconds=s.ORDER_POLL_INTERVAL_SECONDS,
                  id="order_lifecycle", max_instances=1, coalesce=True)
    # WebSocket fill streaming (Phase 4D). The client itself enforces the
    # USE_REAL_CLOB=False guard; jobs are still registered so a runtime
    # toggle flip + watchdog tick brings the socket up without a redeploy.
    sched.add_job(ws_connect, "date", id="ws_connect",
                  max_instances=1, coalesce=True)
    sched.add_job(ws_watchdog, "interval",
                  seconds=s.WS_WATCHDOG_INTERVAL_SECONDS,
                  id="ws_watchdog", max_instances=1, coalesce=True)
    sched.add_job(redeem_hourly, "interval", seconds=s.REDEEM_INTERVAL,
                  id="redeem", max_instances=1, coalesce=True)
    sched.add_job(check_resolutions, "interval", seconds=s.RESOLUTION_CHECK_INTERVAL,
                  id="resolution", max_instances=1, coalesce=True)
    sched.add_job(sweep_deposits, "cron", hour=3, id="sweep", max_instances=1)
    # Daily P&L summary fires once per day at 23:00 Asia/Jakarta. The
    # ``timezone`` argument on the scheduler resolves the local cron tick,
    # so passing ``hour=23`` here is automatically anchored to Jakarta time
    # via ``s.TIMEZONE`` regardless of the host's wallclock zone.
    sched.add_job(
        daily_pnl_summary.run_job, "cron",
        hour=23, minute=0,
        id=daily_pnl_summary.JOB_ID, max_instances=1, coalesce=True,
    )
    # Weekly insights — Monday 08:00 Asia/Jakarta.
    sched.add_job(
        weekly_insights.run_job, "cron",
        day_of_week="mon", hour=8, minute=0,
        id=weekly_insights.JOB_ID, max_instances=1, coalesce=True,
    )
    # Hourly system report → all ADMIN-tier users.
    sched.add_job(
        hourly_report.run_job, "cron",
        minute=0,
        id=hourly_report.JOB_ID, max_instances=1, coalesce=True,
    )
    # Track F — auto-fallback monitor (60s poll).
    sched.add_job(
        run_auto_fallback_check, "interval",
        seconds=AUTO_FALLBACK_INTERVAL,
        id=AUTO_FALLBACK_JOB_ID, max_instances=1, coalesce=True,
    )
    sched.add_listener(
        _job_tracker_listener,
        EVENT_JOB_SUBMITTED | EVENT_JOB_EXECUTED | EVENT_JOB_ERROR,
    )
    return sched
