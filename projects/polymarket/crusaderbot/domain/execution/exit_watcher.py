"""Exit watcher worker — per-position TP/SL/force-close/strategy auto-close.

Priority chain (first match wins, evaluated each tick per open position):

    1. force_close_intent == TRUE      -> ExitReason.FORCE_CLOSE
    2. ret_pct >= applied_tp_pct       -> ExitReason.TP_HIT
    3. ret_pct <= -applied_sl_pct      -> ExitReason.SL_HIT
    4. strategy.evaluate_exit(...) EXIT -> ExitReason.STRATEGY_EXIT
    5. otherwise                        -> hold (refresh current_price only)

Tick semantics:
  * Async task only — never threading.
  * Default poll interval ``DEFAULT_POLL_INTERVAL_SECONDS`` (30s); the
    scheduler-driven entry point (``run_once``) is what production calls
    every ``EXIT_WATCH_INTERVAL`` seconds. ``run_forever`` is supplied for
    standalone deployments / tests.
  * Resolved markets are skipped — they settle through the redemption
    pipeline (terminal value 1 / 0 USDC), not a CLOB re-quote.
  * Close orders go through ``order.submit_close_with_retry`` which wraps
    ``router.close`` with a single 5s-delayed retry. CLOB internals are
    NOT touched here — the watcher is engine-agnostic.

Failure handling:
  * Engine error -> retry once after 5s -> if still failing:
      - increment ``positions.close_failure_count``
      - alert the user (close failed, will retry)
      - if failure_count >= CLOSE_FAILURE_OPERATOR_THRESHOLD: alert operator
      - position stays 'open' and is re-evaluated on the next tick
        (transient broker outages must not poison live exposure into a
        permanent close_failed state — the operator finalizes manually)
  * No silent ``except: pass`` anywhere — every catch logs at WARN/ERROR.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Awaitable, Callable, Optional, Protocol

from ... import audit
from ...integrations.polymarket import get_live_market_price
from ...monitoring import alerts as monitoring_alerts
from ..positions import registry
from ..positions.registry import (
    ExitReason,
    OpenPositionForExit,
)
from . import order as order_module
from . import router

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS: float = 30.0


class StrategyExitEvaluator(Protocol):
    """Hook contract for per-strategy exit decisions.

    Returns ``True`` to instruct the watcher to close the position with
    ``ExitReason.STRATEGY_EXIT``. Defaults to a no-op for now (see
    ``default_strategy_evaluator``); copy_trade enters and relies on TP/SL.
    """

    async def __call__(self, position: OpenPositionForExit) -> bool: ...


async def default_strategy_evaluator(position: OpenPositionForExit) -> bool:
    """No current strategy emits standalone exit signals — copy_trade enters
    and relies on TP/SL. The hook exists so future signal-driven exits drop
    in without disturbing priority order.
    """
    return False


async def _fetch_live_price(market_id: str, side: str) -> Optional[float]:
    """Fetch the live Polymarket price for this position's side.

    Error-isolated wrapper around ``get_live_market_price``. Returns None when
    the API is unreachable or returns an unparseable response — the caller in
    ``evaluate`` falls back to ``position.current_price()`` (which returns
    ``entry_price`` when market columns are stale), keeping ret_pct == 0 and
    preventing spurious TP/SL triggers on missing data.
    """
    try:
        return await get_live_market_price(market_id, side)
    except Exception as exc:
        logger.warning(
            "exit_watcher._fetch_live_price market=%s side=%s error=%s",
            market_id, side, exc,
        )
        return None


def _compute_pnl_usdc(
    side: str,
    entry_price: float,
    current_price: float,
    size_usdc: float,
) -> float:
    """Unrealised P&L in USDC using the same per-side formula as ``_return_pct``.

    Returns 0.0 on degenerate inputs (size_usdc <= 0).
    """
    if size_usdc <= 0.0:
        return 0.0
    ret = _return_pct(side=side, entry_price=entry_price, current_price=current_price)
    return round(ret * size_usdc, 6)


@dataclass(frozen=True)
class ExitDecision:
    """The result of ``evaluate``: either an exit reason + price, or hold."""

    should_exit: bool
    reason: Optional[str]
    current_price: float


@dataclass(frozen=True)
class RunResult:
    """Counts from one full pass of ``run_once``.

    submitted — TP/SL/force/strategy close attempts dispatched to the CLOB.
    expired   — positions closed as MARKET_EXPIRED (no CLOB order; wallet credited).
    held      — positions evaluated, price refreshed, no exit triggered.
    errors    — per-position exceptions caught by the batch error net.
    """

    submitted: int = 0
    expired: int = 0
    held: int = 0
    errors: int = 0


def _return_pct(*, side: str, entry_price: float, current_price: float) -> float:
    """Per-side P&L percentage at the current mark.

    YES side: (current - entry) / entry
    NO side : ((1 - current) - (1 - entry)) / (1 - entry)
            = (entry - current) / (1 - entry)

    The denominators are floored so a degenerate entry at exactly 0 or 1
    cannot produce a divide-by-zero — those are upstream-rejected by the
    risk gate but the floor is cheap insurance.
    """
    if side == "yes":
        return (current_price - entry_price) / max(entry_price, 1e-6)
    comp_entry = 1.0 - entry_price
    comp_exit = 1.0 - current_price
    return (comp_exit - comp_entry) / max(comp_entry, 1e-6)


async def evaluate(
    position: OpenPositionForExit,
    strategy_evaluator: StrategyExitEvaluator = default_strategy_evaluator,
    live_price: Optional[float] = None,
) -> ExitDecision:
    """Decide whether to close ``position`` this tick.

    Pure-ish: only awaits the strategy hook. Reads no DB, takes no locks,
    sends no orders. The watcher consumes the decision and orchestrates
    the actual close (or hold) in ``_act_on_decision``.

    ``live_price`` is a freshly-fetched Polymarket price passed in by
    ``run_once``; when provided it overrides ``position.current_price()`` so
    TP/SL evaluations use real mark-to-market data instead of the stale
    ``markets.yes_price``/``no_price`` columns (which may lag or be NULL).
    """
    if position.market_resolved:
        # Resolved markets settle through the redemption pipeline, not CLOB.
        cur = live_price if live_price is not None else position.current_price()
        return ExitDecision(should_exit=False, reason=None, current_price=cur)

    cur = live_price if live_price is not None else position.current_price()

    # 1. force_close_intent — highest priority. The Pause+Close-All Telegram
    #    flow sets this marker so the watcher unwinds on the next tick
    #    regardless of TP/SL/strategy state.
    if position.force_close_intent:
        return ExitDecision(should_exit=True,
                            reason=ExitReason.FORCE_CLOSE.value,
                            current_price=cur)

    ret = _return_pct(side=position.side,
                      entry_price=position.entry_price,
                      current_price=cur)

    # 2. TP — read from the immutable applied_tp_pct snapshot, NOT from
    #    user_settings.tp_pct. A user toggling TP via /settings must NOT
    #    affect open positions.
    if position.applied_tp_pct is not None and ret >= position.applied_tp_pct:
        return ExitDecision(should_exit=True,
                            reason=ExitReason.TP_HIT.value,
                            current_price=cur)

    # 3. SL — same snapshot rule. Note SL is stored as a positive magnitude;
    #    the trigger condition compares against -applied_sl_pct so a 0.10
    #    SL means "close once we are 10% in the red".
    if position.applied_sl_pct is not None and ret <= -position.applied_sl_pct:
        return ExitDecision(should_exit=True,
                            reason=ExitReason.SL_HIT.value,
                            current_price=cur)

    # 4. Strategy hook — last priority above hold.
    if await strategy_evaluator(position):
        return ExitDecision(should_exit=True,
                            reason=ExitReason.STRATEGY_EXIT.value,
                            current_price=cur)

    return ExitDecision(should_exit=False, reason=None, current_price=cur)


def _user_alert_for_reason(reason: str):
    """Map an exit reason to its user-side alert function."""
    if reason == ExitReason.TP_HIT.value:
        return monitoring_alerts.alert_user_tp_hit
    if reason == ExitReason.SL_HIT.value:
        return monitoring_alerts.alert_user_sl_hit
    if reason == ExitReason.FORCE_CLOSE.value:
        return monitoring_alerts.alert_user_force_close
    if reason == ExitReason.STRATEGY_EXIT.value:
        return monitoring_alerts.alert_user_strategy_exit
    return None


async def _act_on_decision(
    position: OpenPositionForExit,
    decision: ExitDecision,
    *,
    close_submitter: Optional[order_module.CloseSubmitter] = None,
) -> None:
    """Execute the watcher's decision: close+alert, or refresh current_price."""
    if not decision.should_exit:
        pnl = _compute_pnl_usdc(
            position.side,
            position.entry_price,
            decision.current_price,
            position.size_usdc,
        )
        await registry.update_current_price(
            position.id, decision.current_price, position.user_id, pnl_usdc=pnl
        )
        return

    reason = decision.reason or ExitReason.STRATEGY_EXIT.value
    submitter = close_submitter or router.close
    result = await order_module.submit_close_with_retry(
        position=position.to_router_dict(),
        exit_price=decision.current_price,
        exit_reason=reason,
        submitter=submitter,
    )

    if not result.ok:
        new_count = await registry.record_close_failure(position.id, position.user_id)
        await audit.write(
            actor_role="bot", action="exit_watcher_close_failed",
            user_id=position.user_id,
            payload={"position_id": str(position.id),
                     "reason": reason,
                     "failure_count": new_count,
                     "error": (result.error or "")[:500]},
        )
        await monitoring_alerts.alert_user_close_failed(
            telegram_user_id=position.telegram_user_id,
            market_id=position.market_id,
            market_question=position.market_question,
            side=position.side,
            error=result.error or "unknown",
        )
        await monitoring_alerts.alert_operator_close_failed_persistent(
            position_id=position.id,
            user_id=position.user_id,
            market_id=position.market_id,
            side=position.side,
            mode=position.mode,
            failure_count=new_count,
            last_error=result.error or "unknown",
        )
        return

    # Successful close: reset the failure counter (idempotent if it was 0).
    if position.close_failure_count > 0:
        await registry.reset_close_failure(position.id, position.user_id)

    payload = result.payload or {}
    pnl_decimal = payload.get("pnl_usdc", Decimal("0"))
    try:
        pnl = float(pnl_decimal)
    except (TypeError, ValueError):
        pnl = 0.0

    await audit.write(
        actor_role="bot", action="exit_watcher_close_ok",
        user_id=position.user_id,
        payload={"position_id": str(position.id),
                 "reason": reason,
                 "exit_price": decision.current_price,
                 "pnl_usdc": str(pnl_decimal),
                 "mode": position.mode},
    )

    alert_fn = _user_alert_for_reason(reason)
    if alert_fn is not None:
        await alert_fn(
            telegram_user_id=position.telegram_user_id,
            market_id=position.market_id,
            market_question=position.market_question,
            side=position.side,
            exit_price=decision.current_price,
            pnl_usdc=pnl,
            mode=position.mode,
        )


async def _close_expired_position(position: OpenPositionForExit) -> bool:
    """Close a position because its market is no longer live on Gamma.

    Called when ``_fetch_live_price`` returns None after one retry (Phase A),
    or when the position is on a market already marked resolved in the local DB
    but not yet processed by the redemption pipeline (Phase B).

    Atomic transaction in ``registry.close_as_expired``:
      status='closed', exit_reason='market_expired', pnl_usdc=0.0,
      wallets.balance_usdc += size_usdc, ledger INSERT type='trade_close'.

    Returns True iff the position was closed. Returns False if the position
    was already closed by another path (idempotent).
    """
    logger.warning(
        "Position %s: market %s not found on Gamma after retries — closing as MARKET_EXPIRED",
        position.id, position.market_id,
    )
    try:
        closed = await registry.close_as_expired(
            position.id, position.user_id, position.size_usdc
        )
        if not closed:
            logger.info(
                "close_as_expired: position %s already closed (idempotent skip)",
                position.id,
            )
            return False
        await audit.write(
            actor_role="bot", action="exit_watcher_market_expired",
            user_id=position.user_id,
            payload={
                "position_id": str(position.id),
                "market_id": position.market_id,
                "size_usdc": position.size_usdc,
                "mode": position.mode,
            },
        )
        await monitoring_alerts.alert_user_market_expired(
            telegram_user_id=position.telegram_user_id,
            market_id=position.market_id,
            market_question=position.market_question,
            side=position.side,
            size_usdc=position.size_usdc,
            mode=position.mode,
        )
        return True
    except Exception as exc:
        logger.error(
            "exit_watcher._close_expired_position position=%s error=%s",
            position.id, exc, exc_info=True,
        )
        return False


async def run_once(
    *,
    strategy_evaluator: StrategyExitEvaluator = default_strategy_evaluator,
    close_submitter: Optional[order_module.CloseSubmitter] = None,
) -> RunResult:
    """One full pass over every open position. Returns a ``RunResult`` with counts.

    Two-phase sweep:

    Phase A — normal positions (``m.resolved = FALSE`` in local DB):
      1. Fetch live price from Gamma.
      2. If None, retry once (cache miss means a fresh HTTP call each time).
      3. If still None → close as MARKET_EXPIRED; skip evaluate/act.
      4. Otherwise evaluate TP/SL/force/strategy and act.

    Phase B — positions on already-resolved markets (``m.resolved = TRUE``):
      These are excluded from Phase A's query entirely. Close them as
      MARKET_EXPIRED directly — no price fetch needed.

    Per-position errors are caught and logged so a single bad row never
    poisons the rest of the batch.
    """
    submitted = 0
    expired = 0
    held = 0
    errors = 0

    # Phase A: normal positions — market not yet resolved in local DB.
    positions = await registry.list_open_for_exit()
    for p in positions:
        try:
            # Skip live price fetch for force-close: FORCE_CLOSE has highest
            # priority in evaluate(); fetching first would gate an urgent
            # unwind behind Gamma API retry/backoff during outages.
            live_price = (
                None if p.force_close_intent
                else await _fetch_live_price(p.market_id, p.side)
            )
            # Retry once on None for non-force-close positions. The Gamma
            # cache is populated only on a successful fetch, so a None
            # result is never cached — the retry always makes a fresh call.
            if live_price is None and not p.force_close_intent:
                live_price = await _fetch_live_price(p.market_id, p.side)
                if live_price is None:
                    if await _close_expired_position(p):
                        expired += 1
                    continue
            decision = await evaluate(p, strategy_evaluator, live_price=live_price)
            if decision.should_exit:
                submitted += 1
            else:
                held += 1
            await _act_on_decision(
                p, decision, close_submitter=close_submitter,
            )
        except Exception as exc:
            logger.error(
                "exit_watcher: position %s evaluation failed: %s",
                p.id, exc, exc_info=True,
            )
            errors += 1

    # Phase B: positions on resolved markets — invisible to Phase A's query.
    resolved_positions = await registry.list_open_on_resolved_markets()
    for p in resolved_positions:
        try:
            if await _close_expired_position(p):
                expired += 1
        except Exception as exc:
            logger.error(
                "exit_watcher: resolved-market position %s close failed: %s",
                p.id, exc, exc_info=True,
            )
            errors += 1

    if expired > 0:
        logger.info(
            "exit_watcher.run_once: submitted=%d expired=%d held=%d errors=%d",
            submitted, expired, held, errors,
        )
    return RunResult(submitted=submitted, expired=expired, held=held, errors=errors)


async def run_forever(
    *,
    interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    strategy_evaluator: StrategyExitEvaluator = default_strategy_evaluator,
    close_submitter: Optional[order_module.CloseSubmitter] = None,
    stop: Optional[Callable[[], bool]] = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Standalone async loop. Production runs ``run_once`` from the
    APScheduler tick instead — this is provided so tests and one-off
    deployments (no APScheduler) can drive the watcher directly.

    ``stop`` is an optional poll predicate (returns True to break) used by
    tests; in production the loop runs until the parent task is cancelled.
    """
    logger.info("exit_watcher.run_forever interval=%.1fs", interval_seconds)
    while True:
        if stop is not None and stop():
            logger.info("exit_watcher.run_forever stop predicate -> exiting")
            return
        try:
            await run_once(
                strategy_evaluator=strategy_evaluator,
                close_submitter=close_submitter,
            )
        except Exception as exc:
            # run_once already logs per-position failures; this catch is the
            # last-resort net for an infrastructure-level error (DB pool
            # gone, etc.). The loop must NOT die — APScheduler equivalents
            # would simply restart the tick on the next interval.
            logger.error("exit_watcher.run_once raised: %s", exc, exc_info=True)
        await sleep(interval_seconds)
