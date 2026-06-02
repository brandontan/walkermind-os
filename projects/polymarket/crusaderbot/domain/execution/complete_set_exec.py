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
import logging
from decimal import Decimal
from uuid import UUID

import structlog

from ... import audit
from ...database import get_pool
from ...wallet import ledger
from ..strategy.complete_set_arb import CompleteSetQuote

logger = logging.getLogger(__name__)
log = structlog.get_logger(__name__)

# strategy_type stamped on both legs so the rest of the system can recognise a
# complete-set position (exit watcher skips mid-trade TP/SL; UI groups the pair).
COMPLETE_SET_STRATEGY = "complete_set_arb"


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
                logger.info("complete_set idempotent skip key=%s", idempotency_key)
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


__all__ = ["book_complete_set_paper", "COMPLETE_SET_STRATEGY"]
