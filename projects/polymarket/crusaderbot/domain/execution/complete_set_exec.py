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
    ClobCircuitOpenError,
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

# Errors that GUARANTEE the order never reached the broker (no network call), so
# the leg is in a definitively known state — safe to abort/unwind/persist rather
# than treat as an ambiguous post-submit. ClobAuthError = signing/4xx before send;
# ClobCircuitOpenError = breaker OPEN, rejected with NO broker call. Every OTHER
# exception is ambiguous (the order MAY be live) and must halt + reconcile.
_PRE_SUBMIT_ERRORS = (ClobAuthError, ClobCircuitOpenError)

# strategy_type stamped on both legs so the rest of the system can recognise a
# complete-set position (exit watcher skips mid-trade TP/SL; UI groups the pair).
COMPLETE_SET_STRATEGY = "complete_set_arb"

# A naked leg that could NOT be unwound is persisted under a DISTINCT strategy
# type so the exit watcher does NOT hold it to resolution (the held-to-settlement
# rule keys on the exact string "complete_set_arb"). A naked leg is an UNhedged
# directional exposure that must remain force-exitable by the operator / preset
# sweeps — never silently parked until settlement.
COMPLETE_SET_NAKED_STRATEGY = "complete_set_arb_naked"

# A FOK leg resolves to exactly one of three states. We normalise the broker's
# status against the same vocabulary the WS handler uses so a wire-shape drift
# never reads a kill as a fill (which would strand a naked leg untracked).
#
# FILLED   — definitively matched in full.
# KILLED   — definitively rejected / not matched (clean, no exposure).
# AMBIGUOUS — accepted but NOT yet terminal (e.g. Polymarket's `delayed` marketable
#             window) OR an unrecognised/empty status. The order MAY still match,
#             so this is treated as a post-submit ambiguity (halt + operator
#             reconcile) — never as a clean kill, which could hide a later fill.
_FILLED_STATUSES = frozenset(
    {"matched", "filled", "complete", "completed", "success"}
)
_KILLED_STATUSES = frozenset(
    {"unmatched", "killed", "kill", "cancelled", "canceled", "expired",
     "rejected", "failed"}
)

FILL_FILLED = "filled"
FILL_KILLED = "killed"
FILL_AMBIGUOUS = "ambiguous"


def _fill_status(result: dict[str, Any] | None) -> str:
    """Classify a FOK post_order result as filled / killed / ambiguous.

    Only an explicit terminal status maps to filled or killed; ANYTHING uncertain
    (accepted-not-matched, unknown, empty, malformed) maps to ambiguous so the
    caller halts and reconciles rather than silently treating it as a clean kill.
    """
    if not isinstance(result, dict):
        return FILL_AMBIGUOUS
    status = str(result.get("status") or "").strip().lower()
    if status.startswith("order_status_"):
        status = status[len("order_status_"):]
    if status in _FILLED_STATUSES:
        return FILL_FILLED
    if status in _KILLED_STATUSES:
        return FILL_KILLED
    # An explicit success=False with no terminal status is a clean rejection.
    if result.get("success") is False and not status:
        return FILL_KILLED
    return FILL_AMBIGUOUS


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


def _fill_plan(
    book: dict[str, Any] | None, target_shares: float, tick: float,
) -> tuple[float | None, float]:
    """Plan a FOK BUY of ``target_shares`` against the current asks.

    Walks the ascending asks, capping the last level to the shares still needed,
    and returns ``(limit_price, weighted_cost)``:
      * ``limit_price`` = worst (highest) level touched + 1 tick — the FOK BUY limit
        that fills the whole size in one shot (clamped to < 1.0).
      * ``weighted_cost`` = sum(price * filled_size) over the consumed depth — the
        USDC the order actually spends at the CURRENT book, used for the persisted
        size_usdc + ledger debit so accounting never drifts from the scan-time quote.
    Returns ``(None, 0.0)`` when the book lacks depth for the full size — the caller
    aborts pre-submit rather than risk a partial.
    """
    acc = 0.0
    cost = 0.0
    worst = 0.0
    for price, size in _asks_ascending(book):
        take = min(size, target_shares - acc)
        if take <= 0.0:
            break
        cost += price * take
        acc += take
        worst = price
        if acc + 1e-9 >= target_shares:
            return min(0.99, round(worst + tick, 4)), round(cost, 6)
    return None, 0.0


def _sell_plan(
    book: dict[str, Any] | None, target_shares: float, tick: float,
) -> tuple[float | None, float]:
    """Plan a FOK SELL of ``target_shares`` against the current bids.

    Mirror of ``_fill_plan`` for the unwind SELL. Walks the bids best (highest)
    first, capping the last level, and returns ``(limit_price, weighted_proceeds)``:
      * ``limit_price`` = worst (lowest) bid level needed to absorb the size, minus
        one tick — crosses down aggressively so the FOK fills in full (>= 0.01).
      * ``weighted_proceeds`` = sum(price * filled_size) over the consumed bids — the
        USDC the SELL actually returns. An FOK fills at the limit OR BETTER, so the
        weighted proceeds (>= limit * shares) is the accurate credit; using the bare
        limit would permanently understate the wallet on every unwind.
    ``(None, 0.0)`` means the bid side cannot absorb the size — the unwind is not
    attemptable and the caller must HALT.
    """
    acc = 0.0
    proceeds = 0.0
    worst = 0.0
    for price, size in _bids_descending(book):
        take = min(size, target_shares - acc)
        if take <= 0.0:
            break
        proceeds += price * take
        acc += take
        worst = price
        if acc + 1e-9 >= target_shares:
            return max(0.01, round(worst - tick, 4)), round(proceeds, 6)
    return None, 0.0


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


_FILL_SIZE_KEYS: tuple[str, ...] = (
    "size", "matched_amount", "amount", "filled_size", "making_amount",
)
_FILL_PRICE_KEYS: tuple[str, ...] = ("price", "fill_price", "avg_price")


def _first_float(d: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    """First parseable float among ``keys`` (tolerant of str/None/garbage)."""
    for k in keys:
        v = d.get(k)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    return None


def _fills_cost(fills: list[dict] | None) -> tuple[float, float]:
    """``(total_filled_size, total_cost_usdc)`` summed across broker fills.

    Robust to broker field-name aliases; skips malformed/degenerate rows (size <= 0
    or price outside (0, 1]) so a junk row can never corrupt the aggregate.
    """
    total_size = 0.0
    total_cost = 0.0
    for f in (fills or []):
        if not isinstance(f, dict):
            continue
        sz = _first_float(f, _FILL_SIZE_KEYS)
        px = _first_float(f, _FILL_PRICE_KEYS)
        if sz is None or px is None or sz <= 0.0 or not (0.0 < px <= 1.0):
            continue
        total_size += sz
        total_cost += sz * px
    return total_size, total_cost


async def _exact_fill_cost(
    client: ClobClientProtocol,
    broker_id: str | None,
    *,
    shares: float,
    estimate: float,
    leg: str,
    market_id: str,
) -> float:
    """Actual weighted USDC cost/proceeds of a FILLED order, from broker fills.

    Closes the scan-snapshot understatement (Codex P1 / M-2): a book that drifted
    between scan and fill makes the pre-submit ``estimate`` wrong, so the ledger +
    position must reflect what the broker actually filled. Falls back to ``estimate``
    when fills are unavailable, incomplete, or the query fails (paper/mock returns
    no fills, so behaviour there is unchanged) — accounting refinement must NEVER
    block or fail the persist.
    """
    if not broker_id:
        return estimate
    try:
        fills = await client.get_fills(broker_id)
    except Exception as exc:  # noqa: BLE001 — never block the persist on a fills hiccup
        log.warning("complete_set_exact_fill_query_failed",
                    leg=leg, market_id=market_id, error=str(exc))
        return estimate
    filled_size, cost = _fills_cost(fills)
    # Trust the fills only if they cover the order size (within a tiny epsilon) and
    # yield a positive cost; a short/empty set means the broker view is incomplete.
    if filled_size + 1e-6 < shares or cost <= 0.0:
        log.info("complete_set_exact_fill_incomplete", leg=leg, market_id=market_id,
                 filled_size=round(filled_size, 6), shares=round(shares, 6))
        return estimate
    if abs(cost - estimate) > 1e-9:
        log.info("complete_set_exact_fill", leg=leg, market_id=market_id,
                 estimate=round(estimate, 6), actual=round(cost, 6))
    return cost


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
    yes_key = f"{idempotency_key}:yes"
    no_key = f"{idempotency_key}:no"
    # NOTE: leg costs are NOT taken from the (scan-time) quote — they are recomputed
    # from the submit-time books below, so the persisted size_usdc / ledger debit
    # match what the broker actually fills against the CURRENT book.

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

    # FOK BUY plan from the CURRENT books: limit price (full-fill-or-kill) AND the
    # weighted fill cost. Recomputing the cost here (not reusing the scan-time
    # quote) keeps the persisted size_usdc / ledger debit aligned with what the
    # broker actually spends — a book that drifted up between scan and submit no
    # longer under-records exposure. None -> depth evaporated; abort (no exposure).
    yes_limit, yes_fill_cost = _fill_plan(yes_book, shares, yes_tick_f)
    no_limit, no_fill_cost = _fill_plan(no_book, shares, no_tick_f)
    if yes_limit is None or no_limit is None:
        raise LivePreSubmitError(
            "complete-set book depth insufficient at submit time "
            f"(yes={yes_limit} no={no_limit})"
        )
    yes_cost = Decimal(str(yes_fill_cost))
    no_cost = Decimal(str(no_fill_cost))
    # Arb invariant: the combined PAY price must stay strictly under the $1 payout,
    # else the set is not riskless. Never submit a non-arb complete set. (Limits are
    # >= the actual fill prices, so this is the conservative riskless guarantee.)
    if yes_limit + no_limit >= COMPLETE_SET_PAYOUT:
        raise LivePreSubmitError(
            f"complete-set limit sum {yes_limit + no_limit:.4f} >= "
            f"payout {COMPLETE_SET_PAYOUT} — not riskless"
        )
    # Budget ceiling: the risk gate approved spending up to ``quote.total_cost_usdc``
    # (it sized the quote within the per-position + live-capital caps). If the books
    # drifted UP between scan and submit, the recomputed cost can exceed that
    # approved budget — submitting anyway would overspend the user's approved risk
    # (e.g. a $95 approval repriced to $97). Reject pre-submit (no exposure): a
    # riskless arb we decline is free money skipped, never a loss. Lane 3C re-runs
    # the full gate; this is the primitive's own caller-agnostic floor.
    approved_budget = quote.total_cost_usdc
    actual_total = float(yes_cost + no_cost)
    if actual_total > approved_budget + 1e-6:
        raise LivePreSubmitError(
            f"complete-set submit-time cost {actual_total:.6f} exceeds gate-approved "
            f"budget {approved_budget:.6f} (book drifted up) — reject (no overspend)"
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
    except _PRE_SUBMIT_ERRORS as exc:
        # Auth/breaker-open: the order never reached the broker -> no order on-chain
        # -> safe abort (NO leg never sent, zero exposure).
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

    yes_fill = _fill_status(yes_res)
    if yes_fill == FILL_KILLED:
        # FOK killed: nothing filled, NO leg never sent -> zero exposure.
        await _mark_order(yes_order, "cancelled")
        await _mark_order(no_order, "cancelled")
        log.info("complete_set_live_yes_no_fill", market_id=market_id)
        return {"status": "no_fill", "mode": "live", "leg": "yes"}
    if yes_fill == FILL_AMBIGUOUS:
        # Accepted but NOT terminal (e.g. `delayed`) -> the YES order MAY still
        # match. Treat exactly like a transport-error ambiguity: do NOT send NO,
        # do NOT report a clean kill (which could hide a later fill) -> halt +
        # reconcile so the operator confirms the true YES state on Polymarket.
        await _mark_order(yes_order, "unknown",
                          error=f"non-terminal status: {yes_res.get('status')}")
        await _mark_order(no_order, "cancelled")
        await _halt_and_alert(
            reason="complete_set_yes_ambiguous_status",
            detail=(f"YES leg status AMBIGUOUS ({yes_res.get('status')!r}) "
                    f"market=<code>{market_id}</code> order=<code>{yes_order}</code> "
                    f"— may still match; reconcile on Polymarket."),
        )
        raise LivePostSubmitError(
            f"complete-set YES non-terminal status "
            f"({yes_res.get('status')!r}, order={yes_order})"
        )

    yes_broker_id = _extract_order_id(yes_res)

    # --- Leg 2: NO FOK -------------------------------------------------------
    try:
        no_res = await client.post_order(
            token_id=quote.no_token_id, side="BUY", price=no_limit, size=shares,
            order_type="FOK", tick_size=no_tick, neg_risk=no_neg,
        )
    except _PRE_SUBMIT_ERRORS as exc:
        # Auth/breaker-open: NO never reached the broker; YES is filled (naked) ->
        # unwind the YES leg. (If the breaker is open the unwind SELL will also fail
        # pre-submit and route to _persist_naked_halt — see _unwind_naked_leg.)
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
            entry_price=round(yes_fill_cost / shares, 6),
            market_question=market_question, active_preset=active_preset,
            naked_meta={**meta, "naked_leg": "yes", "no_leg_ambiguous": True},
            reason=f"no_ambiguous_yes_filled:{exc}",
        )
        raise LivePostSubmitError(
            f"complete-set NO ambiguous after YES fill (yes={yes_order}, "
            f"tracked as naked): {exc}"
        ) from exc

    no_fill = _fill_status(no_res)
    if no_fill == FILL_KILLED:
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
    if no_fill == FILL_AMBIGUOUS:
        # NO accepted but NOT terminal (e.g. `delayed`) AND YES filled. Same posture
        # as the NO transport-error ambiguity: do NOT auto-unwind (NO may still
        # match -> over-sell risk); persist the CONFIRMED YES leg as tracked +
        # force-exitable, halt, and raise for operator reconciliation of NO.
        await _mark_order(no_order, "unknown",
                          error=f"non-terminal status: {no_res.get('status')}")
        await _persist_naked_halt(
            pool=pool, user_id=user_id, market_id=market_id, naked_order=yes_order,
            naked_side="yes", naked_cost=yes_cost,
            entry_price=round(yes_fill_cost / shares, 6),
            market_question=market_question, active_preset=active_preset,
            naked_meta={**meta, "naked_leg": "yes", "no_leg_ambiguous": True},
            reason=f"no_ambiguous_status_yes_filled:{no_res.get('status')}",
        )
        raise LivePostSubmitError(
            f"complete-set NO non-terminal status after YES fill "
            f"({no_res.get('status')!r}, yes={yes_order}, tracked as naked)"
        )

    no_broker_id = _extract_order_id(no_res)

    # --- Both legs filled: persist the linked pair atomically ----------------
    # Exact-fill reconciliation (Lane 3C-2): book the broker's ACTUAL weighted fill
    # cost (get_fills) rather than the pre-submit book estimate, so a book that
    # drifted between scan and fill cannot understate live exposure (Codex P1).
    # Computed only AFTER both legs are terminal — never between legs — so the
    # latency-sensitive YES->NO window is unaffected. Falls back to the estimate
    # when fills are unavailable.
    yes_actual = await _exact_fill_cost(
        client, yes_broker_id, shares=shares, estimate=yes_fill_cost,
        leg="yes", market_id=market_id)
    no_actual = await _exact_fill_cost(
        client, no_broker_id, shares=shares, estimate=no_fill_cost,
        leg="no", market_id=market_id)
    yes_cost = Decimal(str(yes_actual))
    no_cost = Decimal(str(no_actual))
    # Per-share entry prices from the ACTUAL fill cost, so entry_price * shares ==
    # the persisted size_usdc == what was really spent.
    yes_price = round(yes_actual / shares, 6)
    no_price = round(no_actual / shares, 6)
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
    # Exact-fill (Lane 3C-2 / Codex P1): the naked leg's BUY cost was the pre-submit
    # book estimate — recompute it from the broker's actual fills so realised P&L and
    # the force-exitable position size reflect what was really spent. Falls back to
    # the estimate when fills are unavailable. The NO leg has already resolved here,
    # so this query adds no latency to the YES->NO window.
    naked_cost = Decimal(str(await _exact_fill_cost(
        client, naked_broker_id, shares=shares, estimate=float(naked_cost),
        leg=f"{naked_side}-naked", market_id=market_id)))
    token_id = quote.yes_token_id if naked_side == "yes" else quote.no_token_id
    entry_price = round(float(naked_cost) / shares, 6) if shares > 0 else naked_limit
    naked_meta = {**meta, "naked_leg": naked_side, "unwind": True}

    sell_limit, sell_proceeds = _sell_plan(naked_book, shares, tick_f)
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
    except _PRE_SUBMIT_ERRORS as exc:
        # Auth/breaker-open: the SELL never reached the broker -> the leg is
        # DEFINITELY still naked -> persist (force-exitable) + halt. This is the
        # branch a breaker-OPEN unwind lands in (ClobCircuitOpenError, no call).
        log.error("complete_set_unwind_presubmit_failed", market_id=market_id,
                  error=str(exc))
        return await _persist_naked_halt(
            pool=pool, user_id=user_id, market_id=market_id, naked_order=naked_order,
            naked_side=naked_side, naked_cost=naked_cost, entry_price=entry_price,
            market_question=market_question, active_preset=active_preset,
            naked_meta=naked_meta, reason=f"unwind_presubmit_error:{exc}",
        )
    except Exception as exc:  # noqa: BLE001
        # AMBIGUOUS post-submit: a timeout / transport error after POST /order means
        # the SELL MAY already be accepted on-chain (account flat) — we cannot assert
        # the leg is still naked. Persisting an open, force-exitable position here
        # would let the exit watcher re-sell a position the broker may already have
        # flattened (a double-close / over-sell). So mark the order 'unknown', HALT,
        # page, and raise LivePostSubmitError for operator reconciliation — never
        # auto-persist a guessed flat/naked state.
        log.error("complete_set_unwind_ambiguous", market_id=market_id,
                  error=str(exc))
        await _mark_order(naked_order, "unknown", error=f"unwind ambiguous: {exc}")
        await _halt_and_alert(
            reason="complete_set_unwind_ambiguous",
            detail=(f"Naked {naked_side} leg unwind SELL AMBIGUOUS "
                    f"market=<code>{market_id}</code> order=<code>{naked_order}</code> "
                    f"— account may be FLAT or NAKED; reconcile on Polymarket before "
                    f"resuming (do not assume). err: {exc}"),
        )
        raise LivePostSubmitError(
            f"complete-set unwind ambiguous ({market_id}, {naked_side}): {exc}"
        ) from exc

    sell_fill = _fill_status(sell_res)
    if sell_fill == FILL_AMBIGUOUS:
        # SELL accepted but NOT terminal (e.g. `delayed`) -> it may still match and
        # flatten the leg. We cannot assert it is still naked, so (as with the
        # transport-error ambiguity above) do NOT persist a re-sellable position —
        # mark unknown, halt, and raise for operator reconciliation.
        log.error("complete_set_unwind_ambiguous_status", market_id=market_id,
                  status=sell_res.get("status"))
        await _mark_order(naked_order, "unknown",
                          error=f"unwind non-terminal status: {sell_res.get('status')}")
        await _halt_and_alert(
            reason="complete_set_unwind_ambiguous",
            detail=(f"Naked {naked_side} leg unwind SELL non-terminal "
                    f"({sell_res.get('status')!r}) market=<code>{market_id}</code> "
                    f"order=<code>{naked_order}</code> — account may be FLAT or NAKED; "
                    f"reconcile on Polymarket before resuming."),
        )
        raise LivePostSubmitError(
            f"complete-set unwind non-terminal status "
            f"({sell_res.get('status')!r}, {market_id}, {naked_side})"
        )
    if sell_fill == FILL_KILLED:
        return await _persist_naked_halt(
            pool=pool, user_id=user_id, market_id=market_id, naked_order=naked_order,
            naked_side=naked_side, naked_cost=naked_cost, entry_price=entry_price,
            market_question=market_question, active_preset=active_preset,
            naked_meta=naked_meta, reason="unwind_fok_killed",
        )

    # Unwind filled -> flat. Credit the WEIGHTED bid proceeds (the FOK fills at the
    # limit or better, so the weighted value over the consumed bids is what the SELL
    # actually returns; crediting the bare limit would permanently understate the
    # wallet on every unwind).
    unwind_broker_id = _extract_order_id(sell_res)
    # Exact-fill (Lane 3C-2 / M-2): credit the broker's ACTUAL weighted SELL proceeds
    # rather than the pre-submit bid-walk estimate; fall back to the estimate when
    # fills are unavailable.
    proceeds = Decimal(str(await _exact_fill_cost(
        client, unwind_broker_id, shares=shares, estimate=float(sell_proceeds),
        leg=f"{naked_side}-unwind", market_id=market_id)))
    realised = proceeds - naked_cost
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
    persisted = False
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
        persisted = True
    except Exception:  # noqa: BLE001 — never let persistence failure swallow the halt
        log.exception("complete_set_naked_persist_failed", market_id=market_id,
                      naked_side=naked_side)
    try:
        await audit.write(
            actor_role="bot", action="live_complete_set_naked_halt", user_id=user_id,
            payload={"market_id": market_id, "naked_side": naked_side,
                     "reason": reason, "position_id": str(position_id),
                     "persisted": persisted, "size_usdc": str(naked_cost)},
        )
    except Exception:  # noqa: BLE001
        log.exception("complete_set_naked_halt_audit_failed", market_id=market_id)
    # If persistence FAILED, the live exposure is NOT tracked in positions/ledger.
    # The alert + return MUST say so loudly — never report a clean "persisted"
    # halt the operator would trust while an untracked live leg sits on-chain.
    if persisted:
        detail = (f"market=<code>{market_id}</code> side={naked_side} "
                  f"cost=${naked_cost} reason={reason}\n"
                  f"Naked leg persisted as <code>{position_id}</code> "
                  f"(force-exitable). Reconcile + resume manually.")
        status = "naked_halt"
    else:
        detail = (f"market=<code>{market_id}</code> side={naked_side} "
                  f"cost=${naked_cost} reason={reason}\n"
                  f"⚠️ PERSIST FAILED — naked leg is NOT tracked in positions/ledger "
                  f"(order=<code>{naked_order}</code>). UNTRACKED live exposure — "
                  f"manual DB repair required before resuming.")
        status = "naked_halt_persist_failed"
    await _halt_and_alert(reason="complete_set_naked_leg", detail=detail)
    return {"status": status, "mode": "live", "naked_leg": naked_side,
            "position_id": position_id, "reason": reason, "persisted": persisted}


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
    """Engage the operator kill switch (HARD) and page the operator.

    A naked leg we could not unwind is a real, unhedged on-chain exposure. The kill
    switch is the ONLY mechanism the risk gate reads to stop opening new trades, so
    a failed activation must NOT be swallowed — otherwise the bot keeps trading
    after a confirmed naked leg while believing it halted. We retry the activation,
    and if it still fails we page the operator with an URGENT "halt did NOT engage"
    alert and raise ``LivePostSubmitError`` so the caller propagates a hard failure
    rather than returning/continuing as if halted. The operator page is always
    attempted (best-effort) before we raise.
    """
    halted = False
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            await kill_switch.set_active(action="pause", reason=reason)
            halted = True
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            log.exception("complete_set_halt_killswitch_attempt_failed",
                          reason=reason, attempt=attempt)
    header = (
        "🛑 <b>COMPLETE-SET NAKED LEG — TRADING HALTED</b>" if halted else
        "🚨🚨 <b>HALT DID NOT ENGAGE — STOP THE BOT MANUALLY</b> 🚨🚨"
    )
    try:
        await notifications.notify_operator(f"{header}\n{detail}")
    except Exception:  # noqa: BLE001
        log.exception("complete_set_naked_halt_notify_failed")
    if not halted:
        # Trading is NOT actually halted (gate reads kill_switch_active from the DB).
        # Surface as a hard post-submit failure so the caller never reports a clean
        # halt while the bot can keep opening trades against a naked leg.
        raise LivePostSubmitError(
            f"kill switch activation FAILED ({reason}) — trading NOT halted: {last_exc}"
        )


__all__ = [
    "book_complete_set_paper",
    "book_complete_set_live",
    "COMPLETE_SET_STRATEGY",
    "COMPLETE_SET_NAKED_STRATEGY",
]
