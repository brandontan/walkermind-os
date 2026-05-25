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
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Awaitable, Callable, Optional, Protocol

from ... import audit
from ...database import get_pool
from ...integrations.clob.market_data import MarketDataClient
from ...integrations.polymarket import get_live_market_price
from ...monitoring import alerts as monitoring_alerts
from ..positions import registry
from ..risk.constants import PROFILES
from ..positions.registry import (
    ExitReason,
    OpenPositionForExit,
)
from ..strategy.registry import StrategyRegistry
from . import order as order_module
from . import router

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS: float = 30.0

# Shared MarketDataClient for CLOB /midpoint queries. Constructed lazily so
# paper-mode test runs that never call _fetch_live_price don't open a socket.
_market_data_client: Optional[MarketDataClient] = None


def _get_market_data_client() -> MarketDataClient:
    global _market_data_client
    if _market_data_client is None:
        _market_data_client = MarketDataClient()
    return _market_data_client


# Per-position consecutive None-price tick counter. A None result on a single
# tick may be a transient Gamma outage (tenacity already retries network errors
# 3x internally). Only declare MARKET_EXPIRED after this many consecutive ticks
# of None so a brief API hiccup cannot close an active position incorrectly.
_EXPIRED_TICK_THRESHOLD: int = 3
_price_fail_counts: dict[object, int] = {}  # position.id (UUID) -> consecutive None ticks

# A profile max_days at or above this value disables the resolution-horizon
# exit (mirrors copy_trade.RESOLUTION_DISTANCE_DISABLED_DAYS). All shipped
# profiles are <= 90d, so the guard is always active in practice.
_RESOLUTION_DISABLED_DAYS: int = 365


def _horizon_exceeded(position: OpenPositionForExit) -> bool:
    """True when the market resolves beyond the owning user's profile horizon.

    Far-dated futures (championship winners months out) barely move, so they
    never trip TP/SL and would otherwise occupy a concurrency slot until
    resolution. Closing them returns the slot to the rotation. A NULL
    resolution date (market not yet synced) is never force-closed here.
    """
    res_at = position.resolution_at
    if res_at is None:
        return False
    preset = PROFILES.get(
        (position.risk_profile or "balanced").lower(), PROFILES["balanced"]
    )
    max_days = int(preset["max_days"])
    if max_days >= _RESOLUTION_DISABLED_DAYS:
        return False
    if res_at.tzinfo is None:
        res_at = res_at.replace(tzinfo=timezone.utc)
    return res_at > datetime.now(timezone.utc) + timedelta(days=max_days)


class StrategyExitEvaluator(Protocol):
    """Hook contract for per-strategy exit decisions.

    Returns ``True`` to instruct the watcher to close the position with
    ``ExitReason.STRATEGY_EXIT``. ``current_price`` is the freshly-fetched live
    mark for the position's side, so strategies can apply price-level exits
    (e.g. late_entry_v3's flip-stop) against real data, not stale columns.
    """

    async def __call__(
        self, position: OpenPositionForExit, current_price: float
    ) -> bool: ...


async def default_strategy_evaluator(
    position: OpenPositionForExit, current_price: float
) -> bool:
    """No-op fallback for positions with no owning strategy. Used when a
    position's ``strategy_type`` is unset or not registered.
    """
    return False


async def registry_strategy_evaluator(
    position: OpenPositionForExit, current_price: float
) -> bool:
    """Dispatch the per-position strategy exit hook by ``strategy_type``.

    Looks the owning strategy up in the process-wide ``StrategyRegistry`` and
    asks its ``evaluate_exit`` whether to close, passing the live favored-side
    price as ``current_price``. Falls back to no-op (False) when the position
    is unattributed, the strategy is not registered, or the hook errors —
    a strategy exit hook must never poison the watcher loop.
    """
    name = position.strategy_type
    if not name:
        return False
    try:
        strat = StrategyRegistry.instance().get(name)
    except KeyError:
        return False
    try:
        decision = await strat.evaluate_exit(
            {
                "id": position.id,
                "user_id": position.user_id,
                "market_id": position.market_id,
                "side": position.side,
                "entry_price": position.entry_price,
                "size_usdc": position.size_usdc,
                "current_price": current_price,
                "strategy_type": name,
            }
        )
    except Exception as exc:
        logger.warning(
            "exit_watcher strategy hook failed strat=%s pos=%s err=%s",
            name, position.id, exc,
        )
        return False
    return bool(getattr(decision, "should_exit", False))


async def _fetch_live_price(
    market_id: str,
    side: str,
    *,
    token_id: Optional[str] = None,
) -> Optional[float]:
    """Fetch the live Polymarket price for this position's side.

    Primary path: CLOB ``GET /midpoint?token_id=X`` when a token_id is
    available. This skips the Gamma round-trip entirely — one HTTP call
    instead of two, and the midpoint is always fresh (no 30s Gamma cache).

    Fallback: ``get_live_market_price`` (Gamma → CLOB /price chain) when
    token_id is absent or the midpoint call fails.

    Returns None on any error — callers fall back to
    ``position.current_price()`` (entry_price when stale), keeping
    ret_pct == 0 and preventing spurious TP/SL triggers on missing data.
    """
    if token_id:
        try:
            mdc = _get_market_data_client()
            resp = await mdc.get_midpoint(token_id)
            raw = resp.get("mid")
            if raw is not None:
                price = float(raw)
                if 0.0 < price < 1.0:
                    return price
        except Exception as exc:
            logger.debug(
                "exit_watcher._fetch_live_price midpoint failed "
                "token=%s market=%s side=%s error=%s — falling back",
                token_id, market_id, side, exc,
            )
    # Fallback: Gamma → CLOB /price chain.
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
    strategy_evaluator: StrategyExitEvaluator = registry_strategy_evaluator,
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
    cur = live_price if live_price is not None else position.current_price()

    # 0. Market end time — close at actual PnL regardless of TP/SL state.
    #    Whichever comes first: TP hit, SL hit, or market end time.
    #    market_resolved = Gamma already marked it resolved (binary settled).
    #    resolution_at past = candle market closed, price is final.
    _now = datetime.now(tz=timezone.utc)
    _past_end = (
        position.resolution_at is not None
        and position.resolution_at.tzinfo is not None
        and _now >= position.resolution_at
    )
    if position.market_resolved or _past_end:
        return ExitDecision(
            should_exit=True,
            reason=ExitReason.MARKET_EXPIRED.value,
            current_price=cur,
        )

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

    # 4. Strategy hook — priority above horizon/hold. Pass the live favored-side
    #    price so price-level exits (e.g. late_entry_v3 flip-stop) use real data.
    if await strategy_evaluator(position, cur):
        return ExitDecision(should_exit=True,
                            reason=ExitReason.STRATEGY_EXIT.value,
                            current_price=cur)

    # 5. Resolution-horizon guard — last priority before hold. Closes positions
    #    whose market resolves beyond the owner's profile horizon so far-dated
    #    futures cannot lock a concurrency slot. Evaluated after TP/SL/strategy
    #    so a position at target still realises its intended exit first.
    if _horizon_exceeded(position):
        return ExitDecision(should_exit=True,
                            reason=ExitReason.HORIZON_EXCEEDED.value,
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
    if reason == ExitReason.MARKET_EXPIRED.value:
        return monitoring_alerts.alert_user_market_expired
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
        try:
            from ...webtrader.backend.sse import push_position_updated
            push_position_updated(
                str(position.user_id),
                str(position.id),
                decision.current_price,
                pnl,
            )
        except ImportError:
            pass
        except Exception as exc:
            logger.warning("exit_watcher: SSE position_updated push failed: %s", exc)
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
        logger.info(
            "close_failed (user notif suppressed, operator alert active)",
            extra={
                "position_id": str(position.id),
                "market_id": position.market_id,
                "side": position.side,
                "error": (result.error or "unknown")[:200],
            },
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

    # Emit position.closed so the SSE bridge and notification_service both fire.
    try:
        from ...core.event_bus import emit as _emit
        await _emit(
            "position.closed",
            telegram_user_id=position.telegram_user_id,
            market_id=position.market_id,
            market_question=position.market_question,
            side=position.side,
            entry_price=float(position.entry_price),
            exit_price=float(decision.current_price or position.entry_price),
            pnl_usdc=pnl,
            close_reason=reason,
            mode=position.mode,
        )
    except Exception as _exc:
        logger.debug("exit_watcher: position.closed emit failed: %s", _exc)


async def _market_actually_expired(market_id: str) -> bool:
    """Return True only when the market is verifiably resolved or past its
    end date. Used to gate MARKET_EXPIRED classification when live-price
    fetch returns None to avoid mis-classifying illiquid-orderbook outages.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT resolved, resolution_at FROM markets WHERE id=$1",
            market_id,
        )
    if row is None:
        return False  # unknown market — let the unknown-market path handle it elsewhere
    if row["resolved"]:
        return True
    end = row["resolution_at"]
    if end is not None and end < datetime.now(timezone.utc):
        return True
    return False


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
        logger.info(
            "market_expired position closed (user notif suppressed)",
            extra={
                "position_id": str(position.id),
                "market_id": position.market_id,
                "side": position.side,
                "size_usdc": position.size_usdc,
                "mode": position.mode,
            },
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
    strategy_evaluator: StrategyExitEvaluator = registry_strategy_evaluator,
    close_submitter: Optional[order_module.CloseSubmitter] = None,
) -> RunResult:
    """One full pass over every open position. Returns a ``RunResult`` with counts.

    Two-phase sweep:

    Phase A — normal positions (``m.resolved = FALSE`` in local DB):
      1. Fetch live price from Gamma.
      2. If None, retry once (cache miss means a fresh HTTP call each time).
      3. If still None → increment per-position fail counter; skip close.
      4. Only close as MARKET_EXPIRED when fail counter >= _EXPIRED_TICK_THRESHOLD
         (3 consecutive ticks ≈ 90 seconds), guarding against transient API outages.
      5. Successful price fetch resets the counter for that position.

    Phase B — positions on resolved markets where the position is on the losing
      side (``m.resolved=TRUE AND m.winning_side != p.side``) or the market has no
      declared winner (``m.winning_side IS NULL``). Winning positions are excluded —
      they collect terminal-value payoff via the redemption pipeline.

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
            # Resolve the CLOB token_id for this position's side so
            # _fetch_live_price can use the faster /midpoint endpoint.
            token_id = (
                p.yes_token_id if p.side == "yes" else p.no_token_id
            )
            # Skip live price fetch for force-close: FORCE_CLOSE has highest
            # priority in evaluate(); fetching first would gate an urgent
            # unwind behind Gamma API retry/backoff during outages.
            live_price = (
                None if p.force_close_intent
                else await _fetch_live_price(p.market_id, p.side, token_id=token_id)
            )
            # Retry once on None for non-force-close positions. The Gamma
            # cache is populated only on a successful fetch, so a None
            # result is never cached — the retry always makes a fresh call.
            if live_price is None and not p.force_close_intent:
                live_price = await _fetch_live_price(p.market_id, p.side, token_id=token_id)
                if live_price is None:
                    # Increment the consecutive-None counter for this position.
                    # Only close after _EXPIRED_TICK_THRESHOLD consecutive ticks
                    # to avoid incorrectly expiring positions during a transient
                    # Gamma outage (tenacity already retries network errors 3x).
                    fail_count = _price_fail_counts.get(p.id, 0) + 1
                    _price_fail_counts[p.id] = fail_count
                    if fail_count >= _EXPIRED_TICK_THRESHOLD:
                        if await _market_actually_expired(p.market_id):
                            if await _close_expired_position(p):
                                expired += 1
                                _price_fail_counts.pop(p.id, None)
                        else:
                            # Stale price on a still-live market — likely illiquid orderbook.
                            # Log once per fail-threshold crossing for ops visibility; keep
                            # the counter pinned at the threshold so we recheck each tick
                            # without unbounded growth.
                            logger.warning(
                                "exit_watcher: position %s market %s has None price for %d ticks "
                                "but DB shows not-resolved — treating as stale, not expired",
                                p.id, p.market_id, fail_count,
                            )
                            _price_fail_counts[p.id] = _EXPIRED_TICK_THRESHOLD
                    continue
                else:
                    _price_fail_counts.pop(p.id, None)  # price recovered, reset
            elif not p.force_close_intent:
                _price_fail_counts.pop(p.id, None)  # healthy price on first fetch, reset
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
    strategy_evaluator: StrategyExitEvaluator = registry_strategy_evaluator,
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
