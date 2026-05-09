"""Live execution engine — real Polymarket CLOB orders via ClobClientProtocol.

Phase 4B: callers now go through get_clob_client() / ClobClientProtocol instead
of the legacy py-clob-client SDK path in integrations.polymarket.

Defense-in-depth: re-validates ALL five activation guards before submitting.
Persists order as 'pending' BEFORE submission to guarantee idempotency. Raises
typed errors so the router can decide whether a paper fallback is safe.

Close paths intentionally skip the open-time guard check: an existing live
position must be unwindable even when guards are later disabled.

Dry-run mode: if USE_REAL_CLOB=True but ENABLE_LIVE_TRADING is not set, the
execute() function logs the order intent and returns a mock fill without writing
to the DB or calling the broker. This lets operators test credential paths
without submitting real orders.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from uuid import UUID

from ... import audit, notifications
from ...config import get_settings
from ...database import get_pool
from ...integrations.clob import (
    ClobAuthError,
    ClobClientProtocol,
    ClobConfigError,
    MockClobClient,
    get_clob_client,
)
from ...wallet import ledger

logger = logging.getLogger(__name__)


class LivePreSubmitError(RuntimeError):
    """Raised before any CLOB submission — safe for the router to paper-fallback."""


class LivePostSubmitError(RuntimeError):
    """Raised after a CLOB submission has occurred — paper-fallback is UNSAFE."""


def assert_live_guards(access_tier: int, trading_mode: str) -> None:
    """Raise unless ALL activation guards pass.

    USE_REAL_CLOB is included as a guard because MockClobClient records
    mode='live' orders in the DB and debits the ledger without sending any
    real order to Polymarket — phantom live exposure. Requiring the real
    client here ensures the router also paper-falls-back when USE_REAL_CLOB
    is not set, even if all three env guards are enabled.
    """
    s = get_settings()
    if not s.ENABLE_LIVE_TRADING:
        raise LivePreSubmitError("ENABLE_LIVE_TRADING=false")
    if not s.EXECUTION_PATH_VALIDATED:
        raise LivePreSubmitError("EXECUTION_PATH_VALIDATED=false")
    if not s.CAPITAL_MODE_CONFIRMED:
        raise LivePreSubmitError("CAPITAL_MODE_CONFIRMED=false")
    if s.ENABLE_LIVE_TRADING and not s.USE_REAL_CLOB:
        raise LivePreSubmitError(
            "USE_REAL_CLOB must be True when ENABLE_LIVE_TRADING is set"
        )
    if access_tier < 4:
        raise LivePreSubmitError(f"tier {access_tier}<4")
    if trading_mode != "live":
        raise LivePreSubmitError(f"user trading_mode={trading_mode}")


async def execute(
    *,
    user_id: UUID,
    telegram_user_id: int,
    access_tier: int,
    trading_mode: str,
    market_id: str,
    market_question: str | None,
    yes_token_id: str | None,
    no_token_id: str | None,
    side: str,
    size_usdc: Decimal,
    price: float,
    idempotency_key: str,
    strategy_type: str,
    tp_pct: float | None,
    sl_pct: float | None,
    order_type: str = "GTC",
    clob_client: ClobClientProtocol | None = None,
) -> dict:
    """Execute a live buy order via ClobClientProtocol.

    idempotency_key must be a stable uuid derived from (signal_id, user_id,
    market_id) by the caller — retrying the same signal never double-submits.

    order_type: "GTC" (default) or "FOK". GTC fills partially and rests in
    book; FOK fills in full immediately or cancels.
    """
    s = get_settings()

    # Dry-run intercept: USE_REAL_CLOB=True but ENABLE_LIVE_TRADING not set.
    # Log intent for credential/workflow testing; do not touch DB or broker.
    if s.USE_REAL_CLOB and not s.ENABLE_LIVE_TRADING:
        token_id = yes_token_id if side == "yes" else no_token_id
        shares = float(size_usdc) / max(price, 0.0001)
        logger.info(
            "live.execute dry_run: USE_REAL_CLOB=True ENABLE_LIVE_TRADING=False "
            "token=%s side=%s shares=%.4f price=%.4f order_type=%s key=%s",
            token_id, side, shares, price, order_type, idempotency_key,
        )
        return {"status": "dry_run", "mode": "paper", "_mock": True}

    assert_live_guards(access_tier, trading_mode)

    token_id = yes_token_id if side == "yes" else no_token_id
    if not token_id:
        raise LivePreSubmitError("missing token_id for live order")

    # Convert USDC notional → exact share count at the entry price. We persist
    # both size_usdc and entry_price so close-side can recompute the same
    # share count and submit an exact-quantity SELL (no exit-price re-quoting).
    shares = float(size_usdc) / max(price, 0.0001)
    try:
        client = clob_client or get_clob_client(s)
    except ClobConfigError as exc:
        raise LivePreSubmitError(f"CLOB client config error: {exc}") from exc

    pool = get_pool()
    # Step 1: claim idempotency by inserting order as 'pending' BEFORE submit.
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO orders (user_id, market_id, side, size_usdc, price,
                                    mode, status, idempotency_key, strategy_type)
                VALUES ($1,$2,$3,$4,$5,'live','pending',$6,$7)
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING id
                """,
                user_id, market_id, side, size_usdc, price,
                idempotency_key, strategy_type,
            )
    if row is None:
        logger.info("live.execute idempotent skip key=%s", idempotency_key)
        return {"status": "duplicate", "mode": "live"}
    order_id = row["id"]

    # Step 2: SUBMIT via ClobClientProtocol.
    #
    # ClobAuthError means signing failed before any network call →
    # definitively pre-submit → safe for router to paper-fallback.
    #
    # All other exceptions are post-submit AMBIGUOUS — the order may have
    # been accepted by the broker even though we never received the ack
    # (timeout, dropped TLS, transient 5xx after queueing). Mark 'unknown',
    # alert operator for manual reconciliation, raise LivePostSubmitError
    # so the router REFUSES to paper-fallback (paper after a possible live
    # fill would duplicate exposure).
    try:
        submit_result = await client.post_order(
            token_id=token_id,
            side="BUY",
            price=price,
            size=shares,
            order_type=order_type,
        )
    except ClobAuthError as exc:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE orders SET status='failed', error_msg=$2 WHERE id=$1",
                order_id, str(exc)[:500],
            )
        await audit.write(actor_role="bot", action="live_pre_submit_failed",
                          user_id=user_id,
                          payload={"order_id": str(order_id),
                                   "error": str(exc)[:500]})
        raise LivePreSubmitError(f"prepare failed: {exc}") from exc
    except Exception as exc:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE orders SET status='unknown', error_msg=$2 WHERE id=$1",
                order_id, f"submit ambiguous: {str(exc)[:480]}",
            )
        await audit.write(actor_role="bot", action="live_submit_ambiguous",
                          user_id=user_id,
                          payload={"order_id": str(order_id),
                                   "error": str(exc)[:500]})
        try:
            await notifications.notify_operator(
                f"⚠️ *AMBIGUOUS LIVE SUBMIT*\n"
                f"order_id=`{order_id}` user=`{user_id}`\n"
                f"market=`{market_id}` side=`{side}` shares=`{shares:.4f}` "
                f"price=`{price:.4f}`\n"
                f"Reconcile via Polymarket dashboard before clearing.\n"
                f"err: `{str(exc)[:300]}`"
            )
        except Exception as notify_exc:
            logger.error("operator notify failed during ambiguous submit: %s",
                         notify_exc)
        raise LivePostSubmitError(
            f"ambiguous submit (order_id={order_id}): {exc}"
        ) from exc

    polymarket_order_id = (
        submit_result.get("orderID")
        or submit_result.get("order_id")
        or submit_result.get("id")
        or ""
    )

    # Step 3: persist position + ledger debit atomically with order update.
    # If this fails, the CLOB order EXISTS — raise LivePostSubmitError so
    # the router does not paper-duplicate.
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE orders SET status='submitted', polymarket_order_id=$2 "
                    "WHERE id=$1",
                    order_id, str(polymarket_order_id),
                )
                pos_row = await conn.fetchrow(
                    """
                    INSERT INTO positions (user_id, market_id, order_id, side,
                                           size_usdc, entry_price, current_price,
                                           tp_pct, sl_pct, mode, status)
                    VALUES ($1,$2,$3,$4,$5,$6,$6,$7,$8,'live','open')
                    RETURNING id
                    """,
                    user_id, market_id, order_id, side,
                    size_usdc, price, tp_pct, sl_pct,
                )
                position_id = pos_row["id"]
                await ledger.debit_in_conn(
                    conn, user_id, size_usdc, ledger.T_TRADE_OPEN,
                    ref_id=position_id, note=f"live open {side} {market_id}",
                )
    except Exception as exc:
        await audit.write(actor_role="bot", action="live_post_submit_db_error",
                          user_id=user_id,
                          payload={"order_id": str(order_id),
                                   "polymarket_order_id": str(polymarket_order_id),
                                   "error": str(exc)[:500]})
        raise LivePostSubmitError(
            f"live order submitted (id={polymarket_order_id}) but DB persist failed: {exc}"
        ) from exc

    await audit.write(actor_role="bot", action="live_open", user_id=user_id,
                      payload={"order_id": str(order_id),
                               "position_id": str(position_id),
                               "market_id": market_id,
                               "polymarket_order_id": str(polymarket_order_id),
                               "size_usdc": str(size_usdc),
                               "price": price})
    label = market_question or market_id
    await notifications.send(
        telegram_user_id,
        f"📈 *[LIVE] Opened*\n{label}\n*{side.upper()}* @ {price:.3f}\n"
        f"Size: ${size_usdc:.2f}",
    )
    return {"order_id": order_id, "position_id": position_id, "mode": "live"}


async def close_position(
    *,
    position: dict,
    exit_price: float,
    exit_reason: str,
    clob_client: ClobClientProtocol | None = None,
) -> dict:
    """Close an EXISTING live position via ClobClientProtocol.

    Does NOT re-check open-time guards — a real on-chain exposure must
    always be unwindable even if guards are later disabled.
    """
    s = get_settings()
    if not s.USE_REAL_CLOB:
        raise RuntimeError(
            "close_position called with USE_REAL_CLOB=False — "
            "MockClobClient cannot submit a real SELL; refusing to phantom-close "
            "a live position. Set USE_REAL_CLOB=True or reconcile manually."
        )

    pool = get_pool()
    async with pool.acquire() as conn:
        market = await conn.fetchrow(
            "SELECT yes_token_id, no_token_id FROM markets WHERE id=$1",
            position["market_id"],
        )
    token_id = (market["yes_token_id"] if position["side"] == "yes"
                else market["no_token_id"])
    if not token_id:
        raise RuntimeError("missing token_id for live close")

    # Close exactly the share count we acquired at open. Computing this from
    # the persisted size_usdc + entry_price guarantees open/close parity:
    # the close SELL submits the SAME quantity regardless of exit_price.
    entry = float(position["entry_price"])
    shares_to_sell = float(position["size_usdc"]) / max(entry, 0.0001)

    # Atomic claim BEFORE the external SELL: prevents a double on-chain SELL
    # when the exit watcher and a manual close fire concurrently on the same
    # open position. Only the winning UPDATE proceeds; the loser sees no row
    # and bails. Status flips to 'closing' for the duration of the submit.
    async with pool.acquire() as conn:
        claimed = await conn.fetchval(
            "UPDATE positions SET status='closing' "
            "WHERE id=$1 AND status='open' RETURNING id",
            position["id"],
        )
    if claimed is None:
        logger.info("live close skip — position %s already closing/closed",
                    position["id"])
        return {"pnl_usdc": Decimal("0"), "exit_price": exit_price,
                "exit_reason": "already_closed"}

    # Submit SELL via ClobClientProtocol. Any exception propagates to the
    # caller (order.py uses LIVE_CLOSE_MAX_ATTEMPTS=1 — single attempt).
    # On failure, roll the claim back to 'open' so a subsequent retry can
    # re-attempt cleanly.
    try:
        client = clob_client or get_clob_client(s)
    except ClobConfigError as exc:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE positions SET status='open' WHERE id=$1",
                position["id"],
            )
        raise RuntimeError(f"CLOB client config error during close: {exc}") from exc
    try:
        await client.post_order(
            token_id=token_id,
            side="SELL",
            price=exit_price,
            size=shares_to_sell,
            order_type="GTC",
        )
    except Exception:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE positions SET status='open' WHERE id=$1",
                position["id"],
            )
        raise

    size = Decimal(str(position["size_usdc"]))
    if position["side"] == "yes":
        ret_pct = (exit_price - entry) / max(entry, 1e-6)
    else:
        comp_entry = 1 - entry
        comp_exit = 1 - exit_price
        ret_pct = (comp_exit - comp_entry) / max(comp_entry, 1e-6)
    pnl = size * Decimal(str(ret_pct))
    proceeds = size + pnl

    async with pool.acquire() as conn:
        async with conn.transaction():
            updated = await conn.fetchval(
                "UPDATE positions SET status='closed', exit_reason=$2, "
                "current_price=$3, pnl_usdc=$4, closed_at=NOW() "
                "WHERE id=$1 AND status='closing' RETURNING id",
                position["id"], exit_reason, exit_price, pnl,
            )
            if updated is None:
                # The claim was ours; status should still be 'closing'. If we
                # reach this branch the SELL was already accepted on-chain —
                # surface for operator reconciliation rather than re-submit.
                logger.error("live close finalize: position %s no longer "
                             "'closing' after successful SELL — manual "
                             "reconciliation required", position["id"])
                return {"pnl_usdc": Decimal("0"), "exit_price": exit_price,
                        "exit_reason": "already_closed"}
            await ledger.credit_in_conn(
                conn, position["user_id"], proceeds, ledger.T_TRADE_CLOSE,
                ref_id=position["id"], note=f"live close {exit_reason}",
            )
    await audit.write(actor_role="bot", action="live_close",
                      user_id=position["user_id"],
                      payload={"position_id": str(position["id"]),
                               "exit_price": exit_price,
                               "exit_reason": exit_reason,
                               "pnl_usdc": str(pnl)})
    return {"pnl_usdc": pnl, "exit_price": exit_price, "exit_reason": exit_reason}
