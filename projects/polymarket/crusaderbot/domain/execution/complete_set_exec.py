"""Complete-set arbitrage — PAPER two-leg booking primitive (Lane 2B).

Lane 1 (`domain/strategy/complete_set_arb.py`) sizes the largest profitable
complete set as a ``CompleteSetQuote``. This module books that quote in PAPER
mode: both outcome legs (YES + NO) of one binary market, atomically, as a linked
pair held to resolution.

Why a dedicated primitive (not `paper.execute`): a complete set is ONE economic
unit made of TWO `positions` rows that must reference each other via
``paired_position_id`` (migration 078), share a single idempotency identity, and
carry no mid-trade TP/SL (the exit is settlement, via the existing redeem path).
`paper.execute` books a single directional side and cannot express that.

SCOPE (Lane 2B): the booking transaction + its guards, fully unit-tested against
a fake connection. It is NOT yet called by any scan loop, registry, gate, or
preset — wiring (set-aware risk gate, scan branch, default-OFF flag) is Lane 2C,
and LIVE execution is Lane 3. Shipping unwired keeps runtime risk at zero while
the transaction shape is proven.

Pipeline boundary (target, Lane 2C+):
    RISK (set-aware, gated once on combined cost) -> [EXECUTION: this file] -> redeem
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog

from ... import audit, notifications
from ...config import get_settings
from ...database import get_pool
from ...integrations.clob import (
    ClobAuthError,
    ClobClientProtocol,
    ClobConfigError,
    MarketDataClient,
    get_clob_client,
)
from ...wallet import ledger
from ..ops import kill_switch
from ..strategy.complete_set_arb import (
    COMPLETE_SET_PAYOUT,
    CompleteSetQuote,
    _asks_ascending,
)
from .live import LivePostSubmitError, LivePreSubmitError, assert_live_guards

log = structlog.get_logger(__name__)

# strategy_type stamped on both legs so the rest of the system can recognise a
# complete-set position (exit watcher skips mid-trade TP/SL; UI groups the pair).
COMPLETE_SET_STRATEGY = "complete_set_arb"

# A naked leg that could NOT be unwound is persisted under a DISTINCT strategy
# type so the exit watcher does NOT hold it to resolution (the held-to-settlement
# rule keys on the exact string "complete_set_arb"). A naked leg is an UNhedged
# directional exposure that must remain force-exitable by the operator / preset
# sweeps — never silently parked until settlement.
COMPLETE_SET_NAKED_STRATEGY = "complete_set_arb_naked"

# FOK is atomic: a leg fully fills (status "matched") or is killed (no fill). We
# normalise the broker's fill status against the same vocabulary the WS handler
# uses so a wire-shape drift never reads a kill as a fill (which would strand a
# naked leg untracked).
_FILLED_STATUSES = frozenset(
    {"matched", "filled", "complete", "completed", "success"}
)


def _order_filled(result: dict[str, Any] | None) -> bool:
    """True iff a FOK order fully filled. Any ambiguity reads as NOT filled."""
    if not isinstance(result, dict):
        return False
    if result.get("success") is False:
        return False
    status = str(result.get("status") or "").strip().lower()
    if status.startswith("order_status_"):
        status = status[len("order_status_"):]
    return status in _FILLED_STATUSES


def _extract_order_id(result: dict[str, Any]) -> str:
    """Pull the broker order id out of a post_order result (tolerant of casing)."""
    return str(
        result.get("orderID")
        or result.get("order_id")
        or result.get("id")
        or ""
    )


def _bids_descending(book: dict[str, Any] | None) -> list[tuple[float, float]]:
    """Return [(price, size), ...] bids sorted best (highest) first, inside (0,1)."""
    if not isinstance(book, dict):
        return []
    bids = book.get("bids")
    if not isinstance(bids, list):
        return []
    out: list[tuple[float, float]] = []
    for b in bids:
        try:
            price = float(b["price"])
            size = float(b["size"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0.0 < price < 1.0 and 0.0 < size < float("inf"):
            out.append((price, size))
    out.sort(key=lambda lvl: lvl[0], reverse=True)
    return out


def _buy_fill_limit(
    book: dict[str, Any] | None, target_shares: float, tick: float,
) -> float | None:
    """Lowest limit price whose ask depth fully fills ``target_shares``, + 1 tick.

    Walks the ascending asks accumulating size; the worst (highest) level touched
    plus one tick is the FOK BUY limit that fills the whole quoted size in one
    shot. Returns ``None`` when the book no longer holds enough depth — the caller
    aborts pre-submit rather than risk a partial.
    """
    acc = 0.0
    worst = 0.0
    for price, size in _asks_ascending(book):
        worst = price
        acc += size
        if acc + 1e-9 >= target_shares:
            return min(0.99, round(worst + tick, 4))
    return None


def _sell_fill_limit(
    book: dict[str, Any] | None, target_shares: float, tick: float,
) -> float | None:
    """Highest limit price whose bid depth fully absorbs ``target_shares``, - 1 tick.

    Mirror of ``_buy_fill_limit`` for the unwind SELL: the worst (lowest) bid level
    needed to flatten the naked leg, minus one tick, crosses down aggressively so
    the FOK fills in full. ``None`` means the bid side cannot absorb the size — the
    unwind is not attemptable and the caller must HALT.
    """
    acc = 0.0
    worst = 0.0
    for price, size in _bids_descending(book):
        worst = price
        acc += size
        if acc + 1e-9 >= target_shares:
            return max(0.01, round(worst - tick, 4))
    return None


async def _insert_order(
    conn,
    *,
    user_id: UUID,
    market_id: str,
    side: str,
    size_usdc: Decimal,
    price: float,
    idempotency_key: str,
) -> UUID | None:
    """Insert one filled paper order; return its id, or None if the key dup'd."""
    row = await conn.fetchrow(
        """
        INSERT INTO orders (user_id, market_id, side, size_usdc, price,
                            mode, status, idempotency_key, strategy_type)
        VALUES ($1,$2,$3,$4,$5,'paper','filled',$6,$7)
        ON CONFLICT (idempotency_key) DO NOTHING
        RETURNING id
        """,
        user_id, market_id, side, size_usdc, price,
        idempotency_key, COMPLETE_SET_STRATEGY,
    )
    return row["id"] if row is not None else None


async def _insert_position(
    conn,
    *,
    user_id: UUID,
    market_id: str,
    order_id: UUID,
    side: str,
    size_usdc: Decimal,
    price: float,
    market_question: str | None,
    active_preset: str | None,
    strategy_metadata: dict,
) -> UUID:
    """Insert one open paper position leg (no TP/SL — held to settlement)."""
    row = await conn.fetchrow(
        """
        INSERT INTO positions (user_id, market_id, order_id, side,
                               size_usdc, entry_price, current_price,
                               tp_pct, sl_pct, mode, status, strategy_type,
                               market_question, active_preset,
                               strategy_metadata)
        VALUES ($1,$2,$3,$4,$5,$6,$6,NULL,NULL,'paper','open',$7,$8,$9,
                $10::jsonb)
        RETURNING id
        """,
        user_id, market_id, order_id, side,
        size_usdc, price, COMPLETE_SET_STRATEGY,
        market_question, active_preset,
        json.dumps(strategy_metadata),
    )
    return row["id"]


async def book_complete_set_paper(
    *,
    user_id: UUID,
    telegram_user_id: int,
    quote: CompleteSetQuote,
    market_question: str | None,
    idempotency_key: str,
    active_preset: str | None = None,
) -> dict:
    """Book both legs of a complete set in PAPER mode, atomically.

    In one DB transaction: insert 2 filled orders + 2 open positions, cross-link
    them via ``paired_position_id`` (the migration-078 deferrable FK validates the
    mutual links at COMMIT), and debit the ledger for each leg's cost. Both legs
    derive their idempotency key from ``idempotency_key`` (``:yes`` / ``:no``) so
    the set has a single replay identity.

    Returns:
        ``{"status": "open", ...}`` with both position ids on success;
        ``{"status": "duplicate"}`` if the set was already booked;
        ``{"status": "skipped", ...}`` for a degenerate (non-positive) quote.

    Raises:
        RuntimeError if exactly one leg's idempotency key is fresh (a half-booked
        set) — the transaction rolls back so a partial pair never persists.
    """
    shares = quote.fillable_shares
    if shares <= 0:
        # A complete set with no fillable shares is not bookable — never persist
        # a degenerate pair. (fillable_complete_set already guards this; defensive.)
        log.warning("complete_set_book_skip_nonpositive_shares",
                    market_id=quote.market_id, shares=shares)
        return {"status": "skipped", "reason": "non_positive_shares"}

    # Per-share leg prices from the quote's per-leg USDC cost.
    yes_price = round(quote.yes_cost_usdc / shares, 6)
    no_price = round(quote.no_cost_usdc / shares, 6)
    yes_cost = Decimal(str(quote.yes_cost_usdc))
    no_cost = Decimal(str(quote.no_cost_usdc))

    # Quote snapshot rides with both legs (exit/UI replay; observability).
    meta = {
        "complete_set": True,
        "condition_id": quote.condition_id,
        "fillable_shares": shares,
        "avg_pair_cost": quote.avg_pair_cost,
        "gross_margin_usdc": quote.gross_margin_usdc,
        "net_margin_usdc": quote.net_margin_usdc,
        "yes_token_id": quote.yes_token_id,
        "no_token_id": quote.no_token_id,
    }

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            yes_order = await _insert_order(
                conn, user_id=user_id, market_id=quote.market_id, side="yes",
                size_usdc=yes_cost, price=yes_price,
                idempotency_key=f"{idempotency_key}:yes",
            )
            no_order = await _insert_order(
                conn, user_id=user_id, market_id=quote.market_id, side="no",
                size_usdc=no_cost, price=no_price,
                idempotency_key=f"{idempotency_key}:no",
            )
            if yes_order is None and no_order is None:
                log.info("complete_set_idempotent_skip", idempotency_key=idempotency_key)
                return {"status": "duplicate", "mode": "paper"}
            if yes_order is None or no_order is None:
                # One leg fresh, one already booked → the pair is inconsistent.
                # Raise so the transaction rolls back; never leave a half set.
                raise RuntimeError(
                    f"complete_set partial idempotency for {idempotency_key}: "
                    f"yes={yes_order} no={no_order}"
                )

            yes_pos = await _insert_position(
                conn, user_id=user_id, market_id=quote.market_id, order_id=yes_order,
                side="yes", size_usdc=yes_cost, price=yes_price,
                market_question=market_question, active_preset=active_preset,
                strategy_metadata=meta,
            )
            no_pos = await _insert_position(
                conn, user_id=user_id, market_id=quote.market_id, order_id=no_order,
                side="no", size_usdc=no_cost, price=no_price,
                market_question=market_question, active_preset=active_preset,
                strategy_metadata=meta,
            )

            # Cross-link the legs. The mig-078 FK is DEFERRABLE INITIALLY
            # DEFERRED, so both directions validate at COMMIT.
            await conn.execute(
                "UPDATE positions SET paired_position_id = $1 WHERE id = $2",
                no_pos, yes_pos,
            )
            await conn.execute(
                "UPDATE positions SET paired_position_id = $1 WHERE id = $2",
                yes_pos, no_pos,
            )

            await ledger.debit_in_conn(
                conn, user_id, yes_cost, ledger.T_TRADE_OPEN,
                ref_id=yes_pos, note=f"paper complete-set YES {quote.market_id}",
            )
            await ledger.debit_in_conn(
                conn, user_id, no_cost, ledger.T_TRADE_OPEN,
                ref_id=no_pos, note=f"paper complete-set NO {quote.market_id}",
            )

    log.info(
        "paper_complete_set_open", user_id=str(user_id), market_id=quote.market_id,
        shares=shares, yes_cost=str(yes_cost), no_cost=str(no_cost),
        net_margin_usdc=quote.net_margin_usdc,
        yes_position_id=str(yes_pos), no_position_id=str(no_pos),
    )
    # Audit is best-effort — a logging failure must never unwind a booked set.
    try:
        await audit.write(
            actor_role="bot", action="paper_complete_set_open", user_id=user_id,
            payload={
                "market_id": quote.market_id,
                "yes_position_id": str(yes_pos),
                "no_position_id": str(no_pos),
                "shares": shares,
                "avg_pair_cost": quote.avg_pair_cost,
                "net_margin_usdc": quote.net_margin_usdc,
            },
        )
    except Exception:  # noqa: BLE001 — never let audit failure unwind the trade
        log.exception("complete_set_audit_write_failed", market_id=quote.market_id)

    return {
        "status": "open",
        "mode": "paper",
        "yes_position_id": yes_pos,
        "no_position_id": no_pos,
        "shares": shares,
    }


async def book_complete_set_live(
    *,
    user_id: UUID,
    telegram_user_id: int,
    role: str,
    trading_mode: str,
    quote: CompleteSetQuote,
    market_question: str | None,
    idempotency_key: str,
    yes_book: dict[str, Any] | None,
    no_book: dict[str, Any] | None,
    active_preset: str | None = None,
    clob_client: ClobClientProtocol | None = None,
) -> dict:
    """Book both legs of a complete set LIVE via two sequential FOK orders.

    Execution contract (owner-directed, naked-leg fallback = auto-unwind):

      1. Re-assert ALL five activation guards (defense-in-depth) — a guard miss
         raises ``LivePreSubmitError`` with zero exposure.
      2. Claim per-leg idempotency (``:yes`` / ``:no``) as 'pending' orders.
      3. Submit the YES leg FOK. A kill (no fill) aborts cleanly — the NO leg is
         never sent, so there is **no naked exposure**.
      4. YES filled -> submit the NO leg FOK. Both filled -> persist the linked
         pair (positions + ``paired_position_id`` + ledger) held to settlement.
      5. NO killed -> the YES leg is **naked** -> aggressive FOK SELL to flatten.
         Unwind filled -> flat (realised spread loss booked, no open position).
         Unwind failed -> persist the naked leg as a tracked, force-exitable
         position, engage the kill switch, page the operator.

    FOK limits are recomputed from live book depth so each leg either fills the
    whole quoted size or kills — there is no partial-fill branch to reconcile.

    Returns one of:
      ``open`` (pair booked) / ``no_fill`` (clean abort) / ``unwound`` (naked leg
      flattened) / ``naked_halt`` (unwind failed, halted) / ``duplicate`` /
      ``skipped``.

    Raises ``LivePreSubmitError`` for pre-submit aborts (safe — no order on-chain)
    and ``LivePostSubmitError`` for ambiguous post-submit states (caller must NOT
    duplicate; operator reconciles).
    """
    assert_live_guards(role, trading_mode)

    shares = quote.fillable_shares
    if shares <= 0:
        log.warning("complete_set_live_skip_nonpositive_shares",
                    market_id=quote.market_id, shares=shares)
        return {"status": "skipped", "reason": "non_positive_shares"}

    market_id = quote.market_id
    yes_cost = Decimal(str(quote.yes_cost_usdc))
    no_cost = Decimal(str(quote.no_cost_usdc))
    yes_key = f"{idempotency_key}:yes"
    no_key = f"{idempotency_key}:no"

    meta = {
        "complete_set": True,
        "condition_id": quote.condition_id,
        "fillable_shares": shares,
        "avg_pair_cost": quote.avg_pair_cost,
        "gross_margin_usdc": quote.gross_margin_usdc,
        "net_margin_usdc": quote.net_margin_usdc,
        "yes_token_id": quote.yes_token_id,
        "no_token_id": quote.no_token_id,
    }

    s = get_settings()
    pool = get_pool()

    # --- Idempotency precheck (fast skip before any external call) -----------
    try:
        async with pool.acquire() as conn:
            existing = await conn.fetchval(
                "SELECT COUNT(*) FROM orders WHERE idempotency_key = ANY($1::text[])",
                [yes_key, no_key],
            )
    except Exception as exc:
        raise LivePreSubmitError(
            f"complete_set_live idempotency precheck failed: {exc}"
        ) from exc
    if existing:
        log.info("complete_set_live_idempotent_skip", idempotency_key=idempotency_key)
        return {"status": "duplicate", "mode": "live"}

    # --- Pre-submit CLOB metadata for BOTH legs (fail -> abort, no exposure) --
    try:
        async with MarketDataClient() as mdc:
            yes_tick = await mdc.get_tick_size(quote.yes_token_id) or "0.01"
            no_tick = await mdc.get_tick_size(quote.no_token_id) or "0.01"
            yes_neg = await mdc.get_neg_risk(quote.yes_token_id) or False
            no_neg = await mdc.get_neg_risk(quote.no_token_id) or False
    except Exception as exc:
        raise LivePreSubmitError(
            f"CLOB metadata unavailable for complete-set legs: {exc}"
        ) from exc
    yes_tick_f = float(yes_tick)
    no_tick_f = float(no_tick)

    # FOK BUY limits that fully fill ``shares`` against the CURRENT book. None ->
    # depth evaporated since the quote; abort before any submit (no exposure).
    yes_limit = _buy_fill_limit(yes_book, shares, yes_tick_f)
    no_limit = _buy_fill_limit(no_book, shares, no_tick_f)
    if yes_limit is None or no_limit is None:
        raise LivePreSubmitError(
            "complete-set book depth insufficient at submit time "
            f"(yes={yes_limit} no={no_limit})"
        )
    # Arb invariant: the combined PAY price must stay strictly under the $1 payout,
    # else the set is not riskless. Never submit a non-arb complete set.
    if yes_limit + no_limit >= COMPLETE_SET_PAYOUT:
        raise LivePreSubmitError(
            f"complete-set limit sum {yes_limit + no_limit:.4f} >= "
            f"payout {COMPLETE_SET_PAYOUT} — not riskless"
        )

    try:
        client = clob_client or get_clob_client(s)
    except (ClobConfigError, ClobAuthError) as exc:
        raise LivePreSubmitError(f"CLOB client config error: {exc}") from exc

    # --- Claim both legs as 'pending' (race-safe idempotency) ----------------
    async with pool.acquire() as conn:
        async with conn.transaction():
            yes_order = await _insert_live_order(
                conn, user_id=user_id, market_id=market_id, side="yes",
                size_usdc=yes_cost, price=yes_limit,
                idempotency_key=yes_key, status="pending",
            )
            no_order = await _insert_live_order(
                conn, user_id=user_id, market_id=market_id, side="no",
                size_usdc=no_cost, price=no_limit,
                idempotency_key=no_key, status="pending",
            )
            if yes_order is None and no_order is None:
                return {"status": "duplicate", "mode": "live"}
            if yes_order is None or no_order is None:
                raise RuntimeError(
                    f"complete_set_live partial idempotency for {idempotency_key}: "
                    f"yes={yes_order} no={no_order}"
                )

    # --- Leg 1: YES FOK ------------------------------------------------------
    try:
        yes_res = await client.post_order(
            token_id=quote.yes_token_id, side="BUY", price=yes_limit, size=shares,
            order_type="FOK", tick_size=yes_tick, neg_risk=yes_neg,
        )
    except ClobAuthError as exc:
        # Signing failed before any network call -> no order on-chain -> safe abort.
        await _mark_order(yes_order, "failed", error=str(exc))
        await _mark_order(no_order, "cancelled")
        raise LivePreSubmitError(f"complete-set YES prepare failed: {exc}") from exc
    except Exception as exc:
        # Ambiguous: the YES order MAY be live. Do not send NO; halt + reconcile.
        await _mark_order(yes_order, "unknown", error=f"submit ambiguous: {exc}")
        await _mark_order(no_order, "cancelled")
        await _halt_and_alert(
            reason="complete_set_yes_ambiguous",
            detail=(f"YES leg submit AMBIGUOUS market=<code>{market_id}</code> "
                    f"order=<code>{yes_order}</code> — reconcile on Polymarket."),
        )
        raise LivePostSubmitError(
            f"complete-set YES ambiguous submit (order={yes_order}): {exc}"
        ) from exc

    if not _order_filled(yes_res):
        # FOK killed: nothing filled, NO leg never sent -> zero exposure.
        await _mark_order(yes_order, "cancelled")
        await _mark_order(no_order, "cancelled")
        log.info("complete_set_live_yes_no_fill", market_id=market_id)
        return {"status": "no_fill", "mode": "live", "leg": "yes"}

    yes_broker_id = _extract_order_id(yes_res)

    # --- Leg 2: NO FOK -------------------------------------------------------
    try:
        no_res = await client.post_order(
            token_id=quote.no_token_id, side="BUY", price=no_limit, size=shares,
            order_type="FOK", tick_size=no_tick, neg_risk=no_neg,
        )
    except ClobAuthError as exc:
        # YES is filled (naked); NO never reached the wire -> unwind the YES leg.
        log.warning("complete_set_live_no_prepare_failed_unwinding", error=str(exc))
        await _mark_order(no_order, "failed", error=str(exc))
        return await _unwind_naked_leg(
            client=client, pool=pool, user_id=user_id,
            telegram_user_id=telegram_user_id, quote=quote, naked_book=yes_book,
            naked_side="yes", naked_order=yes_order, naked_broker_id=yes_broker_id,
            naked_cost=yes_cost, naked_limit=yes_limit, shares=shares,
            tick=yes_tick, tick_f=yes_tick_f, neg_risk=yes_neg,
            market_question=market_question, active_preset=active_preset, meta=meta,
        )
    except Exception as exc:
        # NO leg ambiguous AND YES filled. We do NOT auto-unwind (an unwind SELL
        # could over-sell if NO actually filled). But the YES fill is CONFIRMED, so
        # it must be persisted + tracked BEFORE halting — otherwise the known live
        # exposure is invisible (no position row, no ledger debit) and a retry hits
        # the idempotency precheck and skips, hiding it until manual DB repair
        # (Codex P1). _persist_naked_halt marks yes_order filled, inserts the YES
        # leg as a force-exitable complete_set_arb_naked position, debits the
        # ledger, and halts + pages. NO stays 'unknown' for operator reconciliation.
        await _mark_order(no_order, "unknown", error=f"submit ambiguous: {exc}")
        await _persist_naked_halt(
            pool=pool, user_id=user_id, market_id=market_id, naked_order=yes_order,
            naked_side="yes", naked_cost=yes_cost,
            entry_price=round(quote.yes_cost_usdc / shares, 6),
            market_question=market_question, active_preset=active_preset,
            naked_meta={**meta, "naked_leg": "yes", "no_leg_ambiguous": True},
            reason=f"no_ambiguous_yes_filled:{exc}",
        )
        raise LivePostSubmitError(
            f"complete-set NO ambiguous after YES fill (yes={yes_order}, "
            f"tracked as naked): {exc}"
        ) from exc

    if not _order_filled(no_res):
        # NO killed, YES filled -> YES is naked -> auto-unwind.
        await _mark_order(no_order, "cancelled")
        log.warning("complete_set_live_no_killed_unwinding", market_id=market_id)
        return await _unwind_naked_leg(
            client=client, pool=pool, user_id=user_id,
            telegram_user_id=telegram_user_id, quote=quote, naked_book=yes_book,
            naked_side="yes", naked_order=yes_order, naked_broker_id=yes_broker_id,
            naked_cost=yes_cost, naked_limit=yes_limit, shares=shares,
            tick=yes_tick, tick_f=yes_tick_f, neg_risk=yes_neg,
            market_question=market_question, active_preset=active_preset, meta=meta,
        )

    no_broker_id = _extract_order_id(no_res)

    # --- Both legs filled: persist the linked pair atomically ----------------
    yes_price = round(quote.yes_cost_usdc / shares, 6)
    no_price = round(quote.no_cost_usdc / shares, 6)
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE orders SET status='filled', polymarket_order_id=$2 "
                    "WHERE id=$1", yes_order, yes_broker_id,
                )
                await conn.execute(
                    "UPDATE orders SET status='filled', polymarket_order_id=$2 "
                    "WHERE id=$1", no_order, no_broker_id,
                )
                yes_pos = await _insert_live_position(
                    conn, user_id=user_id, market_id=market_id, order_id=yes_order,
                    side="yes", size_usdc=yes_cost, price=yes_price,
                    market_question=market_question, active_preset=active_preset,
                    strategy_metadata=meta, strategy_type=COMPLETE_SET_STRATEGY,
                )
                no_pos = await _insert_live_position(
                    conn, user_id=user_id, market_id=market_id, order_id=no_order,
                    side="no", size_usdc=no_cost, price=no_price,
                    market_question=market_question, active_preset=active_preset,
                    strategy_metadata=meta, strategy_type=COMPLETE_SET_STRATEGY,
                )
                await conn.execute(
                    "UPDATE positions SET paired_position_id=$1 WHERE id=$2",
                    no_pos, yes_pos,
                )
                await conn.execute(
                    "UPDATE positions SET paired_position_id=$1 WHERE id=$2",
                    yes_pos, no_pos,
                )
                await ledger.debit_in_conn(
                    conn, user_id, yes_cost, ledger.T_TRADE_OPEN,
                    ref_id=yes_pos, note=f"live complete-set YES {market_id}",
                )
                await ledger.debit_in_conn(
                    conn, user_id, no_cost, ledger.T_TRADE_OPEN,
                    ref_id=no_pos, note=f"live complete-set NO {market_id}",
                )
    except Exception as exc:
        # Both legs are filled on-chain but persistence failed -> never paper or
        # retry-duplicate. Halt + operator reconciliation.
        await _halt_and_alert(
            reason="complete_set_persist_failed",
            detail=(f"BOTH legs filled but DB persist FAILED market=<code>{market_id}</code> "
                    f"yes_order=<code>{yes_order}</code> no_order=<code>{no_order}</code>"
                    f" — reconcile positions/ledger manually."),
        )
        raise LivePostSubmitError(
            f"complete-set both legs filled but persist failed ({market_id}): {exc}"
        ) from exc

    log.info("live_complete_set_open", user_id=str(user_id), market_id=market_id,
             shares=shares, yes_position_id=str(yes_pos), no_position_id=str(no_pos),
             net_margin_usdc=quote.net_margin_usdc)
    try:
        await audit.write(
            actor_role="bot", action="live_complete_set_open", user_id=user_id,
            payload={"market_id": market_id, "yes_position_id": str(yes_pos),
                     "no_position_id": str(no_pos), "shares": shares,
                     "yes_broker_id": yes_broker_id, "no_broker_id": no_broker_id,
                     "avg_pair_cost": quote.avg_pair_cost,
                     "net_margin_usdc": quote.net_margin_usdc},
        )
    except Exception:  # noqa: BLE001 — audit failure must never unwind a booked set
        log.exception("complete_set_live_audit_write_failed", market_id=market_id)
    try:
        await notifications.send(
            telegram_user_id,
            f"🎯 <b>[LIVE] Complete-set opened</b>\n{market_question or market_id}\n"
            f"shares={shares:.2f} cost=${quote.total_cost_usdc:.2f} "
            f"net_margin=${quote.net_margin_usdc:.2f}",
        )
    except Exception:  # noqa: BLE001
        log.exception("complete_set_live_notify_failed", market_id=market_id)

    return {"status": "open", "mode": "live", "yes_position_id": yes_pos,
            "no_position_id": no_pos, "shares": shares}


async def _unwind_naked_leg(
    *,
    client: ClobClientProtocol,
    pool,
    user_id: UUID,
    telegram_user_id: int,
    quote: CompleteSetQuote,
    naked_book: dict[str, Any] | None,
    naked_side: str,
    naked_order: UUID,
    naked_broker_id: str,
    naked_cost: Decimal,
    naked_limit: float,
    shares: float,
    tick: str,
    tick_f: float,
    neg_risk: bool,
    market_question: str | None,
    active_preset: str | None,
    meta: dict,
) -> dict:
    """Flatten a naked complete-set leg with an aggressive FOK SELL.

    Success -> the leg is round-tripped flat: book the realised spread loss to the
    ledger (debit cost, credit proceeds), persist NO open position.
    Failure (no bid depth, kill, or broker error) -> the exposure cannot be
    flattened automatically: persist the naked leg as a tracked, force-exitable
    position, engage the kill switch, and page the operator.
    """
    market_id = quote.market_id
    token_id = quote.yes_token_id if naked_side == "yes" else quote.no_token_id
    entry_price = round(float(naked_cost) / shares, 6) if shares > 0 else naked_limit
    naked_meta = {**meta, "naked_leg": naked_side, "unwind": True}

    sell_limit = _sell_fill_limit(naked_book, shares, tick_f)
    if sell_limit is None:
        return await _persist_naked_halt(
            pool=pool, user_id=user_id, market_id=market_id, naked_order=naked_order,
            naked_side=naked_side, naked_cost=naked_cost, entry_price=entry_price,
            market_question=market_question, active_preset=active_preset,
            naked_meta=naked_meta, reason="no_bid_depth",
        )

    try:
        sell_res = await client.post_order(
            token_id=token_id, side="SELL", price=sell_limit, size=shares,
            order_type="FOK", tick_size=tick, neg_risk=neg_risk,
        )
    except Exception as exc:  # noqa: BLE001 — any error means the leg stays naked
        log.error("complete_set_unwind_submit_failed", market_id=market_id,
                  error=str(exc))
        return await _persist_naked_halt(
            pool=pool, user_id=user_id, market_id=market_id, naked_order=naked_order,
            naked_side=naked_side, naked_cost=naked_cost, entry_price=entry_price,
            market_question=market_question, active_preset=active_preset,
            naked_meta=naked_meta, reason=f"unwind_error:{exc}",
        )

    if not _order_filled(sell_res):
        return await _persist_naked_halt(
            pool=pool, user_id=user_id, market_id=market_id, naked_order=naked_order,
            naked_side=naked_side, naked_cost=naked_cost, entry_price=entry_price,
            market_question=market_question, active_preset=active_preset,
            naked_meta=naked_meta, reason="unwind_fok_killed",
        )

    # Unwind filled -> flat. Realised proceeds at the (conservative) sell limit;
    # FOK fills at limit-or-better so this never overstates the credited balance.
    proceeds = Decimal(str(round(sell_limit * shares, 6)))
    realised = proceeds - naked_cost
    unwind_broker_id = _extract_order_id(sell_res)
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE orders SET status='filled', polymarket_order_id=$2 "
                    "WHERE id=$1", naked_order, naked_broker_id,
                )
                unwind_order = await _insert_live_order(
                    conn, user_id=user_id, market_id=market_id, side=naked_side,
                    size_usdc=proceeds, price=sell_limit,
                    idempotency_key=f"{naked_broker_id or naked_order}:unwind",
                    status="filled",
                )
                await ledger.debit_in_conn(
                    conn, user_id, naked_cost, ledger.T_TRADE_OPEN,
                    ref_id=naked_order, note=f"live naked {naked_side} {market_id}",
                )
                await ledger.credit_in_conn(
                    conn, user_id, proceeds, ledger.T_TRADE_CLOSE,
                    ref_id=(unwind_order or naked_order),
                    note=f"live naked-unwind {naked_side} {market_id}",
                )
    except Exception as exc:
        # The SELL filled on-chain but we could not book it -> halt + reconcile.
        await _halt_and_alert(
            reason="complete_set_unwind_persist_failed",
            detail=(f"Naked {naked_side} leg UNWOUND on-chain but ledger persist FAILED "
                    f"market=<code>{market_id}</code> order=<code>{naked_order}</code>"),
        )
        raise LivePostSubmitError(
            f"complete-set unwind filled but persist failed ({market_id}): {exc}"
        ) from exc

    log.warning("complete_set_naked_unwound", market_id=market_id,
                naked_side=naked_side, realised_usdc=str(realised))
    try:
        await audit.write(
            actor_role="bot", action="live_complete_set_unwound", user_id=user_id,
            payload={"market_id": market_id, "naked_side": naked_side,
                     "shares": shares, "realised_usdc": str(realised),
                     "unwind_broker_id": unwind_broker_id},
        )
    except Exception:  # noqa: BLE001
        log.exception("complete_set_unwind_audit_failed", market_id=market_id)
    try:
        await notifications.notify_operator(
            f"♻️ <b>COMPLETE-SET NAKED LEG AUTO-UNWOUND</b>\n"
            f"market=<code>{market_id}</code> side={naked_side} "
            f"realised=${realised:.4f} (spread loss). Trading continues."
        )
    except Exception:  # noqa: BLE001
        log.exception("complete_set_unwind_notify_failed", market_id=market_id)

    return {"status": "unwound", "mode": "live", "naked_leg": naked_side,
            "realised_usdc": realised, "shares": shares}


async def _persist_naked_halt(
    *,
    pool,
    user_id: UUID,
    market_id: str,
    naked_order: UUID,
    naked_side: str,
    naked_cost: Decimal,
    entry_price: float,
    market_question: str | None,
    active_preset: str | None,
    naked_meta: dict,
    reason: str,
) -> dict:
    """Unwind failed: persist the naked leg as a tracked position, halt, alert.

    The leg is stamped ``COMPLETE_SET_NAKED_STRATEGY`` (NOT the held-to-settlement
    ``complete_set_arb``) so the exit watcher and preset sweeps can still force it
    out. Capital really left on the buy, so the ledger is debited for the cost.
    """
    position_id: UUID | None = None
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE orders SET status='filled' WHERE id=$1", naked_order,
                )
                position_id = await _insert_live_position(
                    conn, user_id=user_id, market_id=market_id, order_id=naked_order,
                    side=naked_side, size_usdc=naked_cost, price=entry_price,
                    market_question=market_question, active_preset=active_preset,
                    strategy_metadata={**naked_meta, "unwind_failed_reason": reason},
                    strategy_type=COMPLETE_SET_NAKED_STRATEGY,
                )
                await ledger.debit_in_conn(
                    conn, user_id, naked_cost, ledger.T_TRADE_OPEN,
                    ref_id=position_id, note=f"live naked {naked_side} {market_id}",
                )
    except Exception:  # noqa: BLE001 — never let persistence failure swallow the halt
        log.exception("complete_set_naked_persist_failed", market_id=market_id,
                      naked_side=naked_side)
    try:
        await audit.write(
            actor_role="bot", action="live_complete_set_naked_halt", user_id=user_id,
            payload={"market_id": market_id, "naked_side": naked_side,
                     "reason": reason, "position_id": str(position_id),
                     "size_usdc": str(naked_cost)},
        )
    except Exception:  # noqa: BLE001
        log.exception("complete_set_naked_halt_audit_failed", market_id=market_id)
    await _halt_and_alert(
        reason="complete_set_naked_leg",
        detail=(f"market=<code>{market_id}</code> side={naked_side} "
                f"cost=${naked_cost} reason={reason}\n"
                f"Naked leg persisted as <code>{position_id}</code> "
                f"(force-exitable). Reconcile + resume manually."),
    )
    return {"status": "naked_halt", "mode": "live", "naked_leg": naked_side,
            "position_id": position_id, "reason": reason}


async def _insert_live_order(
    conn,
    *,
    user_id: UUID,
    market_id: str,
    side: str,
    size_usdc: Decimal,
    price: float,
    idempotency_key: str,
    status: str,
) -> UUID | None:
    """Claim one live order row; return its id, or None if the key already exists."""
    row = await conn.fetchrow(
        """
        INSERT INTO orders (user_id, market_id, side, size_usdc, price,
                            mode, status, idempotency_key, strategy_type)
        VALUES ($1,$2,$3,$4,$5,'live',$6,$7,$8)
        ON CONFLICT (idempotency_key) DO NOTHING
        RETURNING id
        """,
        user_id, market_id, side, size_usdc, price, status,
        idempotency_key, COMPLETE_SET_STRATEGY,
    )
    return row["id"] if row is not None else None


async def _insert_live_position(
    conn,
    *,
    user_id: UUID,
    market_id: str,
    order_id: UUID,
    side: str,
    size_usdc: Decimal,
    price: float,
    market_question: str | None,
    active_preset: str | None,
    strategy_metadata: dict,
    strategy_type: str,
) -> UUID:
    """Insert one open live position leg (no TP/SL — settlement or operator exit)."""
    row = await conn.fetchrow(
        """
        INSERT INTO positions (user_id, market_id, order_id, side,
                               size_usdc, entry_price, current_price,
                               tp_pct, sl_pct, mode, status, strategy_type,
                               market_question, active_preset,
                               strategy_metadata)
        VALUES ($1,$2,$3,$4,$5,$6,$6,NULL,NULL,'live','open',$7,$8,$9,
                $10::jsonb)
        RETURNING id
        """,
        user_id, market_id, order_id, side, size_usdc, price, strategy_type,
        market_question, active_preset, json.dumps(strategy_metadata),
    )
    return row["id"]


async def _mark_order(
    order_id: UUID, status: str, *, broker_id: str = "", error: str = "",
) -> None:
    """Best-effort terminal-status write for a claimed live order row."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE orders SET status=$2, polymarket_order_id=$3, error_msg=$4 "
                "WHERE id=$1",
                order_id, status, broker_id, (error[:500] or None),
            )
    except Exception:  # noqa: BLE001 — status bookkeeping must never raise over the trade
        log.exception("complete_set_live_mark_order_failed",
                      order_id=str(order_id), status=status)


async def _halt_and_alert(*, reason: str, detail: str) -> None:
    """Engage the operator kill switch and page the operator. Both best-effort.

    A naked leg we could not unwind is a real, unhedged on-chain exposure: stop the
    bot from opening anything new and put a human in the loop immediately. Neither
    the halt nor the alert may raise — the caller still has to persist the naked
    position so it is tracked even if paging fails.
    """
    try:
        await kill_switch.set_active(action="pause", reason=reason)
    except Exception:  # noqa: BLE001
        log.exception("complete_set_naked_halt_killswitch_failed", reason=reason)
    try:
        await notifications.notify_operator(
            f"🛑 <b>COMPLETE-SET NAKED LEG — TRADING HALTED</b>\n{detail}"
        )
    except Exception:  # noqa: BLE001
        log.exception("complete_set_naked_halt_notify_failed")


__all__ = [
    "book_complete_set_paper",
    "book_complete_set_live",
    "COMPLETE_SET_STRATEGY",
    "COMPLETE_SET_NAKED_STRATEGY",
]
