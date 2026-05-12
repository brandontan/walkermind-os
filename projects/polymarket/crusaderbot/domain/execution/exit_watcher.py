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
from dataclasses import dataclass
from decimal import Decimal
from typing import Awaitable, Callable, Optional, Protocol

from ... import audit
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


@dataclass(frozen=True)
class ExitDecision:
    """The result of ``evaluate``: either an exit reason + price, or hold."""

    should_exit: bool
    reason: Optional[str]
    current_price: float


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
) -> ExitDecision:
    """Decide whether to close ``position`` this tick.

    Pure-ish: only awaits the strategy hook. Reads no DB, takes no locks,
    sends no orders. The watcher consumes the decision and orchestrates
    the actual close (or hold) in ``_act_on_decision``.
    """
    if position.market_resolved:
        # Resolved markets settle through the redemption pipeline, not CLOB.
        return ExitDecision(should_exit=False, reason=None,
                            current_price=position.current_price())

    cur = position.current_price()

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
        await registry.update_current_price(position.id, decision.current_price, position.user_id)
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


async def run_once(
    *,
    strategy_evaluator: StrategyExitEvaluator = default_strategy_evaluator,
    close_submitter: Optional[order_module.CloseSubmitter] = None,
) -> int:
    """One full pass over every open position. Returns the number of close
    attempts submitted (success + failure both count — they are visible in
    audit.log).

    The scheduler calls this on each ``EXIT_WATCH_INTERVAL`` tick.
    Per-position errors are caught and logged so a single bad row never
    poisons the rest of the batch.
    """
    positions = await registry.list_open_for_exit()
    submitted = 0
    for p in positions:
        try:
            decision = await evaluate(p, strategy_evaluator)
            if decision.should_exit:
                submitted += 1
            await _act_on_decision(
                p, decision, close_submitter=close_submitter,
            )
        except Exception as exc:
            # Per-position failure must not halt the batch. Log at ERROR so
            # the failure is observable; do NOT silently swallow.
            logger.error(
                "exit_watcher: position %s evaluation failed: %s",
                p.id, exc, exc_info=True,
            )
    return submitted


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
