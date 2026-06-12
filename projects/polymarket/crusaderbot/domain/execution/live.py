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

import json
import logging
from decimal import Decimal
from uuid import UUID

from ... import audit, notifications
from ...config import get_settings
from ...database import get_pool
from ...services import portfolio_snapshots
from ...services.trade_notifications import TradeNotifier
from ...integrations.clob import (
    ClobAuthError,
    ClobClientProtocol,
    ClobConfigError,
    MarketDataClient,
    MockClobClient,
    get_clob_client,
)
from ...integrations.clob.user_client import (
    PerUserClobError,
    get_user_clob_client_with_wallet,
)
from ...wallet import ledger
from .per_user_clob import resolve_user_clob_client
from .slippage import compute_aggressive_limit_price
from ..risk.constants import LIVE_MIN_ORDER_SHARES, SLIPPAGE_GUARD_PCT

_notifier = TradeNotifier()

logger = logging.getLogger(__name__)


class LivePreSubmitError(RuntimeError):
    """Raised before any CLOB submission — safe for the router to paper-fallback."""


class LivePostSubmitError(RuntimeError):
    """Raised after a CLOB submission has occurred — paper-fallback is UNSAFE."""


def assert_live_guards(role: str, trading_mode: str) -> None:
    """Raise unless ALL activation guards pass.

    USE_REAL_CLOB is included as a guard because MockClobClient records
    mode='live' orders in the DB and debits the ledger without sending any
    real order to Polymarket — phantom live exposure. Requiring the real
    client here ensures the router also paper-falls-back when USE_REAL_CLOB
    is not set, even if all three env guards are enabled.

    role must equal 'admin' — live trading is owner-only while
    EXECUTION_PATH_VALIDATED / CAPITAL_MODE_CONFIRMED remain owner-gated.
    """
    s = get_settings()
    if not s.ENABLE_LIVE_TRADING:
        raise LivePreSubmitError("ENABLE_LIVE_TRADING=false")
    if not s.EXECUTION_PATH_VALIDATED:
        raise LivePreSubmitError("EXECUTION_PATH_VALIDATED=false")
    if not s.CAPITAL_MODE_CONFIRMED:
        raise LivePreSubmitError("CAPITAL_MODE_CONFIRMED=false")
    if not s.RISK_CONTROLS_VALIDATED:
        raise LivePreSubmitError("RISK_CONTROLS_VALIDATED=false")
    if not s.SECURITY_HARDENING_VALIDATED:
        raise LivePreSubmitError("SECURITY_HARDENING_VALIDATED=false")
    if s.ENABLE_LIVE_TRADING and not s.USE_REAL_CLOB:
        raise LivePreSubmitError(
            "USE_REAL_CLOB must be True when ENABLE_LIVE_TRADING is set"
        )
    if role != "admin":
        raise LivePreSubmitError(f"role={role!r} not admin")
    if trading_mode != "live":
        raise LivePreSubmitError(f"user trading_mode={trading_mode}")


async def execute(
    *,
    user_id: UUID,
    telegram_user_id: int,
    role: str,
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
    active_preset: str | None = None,
    strategy_metadata: dict | None = None,
    order_type: str = "GTC",
    best_ask: float | None = None,
    best_bid: float | None = None,
    clob_client: ClobClientProtocol | None = None,
) -> dict:
    """Execute a live buy order via ClobClientProtocol.

    idempotency_key must be a stable uuid derived from (signal_id, user_id,
    market_id) by the caller — retrying the same signal never double-submits.

    order_type: "GTC" (default) or "FOK". GTC fills partially and rests in
    book; FOK fills in full immediately or cancels.
    """
    s = get_settings()

    # Guard bypass detection (Track D Part A defense-in-depth).
    # live.execute() must ONLY be reached when ALL four activation guards are
    # SET. If this assertion fails, someone bypassed the router guard — log
    # CRITICAL before the regular assert_live_guards() raises.
    _all_guards_set = (
        s.ENABLE_LIVE_TRADING
        and s.EXECUTION_PATH_VALIDATED
        and s.CAPITAL_MODE_CONFIRMED
        and s.USE_REAL_CLOB
    )
    if not _all_guards_set:
        logger.critical(
            "GUARD_BYPASS_ATTEMPT: live.execute() called with incomplete guards "
            "ENABLE_LIVE_TRADING=%s EXECUTION_PATH_VALIDATED=%s "
            "CAPITAL_MODE_CONFIRMED=%s USE_REAL_CLOB=%s — "
            "routing via assert_live_guards for safe rejection",
            s.ENABLE_LIVE_TRADING, s.EXECUTION_PATH_VALIDATED,
            s.CAPITAL_MODE_CONFIRMED, s.USE_REAL_CLOB,
        )

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

    assert_live_guards(role, trading_mode)

    token_id = yes_token_id if side == "yes" else no_token_id
    if not token_id:
        raise LivePreSubmitError("missing token_id for live order")

    # Fast-path duplicate check before hitting external APIs.
    # The INSERT ON CONFLICT below is the true idempotency claim (handles races);
    # this early read ensures a replay on a temporarily unavailable MDC returns
    # the correct duplicate no-op instead of being routed to paper fallback.
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            _dup = await conn.fetchval(
                "SELECT id FROM orders WHERE idempotency_key = $1",
                idempotency_key,
            )
    except Exception as exc:
        logger.exception(
            "live.execute idempotency precheck failed key=%s", idempotency_key,
        )
        raise LivePreSubmitError(f"idempotency precheck failed: {exc}") from exc
    if _dup is not None:
        logger.info("live.execute idempotent skip (early) key=%s", idempotency_key)
        return {"status": "duplicate", "mode": "live"}

    # Fetch tick_size + neg_risk from the CLOB market data API.
    # tick_size: required for price rounding in the signed order.
    # neg_risk: selects the correct Exchange contract for signing.
    # Fail pre-submit so the router can paper-fallback cleanly rather than
    # hitting a post-submit ambiguous rejection on 0.001-tick or neg-risk markets.
    _tick_size: str = "0.01"
    _tick_size_f: float = 0.01
    _neg_risk: bool = False
    try:
        async with MarketDataClient() as _mdc:
            _raw_tick = await _mdc.get_tick_size(token_id)
            if not _raw_tick:
                raise ValueError(f"empty tick_size from CLOB API (token={token_id})")
            _tick_size = _raw_tick
            _tick_size_f = float(_tick_size)
            _neg_risk = await _mdc.get_neg_risk(token_id) or False
    except Exception as _exc:
        raise LivePreSubmitError(
            f"CLOB market metadata unavailable — refusing entry without tick_size/neg_risk "
            f"(token={token_id}): {_exc}"
        ) from _exc

    # Compute aggressive limit price if market-depth params supplied.
    # Uses best_ask + 1 tick for buys, best_bid - 1 tick for sells to
    # cross the spread aggressively and improve fill probability.
    # Falls back to the signal price when market-depth is unavailable.
    limit_price = (
        compute_aggressive_limit_price(
            side, best_ask=best_ask, best_bid=best_bid, offset_ticks=1,
            tick_size=_tick_size_f,
        )
        if best_ask is not None and best_bid is not None
        else price
    )

    # SLIPPAGE_GUARD_PCT fence (Track D Part C).
    # Hard rejection: if intended price deviates from signal price by > 5%,
    # the market has moved too far since signal generation — never submit.
    if price > 0:
        _slippage_pct = abs(limit_price - price) / price
        if _slippage_pct > SLIPPAGE_GUARD_PCT:
            logger.critical(
                "SLIPPAGE_REJECTED: limit_price=%.4f signal_price=%.4f "
                "deviation=%.4f > SLIPPAGE_GUARD_PCT=%.4f "
                "market=%s side=%s user=%s",
                limit_price, price, _slippage_pct, SLIPPAGE_GUARD_PCT,
                market_id, side, user_id,
            )
            raise LivePreSubmitError(
                f"SLIPPAGE_REJECTED: deviation {_slippage_pct:.4f} "
                f"> SLIPPAGE_GUARD_PCT {SLIPPAGE_GUARD_PCT}"
            )

    # Shares computed from limit_price so notional at entry is exact.
    shares = float(size_usdc) / max(limit_price, 0.0001)

    # MIN ORDER SIZE fence (#1801): a sub-minimum order is broker-rejected, so
    # fail closed pre-submit rather than spend an ambiguous network round-trip.
    if shares < LIVE_MIN_ORDER_SHARES:
        raise LivePreSubmitError(
            f"order below CLOB minimum: shares={shares:.4f} < "
            f"LIVE_MIN_ORDER_SHARES={LIVE_MIN_ORDER_SHARES} "
            f"(size_usdc={float(size_usdc):.4f} limit_price={limit_price:.4f})"
        )

    # Observability (#1801): one structured line carrying the full live
    # order-intent decision context — token/side, prices, spread, size,
    # tick/min constraints — so every intent is debuggable from logs alone.
    logger.info(
        "live_order_intent token=%s side=%s shares=%.4f limit_price=%.4f "
        "best_bid=%s best_ask=%s tick_size=%s neg_risk=%s min_shares=%.1f "
        "size_usdc=%.4f market=%s user=%s key=%s",
        token_id, side, shares, limit_price, best_bid, best_ask,
        _tick_size, _neg_risk, LIVE_MIN_ORDER_SHARES, float(size_usdc),
        market_id, user_id, idempotency_key,
    )

    # PRE-WARM the per-user client cache BEFORE we acquire the DB
    # connection (gemini #1741 CRITICAL): the SDK build path does vault
    # decryption + an on-chain RPC, and holding a Postgres transaction
    # open across that I/O would burn a connection slot for the duration.
    # After this call returns, the inside-the-transaction
    # ``resolve_user_clob_client`` is guaranteed to hit the cache. The
    # short cross-user isolation invariant (NULL column / drift) still
    # asserts INSIDE the transaction so the wallet read uses the same
    # snapshot as the orders-row INSERT.
    _use_per_user = (
        clob_client is None
        and getattr(s, "USE_PER_USER_EXECUTION", False)
        and getattr(s, "USE_REAL_CLOB", False)
    )
    if _use_per_user:
        try:
            await get_user_clob_client_with_wallet(user_id, s)
        except (ClobConfigError, ClobAuthError) as exc:
            raise LivePreSubmitError(f"CLOB client config error: {exc}") from exc
        except PerUserClobError as exc:
            # PerUserClobIsolationError on a non-UUID user_id can fire
            # here (the resolver re-checks but a deeper defense-in-depth
            # is cheap). Classify as pre-submit so the router can
            # paper-fallback cleanly.
            raise LivePreSubmitError(
                f"per-user CLOB isolation refused: {exc}"
            ) from exc

    # Step 1: claim idempotency by inserting order as 'pending' BEFORE submit.
    # When the per-user execution flag is on, we also use the SAME connection
    # to read wallets.polymarket_deposit_wallet for the cross-user isolation
    # assertion — same snapshot as the claim, no read-then-claim race.
    async with pool.acquire() as conn:
        async with conn.transaction():
            try:
                if _use_per_user:
                    # Cache is warm; resolver does ONE DB read + a
                    # case-insensitive compare + cache hit. Fast inside
                    # the transaction.
                    client = await resolve_user_clob_client(
                        user_id=user_id, conn=conn, settings=s,
                    )
                else:
                    client = clob_client or get_clob_client(s)
            except (ClobConfigError, ClobAuthError) as exc:
                raise LivePreSubmitError(f"CLOB client config error: {exc}") from exc
            except PerUserClobError as exc:
                # SAFETY-CRITICAL: WalletIdentityMismatch (drift) and
                # PerUserClobIsolationError (None/non-UUID user_id) are
                # surfaced cleanly so the router classifies them as
                # pre-submit (definitively NO broker call happened) and
                # the operator alert names the cross-user invariant.
                raise LivePreSubmitError(
                    f"per-user CLOB isolation refused: {exc}"
                ) from exc

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
            price=limit_price,
            size=shares,
            order_type=order_type,
            tick_size=_tick_size,
            neg_risk=_neg_risk,
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
                                           tp_pct, sl_pct, mode, status, strategy_type,
                                           market_question, active_preset,
                                           strategy_metadata)
                    VALUES ($1,$2,$3,$4,$5,$6,$6,$7,$8,'live','open',$9,$10,$11,
                            $12::jsonb)
                    RETURNING id
                    """,
                    user_id, market_id, order_id, side,
                    size_usdc, limit_price, tp_pct, sl_pct, strategy_type,
                    market_question, active_preset,
                    json.dumps(strategy_metadata) if strategy_metadata else None,
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
                               "signal_price": price,
                               "limit_price": limit_price,
                               "slippage_delta_submitted": round(limit_price - price, 6)})
    # Full TradeNotifier entry card — paper/live visibility parity: WebTrader
    # AlertCenter mirror + notification prefs + View/Close action buttons,
    # replacing the bare "[LIVE] Opened" text line. Entry price shown is the
    # submitted limit_price (matches the persisted positions.entry_price).
    # Wrapped fail-soft: this sits AFTER broker submit + DB persist, so a
    # notification-path error must never fail an order that already exists.
    try:
        await _notifier.notify_entry(
            telegram_user_id=telegram_user_id,
            market_id=market_id,
            market_question=market_question,
            side=side,
            size_usdc=size_usdc,
            price=limit_price,
            tp_pct=tp_pct,
            sl_pct=sl_pct,
            mode="live",
            strategy_type=strategy_type,
            position_id=str(position_id),
        )
    except Exception as notify_exc:  # noqa: BLE001 — order already live
        logger.error(
            "live entry notification failed (order unaffected) position=%s "
            "err=%s", position_id, notify_exc,
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

    _tick_size: str = "0.01"
    _neg_risk: bool = False
    try:
        async with MarketDataClient() as _mdc:
            _tick_size = await _mdc.get_tick_size(token_id) or "0.01"
            _neg_risk = await _mdc.get_neg_risk(token_id) or False
    except Exception as _exc:
        _tick_size = "0.01"
        logger.warning(
            "live.close_position: CLOB tick_size/neg_risk fetch failed — using defaults "
            "token=%s err=%s",
            token_id, str(_exc),
        )

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
            "WHERE id=$1 AND user_id=$2 AND status='open' RETURNING id",
            position["id"], position["user_id"],
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
    #
    # When the per-user execution flag is on, the close path also uses the
    # user's own deposit-wallet client (the close MUST be signed by the
    # same wallet that holds the position — a global-client close would
    # sign with the wrong funder and the broker would reject the order).
    # PRE-WARM the cache BEFORE the conn acquire (gemini #1741 CRITICAL)
    # so the wallet-identity assertion read inside the conn is the only
    # await that holds a connection slot.
    try:
        if (
            clob_client is None
            and getattr(s, "USE_PER_USER_EXECUTION", False)
            and getattr(s, "USE_REAL_CLOB", False)
        ):
            uid = UUID(str(position["user_id"]))
            await get_user_clob_client_with_wallet(uid, s)
            async with pool.acquire() as conn:
                client = await resolve_user_clob_client(
                    user_id=uid, conn=conn, settings=s,
                )
        else:
            client = clob_client or get_clob_client(s)
    except (ClobConfigError, ClobAuthError, PerUserClobError) as exc:
        # PerUserClobError covers WalletIdentityMismatch + isolation —
        # both must roll the position claim back to 'open' so a subsequent
        # retry (after the operator fixes the wallet column / user_id)
        # can re-attempt the close cleanly.
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE positions SET status='open' WHERE id=$1 AND user_id=$2",
                position["id"], position["user_id"],
            )
        raise RuntimeError(f"CLOB client error during close: {exc}") from exc
    try:
        sell_result = await client.post_order(
            token_id=token_id,
            side="SELL",
            price=exit_price,
            size=shares_to_sell,
            order_type="GTC",
            tick_size=_tick_size,
            neg_risk=_neg_risk,
        )
    except Exception:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE positions SET status='open' WHERE id=$1 AND user_id=$2",
                position["id"], position["user_id"],
            )
        raise

    # Persist the close SELL's broker order id + the closing timestamp BEFORE the
    # finalize txn. A crash in the (millisecond) window between this submit and the
    # 'closed' finalize strands the row in 'closing'; without the order id the
    # closing-position reconciler (WARP-74) cannot tell whether the SELL filled and
    # must page for a manual reconcile. Persisting them here shrinks that blind
    # window to the gap between post_order returning and this UPDATE.
    #
    # Deliberately BEST-EFFORT and kept OUT of the atomic 'closing' claim above:
    # closing_at / close_order_id are WARP-74 telemetry columns (migration 082). If
    # the code deploys before the migration, a missing column here only logs — the
    # core close (claim → SELL → finalize) never references the new columns and so
    # can never be bricked by deploy ordering. The reconciler treats a NULL
    # closing_at as reconcilable, so a skipped stamp loses no recovery coverage.
    close_order_id = str(
        (sell_result or {}).get("orderID")
        or (sell_result or {}).get("order_id")
        or (sell_result or {}).get("id")
        or (sell_result or {}).get("orderId")
        or ""
    )
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE positions SET close_order_id=$2, closing_at=NOW() "
                "WHERE id=$1 AND user_id=$3 AND status='closing'",
                position["id"], (close_order_id or None), position["user_id"],
            )
    except Exception as _exc:  # noqa: BLE001 — telemetry write must not break close
        logger.error(
            "live close: persisting close_order_id/closing_at failed (non-fatal) "
            "position=%s err=%s", position["id"], str(_exc),
        )

    size = Decimal(str(position["size_usdc"]))
    # Side-own price frame: exit_price/entry are the position's OWN outcome-token
    # price, so return = (exit - entry)/entry for BOTH sides (matches paper.py +
    # exit_watcher._return_pct). YES unchanged; corrected NO frame —
    # WARP/ROOT/no-side-pnl-frame.
    ret_pct = (exit_price - entry) / max(entry, 1e-6)
    pnl = size * Decimal(str(ret_pct))
    proceeds = size + pnl

    async with pool.acquire() as conn:
        async with conn.transaction():
            updated = await conn.fetchval(
                "UPDATE positions SET status='closed', exit_reason=$2, "
                "current_price=$3, pnl_usdc=$4, closed_at=NOW() "
                "WHERE id=$1 AND user_id=$5 AND status='closing' RETURNING id",
                position["id"], exit_reason, exit_price, pnl, position["user_id"],
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
    # Fire a portfolio_snapshots row so the cb_portfolio NOTIFY trigger
    # pushes the new equity/PnL to WebTrader SSE listeners — same contract
    # as the paper close path. Best-effort: the writer swallows its own
    # errors so a snapshot outage cannot corrupt the realised-close return.
    await portfolio_snapshots.write_snapshot(position["user_id"])
    return {"pnl_usdc": pnl, "exit_price": exit_price, "exit_reason": exit_reason}
