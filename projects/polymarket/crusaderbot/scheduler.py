"""APScheduler jobs — single async loop, all background work."""
from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import TypedDict

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import asyncio
from apscheduler.events import (
    EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_SUBMITTED,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from . import audit, notifications
from .config import get_settings, resolve_trading_mode
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
from .services.daily_report_service import daily_pnl_report_job, JOB_ID as DAILY_REPORT_JOB_ID
from .services.signal_scan import signal_scan_job as sf_scan_job
from .services.copy_trade import monitor as copy_trade_monitor
from .services.copy_trade import leaderboard_sync
from .services.redeem import hourly_worker as redeem_hourly_worker
from .services.redeem import redeem_router
from .services import portfolio_snapshots
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
                mid = str(m.get("conditionId") or m.get("id") or "")  # prefer conditionId (hex) — matches markets.id PK
                if not mid:
                    continue
                outcomes = m.get("outcomePrices") or m.get("outcome_prices") or [None, None]
                if isinstance(outcomes, str):
                    import json as _json
                    try:
                        outcomes = _json.loads(outcomes)
                    except Exception:
                        outcomes = [None, None]
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

def _build_watched_addresses(wallet_rows) -> tuple[list[str], dict[str, object]]:
    """Return the address scan list + a lowercase→user_id lookup map.

    Each wallet contributes its EOA ``deposit_address`` and, when set, its
    pre-computed ``safe_address`` (migration 061). Both addresses route to
    the same user, so transfers into either credit that user without any
    custody-mode flip. NULL ``safe_address`` rows (pre-backfill or pre-Chunk 2
    wallets) silently fall back to EOA-only — no behavior change for them.
    """
    addresses: list[str] = []
    addr_by_lower: dict = {}
    for r in wallet_rows:
        eoa = r["deposit_address"]
        addresses.append(eoa)
        addr_by_lower[eoa.lower()] = r["user_id"]
        safe = r.get("safe_address") if isinstance(r, dict) else r["safe_address"]
        if safe:
            addresses.append(safe)
            addr_by_lower[safe.lower()] = r["user_id"]
    return addresses, addr_by_lower


async def watch_deposits() -> None:
    """Confirmation-depth deposit watcher with reorg guard (H6).

    A USDC transfer is recorded as ``pending`` on first sighting — no ledger
    credit yet. It only credits the ledger once it is
    ``DEPOSIT_CONFIRMATION_DEPTH`` blocks deep on the canonical chain
    (``confirmed``). A log that re-arrives with ``removed=true`` (orphaned by a
    reorg) un-credits a confirmed deposit and marks it ``reverted``.

    The block cursor only advances after every transfer in the scanned range is
    durably recorded; a failed write re-processes on the next tick. Confirmation
    runs as a separate pass over all pending rows, so a deposit seen near head
    is still confirmed on a later tick even after the forward cursor moves past
    its block.
    """
    settings = get_settings()
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            # safe_address comes from migration 061; partial-unique index ensures
            # one user per address. Safe addresses route to the same user_id as
            # the EOA so Polymarket Magic-link / Safe-flow deposits credit the
            # correct user without any custody-mode flip.
            "SELECT user_id, deposit_address, safe_address FROM wallets",
        )
    if not rows:
        return
    addresses, addr_by_lower = _build_watched_addresses(rows)

    try:
        head = await polygon.latest_block()
    except Exception as exc:
        logger.warning("watch_deposits head read failed (no cursor advance): %s", exc)
        return

    cursor_start = await _read_cursor("usdc_deposits")
    try:
        transfers, scanned_to = await polygon.scan_from_cursor(
            addresses, cursor_start,
        )
    except Exception as exc:
        logger.warning("watch_deposits scan failed (no cursor advance): %s", exc)
        return

    all_ok = True
    for t in transfers:
        user_id = addr_by_lower.get(t["to"].lower())
        if not user_id:
            continue  # address not ours — safe to skip and advance cursor
        try:
            if t.get("removed"):
                await _revert_deposit(t)
            else:
                await _record_pending_deposit(user_id, t)
        except Exception as exc:
            logger.error("deposit record failed for %s: %s — cursor will not advance",
                         t.get("tx_hash"), exc)
            all_ok = False

    if all_ok:
        await _write_cursor("usdc_deposits", scanned_to)

    # Confirm pass: promote pending deposits that are now deep enough.
    try:
        notify_after = await _confirm_ready_deposits(
            head, settings.DEPOSIT_CONFIRMATION_DEPTH,
        )
    except Exception as exc:
        logger.error("deposit confirm pass failed: %s", exc)
        notify_after = []

    deposit_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("💰 Wallet", callback_data="menu:wallet"),
        InlineKeyboardButton("📊 Dashboard", callback_data="menu:dashboard"),
    ]])
    for tg_id, amt, tx in notify_after:
        await notifications.send(
            tg_id,
            f"✅ <b>Deposit confirmed:</b> ${float(amt):.2f} USDC\n"
            f"<code>{html.escape(tx)}</code>",
            reply_markup=deposit_kb,
        )


async def _record_pending_deposit(user_id, t: dict) -> None:
    """Insert a newly-seen transfer as ``pending`` — no ledger credit yet.

    Idempotent on ``(tx_hash, log_index)``: a duplicate sighting is a no-op; a
    transfer previously ``reverted`` is reset to ``pending`` so it can confirm
    again if the tx is re-mined on the canonical chain.
    """
    log_index = int(t.get("log_index", 0))
    amount = Decimal(str(t["amount"]))
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO deposits (user_id, tx_hash, log_index, amount_usdc,
                                      block_number, status)
                VALUES ($1,$2,$3,$4,$5,'pending')
                ON CONFLICT (tx_hash, log_index) DO UPDATE
                    SET status='pending', confirmed_at_block=NULL
                    WHERE deposits.status='reverted'
                RETURNING id
                """,
                user_id, t["tx_hash"], log_index, amount, t["block_number"],
            )
    if row is not None:
        await audit.write(
            actor_role="bot", action="deposit_credit_pending", user_id=user_id,
            payload={"tx_hash": t["tx_hash"], "log_index": log_index,
                     "amount": str(amount), "block": t["block_number"]},
        )


async def _revert_deposit(t: dict) -> None:
    """Honor a ``removed=true`` log: debit a confirmed deposit back out, else
    just mark a pending one ``reverted``. Idempotent — an already-reverted or
    never-seen transfer is a no-op.
    """
    log_index = int(t.get("log_index", 0))
    pool = get_pool()
    reverted: tuple | None = None
    async with pool.acquire() as conn:
        async with conn.transaction():
            dep = await conn.fetchrow(
                """
                SELECT id, user_id, amount_usdc, status
                  FROM deposits
                 WHERE tx_hash=$1 AND log_index=$2
                 FOR UPDATE
                """,
                t["tx_hash"], log_index,
            )
            if dep is None or dep["status"] == "reverted":
                return
            await conn.execute(
                "UPDATE deposits SET status='reverted' WHERE id=$1", dep["id"],
            )
            amount = Decimal(str(dep["amount_usdc"]))
            if dep["status"] == "confirmed":
                # roll the credited funds back out of the user's balance
                await ledger.debit_in_conn(
                    conn, dep["user_id"], amount, ledger.T_DEPOSIT,
                    ref_id=dep["id"], note=f"reorg-revert {t['tx_hash']}",
                )
            reverted = (dep["user_id"], dep["status"], amount)
    user_id, prior, amount = reverted
    await audit.write(
        actor_role="bot", action="deposit_credit_reverted", user_id=user_id,
        payload={"tx_hash": t["tx_hash"], "log_index": log_index,
                 "amount": str(amount), "prior_status": prior,
                 "uncredited": prior == "confirmed"},
    )


async def _confirm_ready_deposits(
    head: int, depth: int,
) -> list[tuple[int, Decimal, str]]:
    """Promote pending deposits that are now >= ``depth`` blocks deep to
    ``confirmed`` and credit the ledger once. The confirming UPDATE is guarded
    by ``status='pending'`` so a credit can never fire twice for the same row.

    Returns ``(telegram_user_id, amount, tx_hash)`` tuples to notify.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        ready = await conn.fetch(
            """
            SELECT id, user_id, tx_hash, amount_usdc, block_number
              FROM deposits
             WHERE status='pending'
               AND block_number IS NOT NULL
               AND ($1 - block_number) >= $2
            """,
            head, depth,
        )
    notify: list[tuple[int, Decimal, str]] = []
    for d in ready:
        amount = Decimal(str(d["amount_usdc"]))
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    UPDATE deposits
                       SET status='confirmed', confirmed_at_block=$2,
                           confirmed_at=NOW()
                     WHERE id=$1 AND status='pending'
                    RETURNING id
                    """,
                    d["id"], head,
                )
                if row is None:
                    continue  # confirmed by a concurrent tick — credit once only
                await ledger.credit_in_conn(
                    conn, d["user_id"], amount, ledger.T_DEPOSIT,
                    ref_id=d["id"], note=d["tx_hash"],
                )
                u = await conn.fetchrow(
                    "SELECT telegram_user_id FROM users WHERE id=$1", d["user_id"],
                )
        await audit.write(
            actor_role="bot", action="deposit_credit_confirmed", user_id=d["user_id"],
            payload={"tx_hash": d["tx_hash"], "amount": str(amount),
                     "block": d["block_number"], "confirmed_at_block": head},
        )
        if u:
            notify.append((u["telegram_user_id"], amount, d["tx_hash"]))
    return notify


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


def _resolve_mode() -> str:
    """Paper/live label — delegates to the canonical ``config.resolve_trading_mode``."""
    return resolve_trading_mode(get_settings())


class SignalScanMetrics(TypedDict):
    """Per-tick legacy copy_trade scan metrics persisted to ``job_runs.metadata``.

    Produced by ``run_signal_scan`` (the legacy copy_trade-only path) → captured
    by ``_job_tracker_listener`` under job_name ``legacy_copy_trade_scan``. NOTE:
    the operator panel /panel → Stats now reads the real feed-eval engine from
    the ``scan_runs`` table (``signal_scan_job.fetch_latest_scan_run``), NOT these
    counters. ``router_executed`` is an execution proxy (successful
    ``router_execute`` calls), NOT a confirmed orders/positions DB-row count.
    """
    mode: str
    live_trading: bool
    strategies_loaded: list[str]
    users_scanned: int
    markets_seen: int
    candidates_emitted: int
    risk_approved: int
    risk_rejected: int
    router_executed: int
    errors: int


async def run_signal_scan() -> SignalScanMetrics:
    """Auto-trade scan tick.

    Returns a metrics dict captured by ``_job_tracker_listener`` into
    ``job_runs.metadata`` — durable runtime proof of the
    scan -> candidate -> risk gate -> router_execute pipeline that the operator
    panel (/panel -> Stats) reads back. ``router_executed`` is an execution proxy
    (successful router_execute calls), not a count of confirmed orders/positions
    DB rows. Behaviour is unchanged; the counters are purely observational.
    """
    mode = _resolve_mode()
    markets_seen: set[str] = set()
    candidates_emitted = 0
    risk_approved = 0
    risk_rejected = 0
    router_executed = 0
    errors = 0

    pool = get_pool()
    async with pool.acquire() as conn:
        users = await conn.fetch(
            """
            SELECT u.id, u.telegram_user_id, u.role, u.auto_trade_on,
                   u.paused, w.balance_usdc, s.*
              FROM users u
              JOIN wallets w ON w.user_id = u.id
              JOIN user_settings s ON s.user_id = u.id
             WHERE u.auto_trade_on = TRUE AND u.paused = FALSE
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
                candidates_emitted += 1
                if (m_id := getattr(cand, "market_id", None)):
                    markets_seen.add(str(m_id))
                try:
                    outcome = await _process_candidate(user, cand)
                except Exception as exc:
                    logger.error("candidate processing failed: %s", exc)
                    errors += 1
                    continue
                if outcome == "executed":
                    risk_approved += 1
                    router_executed += 1
                elif outcome == "error":
                    risk_approved += 1
                    errors += 1
                elif outcome == "rejected":
                    risk_rejected += 1

    return {
        "mode": mode,
        "live_trading": get_settings().ENABLE_LIVE_TRADING,
        "strategies_loaded": sorted(_strategies.keys()),
        "users_scanned": len(users),
        "markets_seen": len(markets_seen),
        "candidates_emitted": candidates_emitted,
        "risk_approved": risk_approved,
        "risk_rejected": risk_rejected,
        # Successful router_execute calls this tick. Execution proxy only — NOT a
        # guarantee of new orders/positions DB rows (paper.execute dedups via
        # ON CONFLICT (idempotency_key) DO NOTHING, so a repeat is a no-op).
        "router_executed": router_executed,
        "errors": errors,
    }


async def _process_candidate(user: dict, cand) -> str:
    """Evaluate + (if approved) execute one candidate.

    Returns a short outcome label used by ``run_signal_scan`` to tally the
    pipeline metrics: ``"skipped"`` (market not synced), ``"rejected"`` (risk
    gate), ``"executed"`` (router succeeded), ``"error"`` (router raised).
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        market = await conn.fetchrow(
            "SELECT * FROM markets WHERE id=$1", cand.market_id,
        )
    if market is None:
        # market not synced yet — skip
        return "skipped"
    idem_key = f"{user['id']}:{cand.market_id}:{cand.side}:" \
               f"{cand.extra.get('src_tx', '')[:32]}"
    ctx_g = GateContext(
        user_id=user["id"],
        telegram_user_id=user["telegram_user_id"],
        role=user.get("role") or "user",
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
        return "rejected"
    try:
        await router_execute(
            chosen_mode=result.chosen_mode,
            user_id=user["id"],
            telegram_user_id=user["telegram_user_id"],
            role=user.get("role") or "user",
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
        return "error"
    return "executed"


# ---------------- Exit watcher ----------------

async def check_exits() -> dict:
    """Drive the exit-watcher worker for one tick. Returns RunResult as dict.

    The dict is captured by the APScheduler listener via ``event.retval`` and
    written to ``job_runs.metadata`` so operators can inspect per-tick counts
    (submitted/expired/held/errors) directly from the DB.
    """
    result = await exit_watcher.run_once()
    return {
        "submitted": result.submitted,
        "expired": result.expired,
        "held": result.held,
        "errors": result.errors,
    }


async def log_resumed_open_positions() -> dict:
    """WARP-54 §5: log how many pre-existing open positions exit_watcher is
    about to resume monitoring on startup.

    Runs once as a one-shot startup job (date trigger, immediate). The
    exit_watcher tick already picks up every row where ``status='open'``
    via ``registry.list_open_for_exit`` — this log line is the operator-
    visible proof that recovery happened after a Fly machine restart.

    Returns a dict captured by ``job_runs.metadata`` so the count is
    queryable from the DB without scraping logs.
    """
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            paper_open = int(await conn.fetchval(
                "SELECT COUNT(*) FROM positions WHERE status='open' AND mode='paper'"
            ) or 0)
            live_open = int(await conn.fetchval(
                "SELECT COUNT(*) FROM positions WHERE status='open' AND mode='live'"
            ) or 0)
    except Exception as exc:
        logger.error(
            "startup_recovery: open-position count query failed: %s",
            exc, exc_info=True,
        )
        return {"resumed_paper": None, "resumed_live": None, "error": str(exc)[:300]}

    logger.info(
        "startup_recovery: Resumed monitoring %d open positions (%d paper, %d live)",
        paper_open + live_open, paper_open, live_open,
    )
    return {"resumed_paper": paper_open, "resumed_live": live_open}


# ---------------- Portfolio snapshots ----------------

async def snapshot_portfolios() -> dict:
    """Write a `portfolio_snapshots` row for every user with paper activity.

    Keeps the `cb_portfolio` NOTIFY channel warm for WebTrader SSE listeners
    even when no trade closes happen in a tick — open-position mark-to-market
    drift is captured here, while realised closes write inline from
    ``domain/execution/paper.py:close_position``.
    """
    written = await portfolio_snapshots.snapshot_active_users()
    return {"snapshots_written": written}


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
    """Nightly deposit sweep.

    Logical mode (paper / default): flips ``deposits.swept`` so per-user
    balances are reconciled — no capital moves. Idempotent: a re-run only
    touches rows still ``swept=FALSE``.

    On-chain mode (EXECUTION_PATH_VALIDATED AND SWEEP_ONCHAIN_ENABLED):
    consolidates each user's EOA deposit wallet into the master hot-pool, then
    marks that user's confirmed deposits swept only after a confirmed transfer.
    """
    settings = get_settings()
    if settings.EXECUTION_PATH_VALIDATED and settings.SWEEP_ONCHAIN_ENABLED:
        await _sweep_deposits_onchain()
        return

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            count = await conn.fetchval(
                "WITH u AS ("
                " UPDATE deposits SET swept=TRUE WHERE swept=FALSE RETURNING 1"
                ") SELECT COUNT(*) FROM u"
            )
    logger.info("sweep_deposits: %s deposits marked swept", count)
    await audit.write(
        actor_role="bot",
        action="deposit_sweep",
        payload={"count": int(count)},
    )


async def _sweep_deposits_onchain() -> None:
    """Per-user on-chain consolidation into the master hot-pool.

    Runs sequentially (the cron job is max_instances=1) so the master wallet's
    gas-top-up nonces never race. A per-user failure is logged and skipped —
    one bad wallet never aborts the rest, and deposits are marked swept ONLY
    after that user's transfer confirms on-chain.
    """
    # Custody-mode dispatcher routes per-user sweep to either polygon_usdc
    # (EOA: master-funded gas top-up) or SafeCustody (gasless via relayer).
    # PreflightError is re-exported from custody so the typed error stays
    # uniform regardless of which custody backend handled the call.
    from .wallet.custody import PreflightError, sweep_usdc_to_master
    from .wallet.vault import get_decrypted_pk

    pool = get_pool()
    async with pool.acquire() as conn:
        users = await conn.fetch(
            "SELECT DISTINCT d.user_id, w.deposit_address "
            "FROM deposits d JOIN wallets w ON w.user_id = d.user_id "
            "WHERE d.swept = FALSE AND d.status = 'confirmed'"
        )

    swept_users = 0
    for u in users:
        try:
            pk = await get_decrypted_pk(u["user_id"])
            if pk is None:
                logger.error("sweep_skip user=%s: no wallet key", u["user_id"])
                continue
            result = await sweep_usdc_to_master(u["deposit_address"], pk)
        except PreflightError as exc:
            logger.warning("sweep_skip user=%s: %s", u["user_id"], exc)
            continue
        except Exception as exc:
            logger.error("sweep_failed user=%s error=%s", u["user_id"], exc)
            continue
        if result.get("skipped"):
            continue
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE deposits SET swept=TRUE "
                "WHERE user_id=$1 AND swept=FALSE AND status='confirmed'",
                u["user_id"],
            )
        swept_users += 1
        await audit.write(
            actor_role="bot",
            action="deposit_sweep_onchain",
            payload={"user_id": str(u["user_id"]),
                     "tx_hash": result.get("tx_hash"),
                     "amount_usdc": result.get("amount_usdc"),
                     "gas_topup_matic": result.get("gas_topup_matic")},
        )
    logger.info("sweep_deposits_onchain: %s user wallets swept", swept_users)


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
    # Capture structured return value from jobs that return dicts.
    # check_exits() returns RunResult-as-dict (submitted/expired/held/errors)
    # which is stored in job_runs.metadata for operator dashboards.
    retval = getattr(event, "retval", None) if success else None
    metadata = retval if isinstance(retval, dict) else None
    coro = job_tracker.record_job_event(
        job_id=event.job_id, success=success, error=err,
        started_at=started_at, metadata=metadata,
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
                  id="legacy_copy_trade_scan", max_instances=1, coalesce=True,
                  next_run_time=datetime.now(timezone.utc))
    sched.add_job(sf_scan_job.run_once, "interval", seconds=s.SIGNAL_SCAN_INTERVAL,
                  id="signal_following_scan", max_instances=1, coalesce=True,
                  next_run_time=datetime.now(timezone.utc))
    # Dedicated high-frequency loop for the close_sweep / late_entry_v3 preset:
    # Late Entry V3 only enters in the final ~35s of a crypto candle, which the
    # 180s main scan would miss. Runs only close_sweep users + late_entry_v3.
    sched.add_job(sf_scan_job.run_close_sweep_fast, "interval",
                  seconds=s.CLOSE_SWEEP_SCAN_INTERVAL,
                  id="close_sweep_fast_scan", max_instances=1, coalesce=True,
                  next_run_time=datetime.now(timezone.utc))
    sched.add_job(market_signal_scanner.run_job, "interval",
                  seconds=s.MARKET_SIGNAL_SCAN_INTERVAL,
                  id=market_signal_scanner.JOB_ID, max_instances=1, coalesce=True,
                  replace_existing=True,
                  next_run_time=datetime.now(timezone.utc))
    sched.add_job(market_sync.run_job, "interval",
                  seconds=300,   # was 1800 — 5 min for price freshness
                  id=market_sync.JOB_ID, max_instances=1, coalesce=True)
    sched.add_job(copy_trade_monitor.run_once, "interval",
                  seconds=s.COPY_TRADE_MONITOR_INTERVAL,
                  id="copy_trade_monitor", max_instances=1, coalesce=True)
    sched.add_job(leaderboard_sync.run_job, "interval",
                  seconds=1800,
                  id="leaderboard_sync", max_instances=1, coalesce=True,
                  next_run_time=datetime.now(timezone.utc))
    sched.add_job(check_exits, "interval", seconds=s.EXIT_WATCH_INTERVAL,
                  id="exit_watch", max_instances=1, coalesce=True)
    # Portfolio snapshots tick — drives the dormant `cb_portfolio` NOTIFY
    # channel so WebTrader SSE receives live equity updates even without
    # a trade close in the window (handles open-position mark-to-market
    # drift). 60s cadence matches the WebTrader heartbeat budget.
    sched.add_job(snapshot_portfolios, "interval",
                  seconds=s.PORTFOLIO_SNAPSHOT_INTERVAL,
                  id="portfolio_snapshots", max_instances=1, coalesce=True)
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
    # Track E — daily P&L report. Hour is configurable via DAILY_REPORT_HOUR
    # env (default 23). Timezone is resolved from s.TIMEZONE (Asia/Jakarta).
    sched.add_job(
        daily_pnl_report_job, "cron",
        hour=s.DAILY_REPORT_HOUR, minute=0,
        id=DAILY_REPORT_JOB_ID, max_instances=1, coalesce=True,
        replace_existing=True,
    )
    # Track F — auto-fallback monitor (60s poll).
    sched.add_job(
        run_auto_fallback_check, "interval",
        seconds=AUTO_FALLBACK_INTERVAL,
        id=AUTO_FALLBACK_JOB_ID, max_instances=1, coalesce=True,
    )
    # WARP-54 §5 — one-shot startup recovery log. Runs once at scheduler
    # boot via the ``date`` trigger with no run-time argument (immediate).
    # Surfaces "Resumed monitoring N open positions" so operators see proof
    # after a Fly machine restart that exit_watcher picked up pre-existing
    # positions (it always does via list_open_for_exit; this is the audit
    # trail).
    sched.add_job(
        log_resumed_open_positions, "date",
        id="startup_recovery_log", max_instances=1, coalesce=True,
        replace_existing=True,
    )
    sched.add_listener(
        _job_tracker_listener,
        EVENT_JOB_SUBMITTED | EVENT_JOB_EXECUTED | EVENT_JOB_ERROR,
    )
    return sched
