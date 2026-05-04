"""APScheduler jobs — single async loop, all background work."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from . import audit, notifications
from .config import get_settings
from .database import get_pool
from .domain.execution.router import close as router_close, execute as router_execute
from .domain.risk.gate import GateContext, evaluate
from .domain.signal.copy_trade import CopyTradeStrategy
from .integrations import polygon, polymarket
from .users import set_tier
from .wallet import ledger
from .wallet.vault import get_wallet

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
    """Evaluate every open position against the priority exit chain:

        force_close > tp_hit > sl_hit > strategy_exit > hold

    Resolved markets are NOT closed here — they are settled via the
    redemption pipeline (check_resolutions → _redeem_position) so the
    payout uses the on-chain terminal value (1 / 0 USDC per share),
    not a re-quoted CLOB exit price.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        positions = await conn.fetch(
            """
            SELECT p.*, m.yes_price, m.no_price, m.status AS m_status,
                   m.resolved AS m_resolved, m.winning_side AS m_winning,
                   u.paused AS u_paused
              FROM positions p
              JOIN markets m ON m.id = p.market_id
              JOIN users u ON u.id = p.user_id
             WHERE p.status='open'
            """
        )
    for r in positions:
        try:
            await _evaluate_exit(dict(r))
        except Exception as exc:
            logger.error("exit eval failed for position %s: %s", r["id"], exc)


async def _strategy_should_exit(position: dict) -> bool:
    """Per-strategy exit hook (priority slot below sl_hit, above hold).

    No current strategy emits exit signals on its own — copy_trade enters and
    relies on tp/sl. This hook exists as the explicit branch demanded by the
    spec so future signal-driven exits drop in without disturbing priority.
    """
    return False


async def _evaluate_exit(p: dict) -> None:
    if p["m_resolved"]:
        # Resolved markets settle through the redemption pipeline.
        return

    side = p["side"]
    cur_price = float(p["yes_price"] if side == "yes" else p["no_price"]) \
        if (p["yes_price"] is not None and p["no_price"] is not None) \
        else float(p["entry_price"])
    entry = float(p["entry_price"])
    ret = (cur_price - entry) / max(entry, 1e-6) if side == "yes" \
        else ((1 - cur_price) - (1 - entry)) / max(1 - entry, 1e-6)

    # PRIORITY: force_close > tp_hit > sl_hit > strategy_exit > hold
    # NOTE: `u_paused` is NOT a force-close trigger. Per R11, Pause only
    # prevents NEW trade entries (enforced upstream in the risk gate); open
    # positions stay open. Force-close requires the explicit marker
    # set by the Pause+Close-All flow in emergency.pause_close.
    reason: str | None = None
    if bool(p.get("force_close")):
        reason = "force_close"
    elif p["tp_pct"] is not None and ret >= float(p["tp_pct"]):
        reason = "tp_hit"
    elif p["sl_pct"] is not None and ret <= -float(p["sl_pct"]):
        reason = "sl_hit"
    elif await _strategy_should_exit(p):
        reason = "strategy_exit"

    if reason is None:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE positions SET current_price=$1 WHERE id=$2",
                cur_price, p["id"],
            )
        return
    res = await router_close(position=p, exit_price=cur_price, exit_reason=reason)
    pool = get_pool()
    async with pool.acquire() as conn:
        u = await conn.fetchrow(
            "SELECT telegram_user_id FROM users WHERE id=$1", p["user_id"],
        )
    if u:
        await notifications.send(
            u["telegram_user_id"],
            f"📉 *Closed [{p['mode']}]* — {reason}\n"
            f"P&L: *${float(res['pnl_usdc']):+.2f}*",
        )


# ---------------- Resolution + redeem ----------------

async def check_resolutions() -> None:
    """Detect newly-resolved markets and trigger instant-redeem for opted-in users."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT p.market_id FROM positions p
              JOIN markets m ON m.id = p.market_id
             WHERE p.redeemed = FALSE
               AND m.resolved = FALSE
               AND ((p.status = 'open')
                    OR (p.status = 'closed'
                        AND m.resolution_at IS NOT NULL
                        AND m.resolution_at < NOW()))
            """
        )
    newly_resolved: list[str] = []
    for r in rows:
        try:
            m = await polymarket.get_market(r["market_id"])
            if not m or not m.get("closed"):
                continue
            outcomes = m.get("outcomePrices") or [0.5, 0.5]
            winning = "yes" if float(outcomes[0]) > 0.5 else "no"
            async with pool.acquire() as conn:
                changed = await conn.fetchval(
                    "UPDATE markets SET status='resolved', resolved=TRUE, "
                    "winning_side=$2 WHERE id=$1 AND resolved=FALSE RETURNING id",
                    r["market_id"], winning,
                )
            if changed:
                newly_resolved.append(r["market_id"])
        except Exception as exc:
            logger.error("resolution check failed for %s: %s",
                         r["market_id"], exc)
    for mid in newly_resolved:
        try:
            await _instant_redeem_for_market(mid)
        except Exception as exc:
            logger.error("instant redeem dispatch failed for %s: %s", mid, exc)


async def _instant_redeem_for_market(market_id: str) -> None:
    """R10: settle positions immediately for users with auto_redeem_mode='instant'.

    Live positions are gated by an on-chain gas-spike guard; if gas is above
    INSTANT_REDEEM_GAS_GWEI_MAX (or the gas read fails), they are deferred to
    the hourly queue. Paper positions never need a gas check.
    """
    s = get_settings()
    if not s.AUTO_REDEEM_ENABLED:
        return
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT p.*, m.winning_side, u.telegram_user_id, us.auto_redeem_mode
              FROM positions p
              JOIN markets m ON m.id = p.market_id
              JOIN users u ON u.id = p.user_id
              JOIN user_settings us ON us.user_id = p.user_id
             WHERE p.market_id = $1
               AND p.redeemed = FALSE
               AND m.resolved = TRUE
               AND us.auto_redeem_mode = 'instant'
            """,
            market_id,
        )
    if not rows:
        return
    gas_ok: bool | None = None  # cached gas decision per dispatch
    for p in rows:
        pd = dict(p)
        try:
            if pd["mode"] == "live" and pd["status"] == "open":
                if gas_ok is None:
                    try:
                        gwei = await polygon.gas_price_gwei()
                        gas_ok = gwei <= s.INSTANT_REDEEM_GAS_GWEI_MAX
                        if not gas_ok:
                            logger.warning(
                                "instant redeem gas-spike defer: %.1f gwei > %.1f — "
                                "hourly queue will retry",
                                gwei, s.INSTANT_REDEEM_GAS_GWEI_MAX,
                            )
                    except Exception as exc:
                        logger.error("instant redeem gas read failed: %s — "
                                     "deferring live closes to hourly queue", exc)
                        gas_ok = False
                if not gas_ok:
                    continue  # paper still proceeds; live waits for hourly retry
            await _redeem_position(pd)
        except Exception as exc:
            logger.error("instant redeem failed for %s: %s", pd["id"], exc)


async def redeem_hourly() -> None:
    """Hourly catch-up: settle every redeemable position regardless of mode setting."""
    s = get_settings()
    if not s.AUTO_REDEEM_ENABLED:
        return
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT p.*, m.winning_side, u.telegram_user_id
              FROM positions p
              JOIN markets m ON m.id = p.market_id
              JOIN users u ON u.id = p.user_id
             WHERE p.redeemed = FALSE
               AND m.resolved = TRUE
               AND m.winning_side IS NOT NULL
            """
        )
    if not rows:
        return
    for p in rows:
        try:
            await _redeem_position(dict(p))
        except Exception as exc:
            logger.error("redeem failed for %s: %s", p["id"], exc)


async def _ensure_live_redemption(market_id: str) -> None:
    """Submit the on-chain CTF.redeemPositions() tx ONCE per condition.

    All winning user positions in the same market settle internally against
    the master wallet's recovered USDC. Skips if EXECUTION_PATH_VALIDATED is
    off (live engine then falls back to the internal-payout path only —
    losing-side users redeem to 0, winning-side users get their share count
    credited; redemption tx will be issued later when the operator enables
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
    try:
        result = await polymarket.submit_live_redemption(cond)
    except Exception as exc:
        logger.error("live on-chain redemption failed for %s: %s", cond, exc)
        raise
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


async def _redeem_position(p: dict) -> None:
    """Settle a resolved position. Idempotent.

    Accounting model:
      • status='closed': position was exited before resolution; proceeds were
        already credited at close time. We ONLY mark redeemed=true. Crediting
        anything here would be a double-pay (the round-3 review bug).
      • status='open': pay the terminal value of the held shares directly to
        the user's internal ledger (winners: shares * 1 USDC, losers: 0).
        For LIVE positions, also trigger the master-wallet on-chain
        CTF.redeemPositions() tx via _ensure_live_redemption (deduped per
        condition).
    """
    pool = get_pool()
    won = p["side"] == p["winning_side"]

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
                         "winning_side": p["winning_side"],
                         "won": won},
            )
        return

    # Open at resolution: live → trigger on-chain redemption (idempotent per condition);
    # paper → no on-chain side-effect, just credit internally.
    if p["mode"] == "live":
        try:
            await _ensure_live_redemption(p["market_id"])
        except Exception as exc:
            logger.error("live redemption could not be guaranteed for %s "
                         "(internal credit will still post): %s", p["id"], exc)

    shares = Decimal(str(p["size_usdc"])) / Decimal(str(p["entry_price"]))
    payoff = shares if won else Decimal("0")
    pnl = payoff - Decimal(str(p["size_usdc"]))
    exit_price = 1.0 if won else 0.0
    exit_reason = "resolution_win" if won else "resolution_loss"

    async with pool.acquire() as conn:
        async with conn.transaction():
            updated = await conn.fetchval(
                """
                UPDATE positions
                   SET status='closed', exit_reason=$2, current_price=$3,
                       pnl_usdc=$4, closed_at=NOW(),
                       redeemed=TRUE, redeemed_at=NOW()
                 WHERE id=$1 AND status='open' AND redeemed=FALSE
                 RETURNING id
                """,
                p["id"], exit_reason, exit_price, pnl,
            )
            if updated is None:
                return
            if payoff > 0:
                await ledger.credit_in_conn(
                    conn, p["user_id"], payoff, ledger.T_REDEEM,
                    ref_id=p["id"], note=f"resolution payoff {p['winning_side']}",
                )

    await audit.write(actor_role="bot", action="redeem", user_id=p["user_id"],
                      payload={"position_id": str(p["id"]),
                               "winning_side": p["winning_side"],
                               "won": won,
                               "shares": str(shares),
                               "payoff": str(payoff)})
    if won:
        msg = (f"🏆 *Redeemed* — winning side `{p['winning_side']}`\n"
               f"Payoff: *${float(payoff):+.2f}*")
    else:
        msg = (f"❌ *Resolved against you* — winning side "
               f"`{p['winning_side']}`. Position closed at 0.")
    await notifications.send(p["telegram_user_id"], msg)


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


def setup_scheduler() -> AsyncIOScheduler:
    s = get_settings()
    sched = AsyncIOScheduler(timezone=s.TIMEZONE)
    sched.add_job(sync_markets, "interval", seconds=s.MARKET_SCAN_INTERVAL,
                  id="market_sync", max_instances=1, coalesce=True)
    sched.add_job(watch_deposits, "interval", seconds=s.DEPOSIT_WATCH_INTERVAL,
                  id="deposit_watch", max_instances=1, coalesce=True)
    sched.add_job(run_signal_scan, "interval", seconds=s.SIGNAL_SCAN_INTERVAL,
                  id="signal_scan", max_instances=1, coalesce=True)
    sched.add_job(check_exits, "interval", seconds=s.EXIT_WATCH_INTERVAL,
                  id="exit_watch", max_instances=1, coalesce=True)
    sched.add_job(redeem_hourly, "interval", seconds=s.REDEEM_INTERVAL,
                  id="redeem", max_instances=1, coalesce=True)
    sched.add_job(check_resolutions, "interval", seconds=s.RESOLUTION_CHECK_INTERVAL,
                  id="resolution", max_instances=1, coalesce=True)
    sched.add_job(sweep_deposits, "cron", hour=3, id="sweep", max_instances=1)
    return sched
