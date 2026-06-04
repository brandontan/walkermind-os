"""WARP-74 — generalized LIVE reconciler (restart-recovery + crash-safe close).

The execution layer already has TWO reconcilers, but a gap sits between them:

  * ``OrderLifecycleManager`` (``lifecycle.py``) polls directional live orders in
    ``('submitted','pending','partial_filled')`` against the broker.
  * ``reconcile_complete_set_orders`` (``complete_set_exec.py``) owns
    ``'complete_set_arb%'`` order rows.

NEITHER touches the two states a crash actually leaves behind on the live path:

  P0 #1 — a directional ``'unknown'`` order. ``live.execute`` marks an ambiguous
          post-submit ``'unknown'`` WITH NO broker id (the submit raised before
          we received the order id). The lifecycle poller's ``STATUS_OPEN`` set
          excludes ``'unknown'``, so the row is never polled — it orphans.

  P0 #2 — a live ``positions.status='closing'`` row. ``live.close_position``
          atomically claims the position to ``'closing'``, submits a GTC SELL,
          then finalizes to ``'closed'``. A crash BETWEEN the SELL and the
          finalize strands the row in ``'closing'`` forever; the close SELL is
          not tracked in the ``orders`` table, so nothing recovers it.

This module closes both gaps for the directional strategies (``late_entry_v3`` /
``signal_following`` / ``copy_trade``) — NEVER complete-set, which keeps its own
set-aware reconciler. Both sweeps:

  * no-op in paper / non-live (``USE_REAL_CLOB`` is the gate),
  * never raise (safe on an APScheduler interval; per-item errors are isolated),
  * NEVER assume — anything unverifiable pages the operator (and, for confirmed
    untracked exposure, engages the kill switch) instead of silently guessing.

Recovery is intentionally CONSERVATIVE: it adopts a uniquely-matched resting
order back into the tracked lifecycle, finalizes/rolls-back a stranded close on
confirmed broker truth, and pages on every ambiguity — it never fabricates a
position from a fuzzy size/price match.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable, Optional

import structlog

from ... import audit, notifications
from ...config import get_settings
from ...database import get_pool
from ...integrations.clob import (
    ClobAuthError,
    ClobClientProtocol,
    ClobConfigError,
    get_clob_client,
)
from ...wallet import ledger
from ..ops import kill_switch
from .complete_set_exec import (
    FILL_FILLED,
    FILL_KILLED,
    _fill_status,
    _fills_cost,
)

log = structlog.get_logger(__name__)

# Directional strategies this reconciler owns. Complete-set is excluded on
# purpose — its legs carry refund/naked-leg logic handled by its own reconciler.
_DIRECTIONAL_PREFIXES = ("late_entry_v3", "signal_following", "copy_trade")

# Broker order dicts spell the outcome token under several historical key names.
_TOKEN_KEYS = ("asset_id", "token_id", "tokenID", "asset", "tokenId")
_BROKER_ID_KEYS = ("orderID", "order_id", "id", "orderId")
_SIZE_KEYS = ("original_size", "originalSize", "size", "size_matched", "sizeMatched")

# Adoption guard tolerances. A lone untracked resting order on the token is only
# OUR orphan if its price and size plausibly match the 'unknown' order — otherwise
# it may be an unrelated user/manual order on the same token. The resting price
# can sit a couple of ticks off our stored signal price (live.execute crosses the
# spread with an aggressive +1-tick limit), so the price band is deliberately
# loose; the share count is the strong discriminator.
_ADOPT_PRICE_TOL = 0.03     # ~3 ticks absolute (outcome-token price ∈ (0,1))
_ADOPT_SIZE_TOL = 0.05      # 5% share-count tolerance


def _order_token(o: dict[str, Any]) -> str:
    for k in _TOKEN_KEYS:
        v = o.get(k)
        if v:
            return str(v)
    return ""


def _order_broker_id(o: dict[str, Any]) -> str:
    for k in _BROKER_ID_KEYS:
        v = o.get(k)
        if v:
            return str(v)
    return ""


def _order_size_price(o: dict[str, Any]) -> tuple[float, float]:
    size = 0.0
    for k in _SIZE_KEYS:
        v = o.get(k)
        if v:
            try:
                size = float(v)
                break
            except (TypeError, ValueError):
                continue
    try:
        price = float(o.get("price") or 0.0)
    except (TypeError, ValueError):
        price = 0.0
    return size, price


def _order_matches(b_order: dict[str, Any], order: dict) -> bool:
    """True only if a broker resting order plausibly IS the 'unknown' order.

    Price is the unit-unambiguous, mandatory discriminator (outcome-token price in
    (0,1)). Size is best-effort: brokers report shares either raw OR in 1e6
    fixed-math, so a match under EITHER interpretation counts; an unreadable size
    falls back to the price + exact-token + lone-untracked signal. Getting the
    units wrong can only REJECT (→ page), never wrongly adopt.
    """
    try:
        exp_price = float(order.get("price") or 0.0)
        exp_size = float(order.get("size_usdc") or 0.0) / max(exp_price, 1e-4)
    except (TypeError, ValueError):
        return False
    if exp_price <= 0.0 or exp_size <= 0.0:
        return False
    b_size, b_price = _order_size_price(b_order)
    if not (b_price > 0.0 and abs(b_price - exp_price) <= _ADOPT_PRICE_TOL):
        return False
    if b_size <= 0.0:
        return True  # price + token + lone-untracked is already specific
    for scaled in (b_size, b_size / 1_000_000.0):
        if abs(scaled - exp_size) / max(exp_size, 1e-6) <= _ADOPT_SIZE_TOL:
            return True
    return False


async def _page_operator(text: str) -> None:
    """Best-effort operator page — never raises over a scheduler sweep."""
    try:
        await notifications.notify_operator(text)
    except Exception as exc:  # noqa: BLE001
        log.error("live_reconcile_page_failed", err=str(exc))


async def _halt_and_page(*, reason: str, detail: str) -> None:
    """Engage the kill switch (best-effort) + page on CONFIRMED untracked
    exposure. Unlike the complete-set halt, this never raises — a reconcile
    sweep must keep processing the remaining rows. A failed activation is
    surfaced in the operator page so the bot is never believed-halted silently.
    """
    halted = False
    try:
        await kill_switch.set_active(action="pause", reason=reason)
        halted = True
    except Exception as exc:  # noqa: BLE001
        log.exception("live_reconcile_halt_failed", reason=reason, err=str(exc))
    header = (
        "🛑 <b>LIVE RECONCILE — UNTRACKED EXPOSURE, TRADING HALTED</b>" if halted
        else "🚨🚨 <b>HALT DID NOT ENGAGE — STOP THE BOT MANUALLY</b> 🚨🚨"
    )
    await _page_operator(f"{header}\n{detail}")


def _resolve_client(
    clob_factory: Optional[Callable[[Any], ClobClientProtocol]], s: Any,
) -> Optional[ClobClientProtocol]:
    factory = clob_factory or get_clob_client
    try:
        return factory(s)
    except (ClobConfigError, ClobAuthError) as exc:
        log.error("live_reconcile_client_unavailable", err=str(exc))
        return None


# ---------------------------------------------------------------------------
# P0 #1 — directional 'unknown' order reconciler
# ---------------------------------------------------------------------------


async def _token_for(pool, market_id: str, side: str) -> str:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT yes_token_id, no_token_id FROM markets WHERE id=$1", market_id,
        )
    if not row:
        return ""
    return str((row["yes_token_id"] if str(side).lower() in ("yes", "buy")
                else row["no_token_id"]) or "")


async def _tracked_broker_ids(pool) -> set[str]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT polymarket_order_id FROM orders "
            "WHERE polymarket_order_id IS NOT NULL AND polymarket_order_id <> ''",
        )
    return {str(r["polymarket_order_id"]) for r in rows}


async def _mark_order_paged(order_id: Any, note: str) -> None:
    """Stamp an unverifiable 'unknown' order so it is not re-paged every sweep."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE orders SET error_msg=$2 WHERE id=$1",
                order_id, f"[reconcile_paged] {note}"[:500],
            )
    except Exception as exc:  # noqa: BLE001
        log.error("live_reconcile_mark_paged_failed", err=str(exc))


async def _mark_position_paged(pos_id: Any, note: str) -> None:
    """Stamp an unresolvable stranded 'closing' position so the periodic sweep
    stops re-paging it every cycle (alert-fatigue guard; mirrors orders.error_msg).
    The startup sweep ignores this stamp so a restart still re-surfaces it once.
    """
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE positions SET error_msg=$2 WHERE id=$1",
                pos_id, f"[reconcile_paged] {note}"[:500],
            )
    except Exception as exc:  # noqa: BLE001
        log.error("live_reconcile_mark_position_paged_failed", err=str(exc))


async def _adopt_order(order_id: Any, broker_id: str) -> None:
    """Hand a recovered resting order back to the lifecycle poller: re-link the
    broker id and flip 'unknown' -> 'pending' so ``OrderLifecycleManager`` resumes
    polling it to a clean terminal state. No capital is moved here.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE orders SET status='pending', polymarket_order_id=$2, "
            "error_msg=NULL WHERE id=$1 AND status='unknown'",
            order_id, broker_id,
        )


async def _reconcile_one_unknown(
    order: dict, *, client: ClobClientProtocol, pool, tracked_ids: set[str],
) -> str:
    order_id = order["id"]
    market_id = order["market_id"]
    side = order["side"]

    token = await _token_for(pool, market_id, side)
    if not token:
        await _page_operator(
            f"⚠️ <b>LIVE RECONCILE</b>\nUnknown order <code>{order_id}</code> "
            f"market=<code>{market_id}</code> — token unresolved; reconcile manually."
        )
        await _mark_order_paged(order_id, "token_unresolved")
        return "paged"

    try:
        open_orders = await client.get_open_orders(market_id)
    except Exception as exc:  # noqa: BLE001 — cannot verify -> page, never assume
        log.warning("live_reconcile_open_orders_failed",
                    order_id=str(order_id), err=str(exc))
        await _page_operator(
            f"⚠️ <b>LIVE RECONCILE</b>\nUnknown order <code>{order_id}</code> "
            f"market=<code>{market_id}</code> — broker open-orders query FAILED; "
            f"reconcile manually before resuming."
        )
        return "error"

    on_token = [o for o in (open_orders or []) if _order_token(o) == token]
    untracked = [o for o in on_token
                 if _order_broker_id(o) and _order_broker_id(o) not in tracked_ids]

    if len(untracked) == 1:
        b_order = untracked[0]
        if not _order_matches(b_order, order):
            # A lone untracked resting order on the token whose size/price does NOT
            # match ours — likely an unrelated user/manual order, not our orphan.
            # Never adopt it; page for a manual reconcile.
            await _page_operator(
                f"⚠️ <b>LIVE RECONCILE — size/price mismatch</b>\n"
                f"Unknown order <code>{order_id}</code> market=<code>{market_id}</code>: "
                f"the lone untracked resting order on the token does not match our "
                f"size/price — NOT adopting. Reconcile manually."
            )
            await _mark_order_paged(order_id, "size_price_mismatch")
            return "paged"
        broker_id = _order_broker_id(b_order)
        await _adopt_order(order_id, broker_id)
        await audit.write(actor_role="bot", action="live_reconcile_adopted",
                          user_id=order.get("user_id"),
                          payload={"order_id": str(order_id),
                                   "market_id": market_id,
                                   "polymarket_order_id": broker_id})
        log.info("live_reconcile_adopted", order_id=str(order_id), broker_id=broker_id)
        return "adopted"

    if len(untracked) > 1:
        # Multiple untracked resting orders on our token — genuinely ambiguous
        # untracked exposure. Halt + page rather than adopt the wrong one.
        await _halt_and_page(
            reason="live_reconcile_ambiguous_resting",
            detail=(f"Unknown order <code>{order_id}</code> market=<code>{market_id}</code> "
                    f"token=<code>{token}</code> — {len(untracked)} untracked resting "
                    f"orders match; manual reconcile required."),
        )
        await _mark_order_paged(order_id, "ambiguous_resting")
        return "halted"

    # No untracked resting order on the token. The ambiguous submit either never
    # landed (safe) or filled instantly (untracked exposure). We CANNOT auto-cancel
    # without risking hiding a real fill, so page once for a manual reconcile and
    # stamp the row so it stops re-paging every sweep.
    await _page_operator(
        f"⚠️ <b>LIVE RECONCILE — verify on exchange</b>\n"
        f"Unknown order <code>{order_id}</code> market=<code>{market_id}</code> "
        f"side=<code>{side}</code> size=<code>${order.get('size_usdc')}</code>\n"
        f"No resting order on the token. Confirm it never filled (or reconcile the "
        f"fill) on Polymarket, then clear the row."
    )
    await _mark_order_paged(order_id, "no_resting_order")
    return "paged"


async def reconcile_live_orders(
    *, pool=None, clob_factory=None, settings: Any = None,
) -> dict:
    """Reconcile directional live orders orphaned in ``'unknown'`` by a crash.

    Scans ``mode='live'`` directional orders still ``'unknown'`` past the stale
    threshold with no linked position, and resolves each against broker truth:
    a uniquely-matched untracked resting order is adopted back into the lifecycle
    poller; multiple matches halt + page; an unverifiable order pages for manual
    reconcile. Paper / non-live is a no-op. Never raises.
    """
    s = settings or get_settings()
    if not bool(getattr(s, "USE_REAL_CLOB", False)):
        return {"scanned": 0, "skipped_paper": True}
    if not bool(getattr(s, "LIVE_RECONCILE_ENABLED", True)):
        return {"scanned": 0, "skipped_disabled": True}
    pool = pool or get_pool()
    stale_sec = max(0, int(getattr(s, "LIVE_RECONCILE_STALE_SEC", 300) or 0))
    out = {"scanned": 0, "adopted": 0, "paged": 0, "halted": 0, "error": 0}

    prefixes = "|".join(_DIRECTIONAL_PREFIXES)
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT o.id, o.user_id, o.market_id, o.side, o.size_usdc, o.price,
                       o.polymarket_order_id, o.status, o.strategy_type
                  FROM orders o
                  LEFT JOIN positions p ON p.order_id = o.id
                 WHERE o.mode = 'live'
                   AND o.status = 'unknown'
                   AND o.strategy_type ~ ($2 || '')
                   AND p.id IS NULL
                   AND (o.error_msg IS NULL OR o.error_msg NOT LIKE '%reconcile_paged%')
                   AND o.created_at < NOW() - ($1 || ' seconds')::interval
                """,
                str(stale_sec), f"^({prefixes})",
            )
    except Exception as exc:  # noqa: BLE001 — scheduler job must never raise
        log.exception("live_reconcile_scan_failed", err=str(exc))
        return {**out, "error": 1}
    if not rows:
        return out

    client = _resolve_client(clob_factory, s)
    if client is None:
        # No client -> cannot verify any of these -> page once, leave untouched.
        await _page_operator(
            f"⚠️ <b>LIVE RECONCILE</b>\n{len(rows)} unknown live order(s) "
            f"awaiting reconcile but CLOB client unavailable."
        )
        return {**out, "scanned": len(rows), "error": len(rows)}

    try:
        tracked_ids = await _tracked_broker_ids(pool)
        for row in rows:
            out["scanned"] += 1
            try:
                resolution = await _reconcile_one_unknown(
                    dict(row), client=client, pool=pool, tracked_ids=tracked_ids)
                out[resolution] = out.get(resolution, 0) + 1
            except Exception as exc:  # noqa: BLE001 — isolate one bad order
                out["error"] += 1
                log.exception("live_reconcile_order_failed",
                              order_id=str(row["id"]), err=str(exc))
    finally:
        try:
            await client.aclose()
        except Exception:  # noqa: BLE001
            log.warning("live_reconcile_client_close_failed")
    log.info("live_reconcile_sweep", **out)
    return out


# ---------------------------------------------------------------------------
# P0 #2 — stranded 'closing' position reconciler
# ---------------------------------------------------------------------------


async def _finalize_closed(position: dict, *, exit_price: float,
                           proceeds: Decimal, pnl: Decimal) -> bool:
    """Race-safe finalize of a stranded close to 'closed' + ledger credit.

    Returns True if THIS call won the 'closing'->'closed' transition.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            updated = await conn.fetchval(
                "UPDATE positions SET status='closed', exit_reason='reconciled_close', "
                "current_price=$2, pnl_usdc=$3, closed_at=NOW() "
                "WHERE id=$1 AND user_id=$4 AND status='closing' RETURNING id",
                position["id"], exit_price, pnl, position["user_id"],
            )
            if updated is None:
                return False
            await ledger.credit_in_conn(
                conn, position["user_id"], proceeds, ledger.T_TRADE_CLOSE,
                ref_id=position["id"], note="live close reconciled",
            )
    return True


async def _rollback_closing(position: dict) -> None:
    """Return a stranded 'closing' row to 'open' when the SELL definitively did
    NOT execute — the exit watcher then re-attempts the close cleanly.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE positions SET status='open', closing_at=NULL, close_order_id=NULL "
            "WHERE id=$1 AND user_id=$2 AND status='closing'",
            position["id"], position["user_id"],
        )


async def _reconcile_one_closing(
    position: dict, *, client: ClobClientProtocol,
) -> str:
    pos_id = position["id"]
    close_order_id = str(position.get("close_order_id") or "").strip()

    if not close_order_id:
        # Crash before the close SELL id was persisted (or a pre-migration row).
        # We cannot know whether the SELL filled -> never assume -> page + leave.
        await _page_operator(
            f"⚠️ <b>LIVE RECONCILE — stranded close</b>\n"
            f"Position <code>{pos_id}</code> stuck in 'closing' with no close order "
            f"id. Verify on Polymarket whether the SELL filled, then reconcile."
        )
        await _mark_position_paged(pos_id, "no_close_order_id")
        return "paged_no_id"

    try:
        broker = await client.get_order(close_order_id)
        fills = await client.get_fills(close_order_id)
    except Exception as exc:  # noqa: BLE001 — cannot verify -> page, never assume
        log.warning("live_reconcile_closing_query_failed",
                    position_id=str(pos_id), err=str(exc))
        await _page_operator(
            f"⚠️ <b>LIVE RECONCILE — stranded close</b>\n"
            f"Position <code>{pos_id}</code> close order <code>{close_order_id}</code> "
            f"— broker query FAILED; reconcile manually before resuming."
        )
        return "error"

    st = _fill_status(broker)
    filled_size, fill_cost = _fills_cost(fills)
    size_usdc = Decimal(str(position["size_usdc"]))

    # Only act on a TERMINAL broker state. A non-terminal close — EVEN one that is
    # partially filled in flight — must NOT be finalized: booking a full close
    # while shares are still resting/matching on-chain would strand the unsold
    # remainder and mis-credit the ledger. Leave 'closing'; the next sweep
    # re-checks once the order settles.
    if st not in (FILL_FILLED, FILL_KILLED):
        await _page_operator(
            f"⚠️ <b>LIVE RECONCILE — close in flight</b>\n"
            f"Position <code>{pos_id}</code> close order <code>{close_order_id}</code> "
            f"still non-terminal ({broker.get('status')!r}); monitoring."
        )
        return "pending"

    if st == FILL_FILLED:
        # SELL fully executed. Proceeds = USDC received from selling the shares.
        proceeds = (Decimal(str(fill_cost)) if fill_cost > 0.0
                    else size_usdc * _ret_factor(position))
        exit_price = (round(fill_cost / filled_size, 6) if filled_size > 0.0
                      else float(position.get("current_price")
                                 or position["entry_price"]))
        pnl = proceeds - size_usdc
        won = await _finalize_closed(position, exit_price=exit_price,
                                     proceeds=proceeds, pnl=pnl)
        if won:
            await audit.write(actor_role="bot", action="live_reconcile_closed",
                              user_id=position["user_id"],
                              payload={"position_id": str(pos_id),
                                       "close_order_id": close_order_id,
                                       "exit_price": exit_price,
                                       "pnl_usdc": str(pnl)})
            log.info("live_reconcile_closed", position_id=str(pos_id), pnl=str(pnl))
        return "closed"

    # st == FILL_KILLED from here.
    if filled_size > 0.0:
        # Terminal KILLED but PARTIALLY filled — some shares sold, the rest
        # cancelled. Finalizing the whole position would strand the unsold
        # remainder untracked, so never auto-resolve: page for a manual reconcile.
        await _page_operator(
            f"⚠️ <b>LIVE RECONCILE — PARTIAL CLOSE KILLED</b>\n"
            f"Position <code>{pos_id}</code> close order <code>{close_order_id}</code> "
            f"KILLED after a partial fill of {filled_size} shares — reconcile "
            f"manually to avoid untracked on-chain exposure."
        )
        await _mark_position_paged(pos_id, f"partial_close_killed_filled_{filled_size}")
        return "paged_partial_close"

    # Terminal KILLED with ZERO fills -> the SELL definitively did NOT execute ->
    # safe to re-open for a clean exit-watcher retry.
    await _rollback_closing(position)
    await audit.write(actor_role="bot", action="live_reconcile_close_rolled_back",
                      user_id=position["user_id"],
                      payload={"position_id": str(pos_id),
                               "close_order_id": close_order_id})
    log.info("live_reconcile_close_rolled_back", position_id=str(pos_id))
    return "rolled_back"


def _ret_factor(position: dict) -> Decimal:
    """Fallback proceeds multiplier (current/entry) when broker reports no fills
    but a fill is asserted — keeps the credit finite and side-own framed.
    """
    entry = float(position["entry_price"]) or 1e-6
    cur = float(position.get("current_price") or entry)
    return Decimal(str(max(0.0, cur / max(entry, 1e-6))))


async def reconcile_closing_positions(
    *, pool=None, clob_factory=None, settings: Any = None, startup: bool = False,
) -> dict:
    """Recover live positions stranded in ``'closing'`` by a crash mid-close.

    On ``startup=True`` EVERY live 'closing' row is reconciled (a fresh process
    has nothing legitimately mid-close); on the periodic path only rows whose
    ``closing_at`` is older than ``LIVE_CLOSING_STALE_SEC`` (or NULL — a
    pre-migration row). Each is resolved against broker truth via the persisted
    ``close_order_id``: a confirmed fill finalizes to 'closed' + credits the
    ledger; a confirmed non-fill rolls back to 'open' for a clean retry; anything
    unverifiable pages the operator and is left untouched. Paper is a no-op.
    """
    s = settings or get_settings()
    if not bool(getattr(s, "USE_REAL_CLOB", False)):
        return {"scanned": 0, "skipped_paper": True}
    if not bool(getattr(s, "LIVE_RECONCILE_ENABLED", True)):
        return {"scanned": 0, "skipped_disabled": True}
    pool = pool or get_pool()
    stale_sec = max(0, int(getattr(s, "LIVE_CLOSING_STALE_SEC", 120) or 0))
    out = {"scanned": 0, "closed": 0, "rolled_back": 0, "pending": 0,
           "paged_partial_close": 0, "paged_no_id": 0, "error": 0}

    try:
        async with pool.acquire() as conn:
            if startup:
                rows = await conn.fetch(
                    "SELECT id, user_id, market_id, side, size_usdc, entry_price, "
                    "current_price, close_order_id, closing_at "
                    "FROM positions WHERE mode='live' AND status='closing'",
                )
            else:
                # Periodic sweep excludes already-paged unresolvable rows so the
                # operator is paged once, not every cycle. The startup sweep above
                # intentionally includes them (re-surface once per restart).
                rows = await conn.fetch(
                    "SELECT id, user_id, market_id, side, size_usdc, entry_price, "
                    "current_price, close_order_id, closing_at "
                    "FROM positions WHERE mode='live' AND status='closing' "
                    "AND (error_msg IS NULL OR error_msg NOT LIKE '%reconcile_paged%') "
                    "AND (closing_at IS NULL "
                    "     OR closing_at < NOW() - ($1 || ' seconds')::interval)",
                    str(stale_sec),
                )
    except Exception as exc:  # noqa: BLE001 — scheduler job must never raise
        log.exception("live_reconcile_closing_scan_failed", err=str(exc))
        return {**out, "error": 1}
    if not rows:
        return out

    client = _resolve_client(clob_factory, s)
    if client is None:
        await _page_operator(
            f"⚠️ <b>LIVE RECONCILE</b>\n{len(rows)} live position(s) stranded in "
            f"'closing' but CLOB client unavailable for reconcile."
        )
        return {**out, "scanned": len(rows), "error": len(rows)}

    try:
        for row in rows:
            out["scanned"] += 1
            try:
                resolution = await _reconcile_one_closing(dict(row), client=client)
                out[resolution] = out.get(resolution, 0) + 1
            except Exception as exc:  # noqa: BLE001 — isolate one bad position
                out["error"] += 1
                log.exception("live_reconcile_closing_position_failed",
                              position_id=str(row["id"]), err=str(exc))
    finally:
        try:
            await client.aclose()
        except Exception:  # noqa: BLE001
            log.warning("live_reconcile_closing_client_close_failed")
    log.info("live_reconcile_closing_sweep", startup=startup, **out)
    return out


__all__ = ["reconcile_live_orders", "reconcile_closing_positions"]
