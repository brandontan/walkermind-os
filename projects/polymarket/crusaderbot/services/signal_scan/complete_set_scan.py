"""Complete-set arbitrage — scan + PAPER/LIVE booking wiring (Lane 3C-1).

This is the runtime activation of the complete-set-arb epic: it joins the Lane 1
detector (``fillable_complete_set``) to the booking primitives
(``book_complete_set_paper`` / ``book_complete_set_live``) through the risk gate,
for one enrolled user per call. ``services.signal_scan.signal_scan_job.run_once``
invokes it, gated behind ``COMPLETE_SET_ARB_ENABLED`` (default OFF), so nothing
scans or books a set until the operator flips the flag.

Pipeline (per candidate market):

    DATA (both order books) -> SIGNAL (fillable_complete_set, capital-bounded)
        -> [live-quote log] -> RISK (gate, complete_set=True, once on combined
        cost) -> EXECUTION (book_complete_set_paper for chosen_mode=="paper",
        book_complete_set_live for "live")

Why a dedicated path (not ``_process_candidate``): the normal pipeline books a
single directional leg via the trade engine. A complete set is a hedged YES+NO
*pair* booked atomically by ``book_complete_set_paper`` — a different execution
primitive — so it gets its own small, dependency-injected pipeline that is unit
-testable in isolation (no DB, broker, or network in tests).

Safety posture:
  * Master flag ``COMPLETE_SET_ARB_ENABLED`` gates the whole branch (caller side).
  * ``MIN_COMPLETE_SET_EDGE`` (default 0.0) is the per-pair margin floor; the
    detector returns ``None`` for a non-positive margin, so even with the master
    flag ON nothing books until the operator sets a positive edge floor too.
  * Quote size is bounded up front by the per-position Kelly cap (``max_shares``),
    and the gate re-checks it as a hard reject (``complete_set`` path in step 13),
    so a sizing drift is caught, never silently shrunk.
  * The gate's ``chosen_mode`` decides the booker: "paper" -> paper primitive,
    "live" -> ``book_complete_set_live`` (which re-asserts all 5 LIVE activation
    guards itself, so the live branch is inert until the operator flips them ON);
    any other value is skipped, never executed.
  * Every fillable quote is logged BEFORE any capital — observability of the rare,
    UNMEASURED edge is the primary deliverable of the dormant phase.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Awaitable, Callable
from uuid import UUID

import structlog

from ...domain.execution.complete_set_exec import (
    book_complete_set_live,
    book_complete_set_paper,
)
from ...domain.risk import constants as K
from ...domain.risk.gate import GateContext, GateResult
from ...domain.risk.gate import evaluate as _gate_evaluate
from ...domain.strategy.complete_set_arb import fillable_complete_set
from ...integrations import polymarket as _polymarket
from ...wallet.ledger import get_balance

log = structlog.get_logger(__name__)

BookFetcher = Callable[[str], Awaitable[dict]]
GateEvaluator = Callable[[GateContext], Awaitable[GateResult]]
Booker = Callable[..., Awaitable[dict]]
BalanceReader = Callable[[UUID], Awaitable[Any]]


@dataclass
class CompleteSetScanResult:
    """Per-user outcome counts for one scan pass."""

    markets_scanned: int = 0
    quotes_found: int = 0
    booked: int = 0
    rejected: int = 0
    errors: int = 0


async def _default_book_fetcher(token_id: str) -> dict:
    return await _polymarket.get_book(token_id)


def _market_field(m: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """First non-None value among ``keys`` in a normalized markets-table row."""
    for k in keys:
        v = m.get(k)
        if v is not None:
            return v
    return default


async def scan_complete_set_for_user(
    row: dict[str, Any],
    markets: list[dict[str, Any]],
    *,
    settings: Any,
    book_fetcher: BookFetcher = _default_book_fetcher,
    gate_evaluate: GateEvaluator = _gate_evaluate,
    booker: Booker = book_complete_set_paper,
    live_booker: Booker = book_complete_set_live,
    balance_reader: BalanceReader = get_balance,
) -> CompleteSetScanResult:
    """Detect + PAPER-book complete-set arbs for one user over ``markets``.

    ``markets`` are normalized markets-table rows (``_load_market`` shape:
    ``id``/``yes_token_id``/``no_token_id``/``condition_id``/``status``/
    ``liquidity_usdc``/``question``/``resolved``). Dependencies are injected so the
    pipeline is hermetically testable. Caller MUST gate on
    ``COMPLETE_SET_ARB_ENABLED`` before calling.
    """
    res = CompleteSetScanResult()
    user_id = UUID(str(row["user_id"]))
    risk_profile = str(row.get("resolved_profile") or "balanced")
    trading_mode = str(row.get("trading_mode") or "paper")
    ulog = log.bind(user_id=str(user_id), strategy="complete_set_arb")

    # Per-pair margin floor — reuse MIN_COMPLETE_SET_EDGE. Default 0.0 keeps the
    # path dormant: fillable_complete_set returns None for a non-positive margin,
    # so no quote / no booking until the operator sets MIN_COMPLETE_SET_EDGE > 0.
    try:
        min_pair_margin = float(getattr(settings, "MIN_COMPLETE_SET_EDGE", 0.0))
    except (TypeError, ValueError):
        min_pair_margin = 0.0
    if not (min_pair_margin > 0.0):
        ulog.info("complete_set_scan_dormant_margin", min_pair_margin=min_pair_margin)
        return res

    # Per-position capital cap = Kelly * max_pos_pct * balance, expressed in
    # shares. Each fillable pair costs < $1, so a share cap == USDC cap keeps the
    # combined cost strictly below the cap; the gate (complete_set step 13) hard
    # -rejects if a drift ever pushes it over rather than silently shrinking.
    profile = K.profile_or_default(risk_profile)
    kelly = min(float(profile.get("kelly", K.KELLY_FRACTION)), K.KELLY_FRACTION)
    max_pos_pct = float(profile["max_pos_pct"])
    try:
        balance = float(await balance_reader(user_id))
    except Exception as exc:  # noqa: BLE001 — fail-closed: no scan on balance error
        ulog.warning("complete_set_scan_balance_read_failed", error=str(exc))
        return res
    max_pos_size = balance * max_pos_pct * kelly
    if not (max_pos_size >= 1.0):  # room for >= 1 pair (detector min_shares=1)
        ulog.info("complete_set_scan_capital_too_small",
                  max_pos_size=round(max_pos_size, 4))
        return res

    for m in markets:
        market_id = ""
        try:
            market_id = str(_market_field(m, "id", "market_id", default="") or "")
            yes_token = _market_field(m, "yes_token_id")
            no_token = _market_field(m, "no_token_id")
            if not market_id or not yes_token or not no_token:
                continue
            if bool(_market_field(m, "resolved", default=False)):
                continue
            res.markets_scanned += 1
            condition_id = str(
                _market_field(m, "condition_id", default=market_id) or market_id
            )
            status = str(_market_field(m, "status", default="active") or "active")
            liquidity = float(
                _market_field(m, "liquidity_usdc", "liquidity", default=0.0) or 0.0
            )
            question = _market_field(m, "question")

            # Arb is time-sensitive: fetch both legs' books concurrently so a
            # market's scan latency is one round-trip, not two.
            yes_book, no_book = await asyncio.gather(
                book_fetcher(str(yes_token)),
                book_fetcher(str(no_token)),
            )
            quote = fillable_complete_set(
                yes_book,
                no_book,
                market_id=market_id,
                condition_id=condition_id,
                yes_token_id=str(yes_token),
                no_token_id=str(no_token),
                min_pair_margin=min_pair_margin,
                max_shares=max_pos_size,
            )
            if quote is None:
                continue
            res.quotes_found += 1
            # Live-quote log BEFORE any capital — the dormant-phase deliverable.
            ulog.info(
                "complete_set_quote",
                market_id=market_id,
                fillable_shares=round(quote.fillable_shares, 4),
                total_cost_usdc=round(quote.total_cost_usdc, 4),
                avg_pair_cost=round(quote.avg_pair_cost, 6),
                gross_margin_usdc=round(quote.gross_margin_usdc, 4),
                net_margin_usdc=round(quote.net_margin_usdc, 4),
                trading_mode=trading_mode,
            )

            idem = f"complete_set:{user_id}:{market_id}"
            ctx = GateContext(
                user_id=user_id,
                telegram_user_id=int(row["telegram_user_id"]),
                role=str(row.get("role") or "user"),
                auto_trade_on=bool(row.get("auto_trade_on", False)),
                paused=bool(row.get("paused", False)),
                market_id=market_id,
                side="yes",  # nominal: a set is hedged, not single-sided
                proposed_size_usdc=Decimal(str(quote.total_cost_usdc)),
                proposed_price=float(quote.avg_pair_cost),
                market_liquidity=liquidity,
                market_status=status,
                edge_bps=None,  # arb margin validated by the detector, not a directional edge
                signal_ts=quote.ts,
                idempotency_key=idem,
                strategy_type="complete_set_arb",
                risk_profile=risk_profile,
                daily_loss_override=(
                    float(row["daily_loss_override"])
                    if row.get("daily_loss_override") is not None else None
                ),
                trading_mode=trading_mode,
                user_min_liquidity=float(row.get("min_liquidity_threshold") or 0.0),
                max_drawdown_pct=(
                    float(row["max_drawdown_pct"])
                    if row.get("max_drawdown_pct") is not None else None
                ),
                live_capital_cap_usdc=float(row.get("live_capital_cap_usdc") or 0.0),
                max_concurrent_override=(
                    int(row["max_concurrent_override"])
                    if row.get("max_concurrent_override") is not None else None
                ),
                complete_set=True,
            )
            gate_res = await gate_evaluate(ctx)
            if not gate_res.approved:
                res.rejected += 1
                ulog.info(
                    "complete_set_gate_rejected",
                    market_id=market_id,
                    reason=gate_res.reason,
                    failed_step=gate_res.failed_step,
                )
                continue

            # The gate's chosen_mode selects the booker. The live primitive
            # re-asserts all 5 LIVE activation guards internally, so this branch
            # is inert until the operator flips them ON; any other mode is skipped.
            if gate_res.chosen_mode == "paper":
                paper_res = await booker(
                    user_id=user_id,
                    telegram_user_id=int(row["telegram_user_id"]),
                    quote=quote,
                    market_question=question,
                    idempotency_key=idem,
                    active_preset=row.get("active_preset"),
                )
                # Mirror the live branch: count only a persisted pair ("open"),
                # never a "duplicate"/"skipped" no-op (booker stamps the quote
                # snapshot into strategy_metadata itself; nothing to thread here).
                if str((paper_res or {}).get("status", "unknown")) == "open":
                    res.booked += 1
                ulog.info(
                    "complete_set_booked",
                    mode="paper",
                    market_id=market_id,
                    total_cost_usdc=round(quote.total_cost_usdc, 4),
                    fillable_shares=round(quote.fillable_shares, 4),
                )
            elif gate_res.chosen_mode == "live":
                # An ambiguous post-submit raises (the booker has already halted +
                # paged); the per-market handler below isolates it from the batch.
                live_res = await live_booker(
                    user_id=user_id,
                    telegram_user_id=int(row["telegram_user_id"]),
                    role=str(row.get("role") or "user"),
                    trading_mode=trading_mode,
                    quote=quote,
                    market_question=question,
                    idempotency_key=idem,
                    yes_book=yes_book,
                    no_book=no_book,
                    active_preset=row.get("active_preset"),
                )
                status = str((live_res or {}).get("status", "unknown"))
                if status in ("open", "naked_halt"):
                    # Both persisted a position; "naked_halt" ALSO engaged the kill
                    # switch (booker already paged) — surface it so the halt is
                    # visible in this user's scan telemetry, not just booked.
                    res.booked += 1
                    if status == "naked_halt":
                        ulog.warning(
                            "complete_set_live_naked_halt",
                            market_id=market_id,
                            note="naked leg persisted (force-exitable) + trading "
                                 "halted — operator reconcile required",
                        )
                elif status in ("no_fill", "unwound", "duplicate", "skipped"):
                    pass  # clean no-op — nothing persisted, nothing to flag
                else:
                    # "naked_halt_persist_failed" (UNTRACKED live exposure) or any
                    # unrecognised status: classify as an error (safe-by-default) so
                    # signal_scan_job never logs a clean run while a confirmed live
                    # leg is unreconciled. The booker has already halted + paged.
                    res.errors += 1
                    ulog.error(
                        "complete_set_live_unreconciled",
                        market_id=market_id,
                        status=status,
                    )
                ulog.info(
                    "complete_set_live_result",
                    market_id=market_id,
                    status=status,
                    total_cost_usdc=round(quote.total_cost_usdc, 4),
                    fillable_shares=round(quote.fillable_shares, 4),
                )
            else:
                ulog.warning(
                    "complete_set_unknown_mode_skipping",
                    market_id=market_id,
                    chosen_mode=gate_res.chosen_mode,
                )
                res.rejected += 1
                continue
        except Exception as exc:  # noqa: BLE001 — isolate one bad market from the batch
            res.errors += 1
            ulog.error(
                "complete_set_scan_market_failed",
                market_id=market_id or None,
                error=str(exc),
            )
    return res
