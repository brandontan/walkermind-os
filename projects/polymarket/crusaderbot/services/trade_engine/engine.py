"""Track A trade engine — signal → risk gate → paper order → paper position.

Pipeline (per signal):
    1. Build GateContext from TradeSignal fields
    2. Evaluate 13-step risk gate (domain.risk.gate.evaluate)
    3. On rejection: return TradeResult(approved=False, ...)
    4. On approval:  call router.execute → paper.execute → instant fill
       Balance debited on open; TP/SL applied_pct snapshots stored on position.
    5. Return TradeResult(approved=True, order_id, position_id, mode="paper")

TP/SL auto-close:
    The exit watcher (domain.execution.exit_watcher) runs independently via
    APScheduler every EXIT_WATCH_INTERVAL seconds. It owns the TP/SL close
    loop — this module does NOT poll positions. The watcher close path:
        run_once -> evaluate (tp_hit | sl_hit | force_close | strategy_exit)
                 -> router.close -> paper.close_position
                 -> ledger.credit_in_conn (balance credited on exit)

Close reasons (domain.positions.registry.ExitReason):
    TP_HIT        — applied_tp_pct breached upward
    SL_HIT        — applied_sl_pct breached downward
    MANUAL        — user-initiated via Telegram My Trades close flow
    EMERGENCY     — force_close_intent set by emergency Pause+Close flow
                    (stored as ExitReason.FORCE_CLOSE in the DB)

Safety:
    * PAPER ONLY — chosen_mode is always "paper" in the current posture.
      The risk gate returns chosen_mode="live" only when ALL activation
      guards pass (ENABLE_LIVE_TRADING + EXECUTION_PATH_VALIDATED +
      CAPITAL_MODE_CONFIRMED + Tier 4). Guards are OFF; this engine never
      reaches a live execution path.
    * No guard mutations in this module — guards are read-only here.
    * asyncio only — no threading.
    * Full type hints throughout.
    * Zero silent failures — every exception propagates to the caller so
      the scan loop or test harness can observe and log it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from ...core import event_bus as _event_bus
from ...domain.execution.router import execute as _router_execute
from ...domain.risk.gate import GateContext, GateResult, evaluate as _risk_evaluate

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExecutionDryRun:
    """Result of a dry_run_execute() call — full pipeline, no submission."""

    market_id: str
    side: str
    size_usdc: Optional[Decimal]
    entry_price: Optional[float]
    risk_decision: str
    would_be_rejected: bool
    rejection_reason: Optional[str]


@dataclass(frozen=True)
class TradeSignal:
    """Typed contract for a single signal entering the trade engine.

    The caller (scan loop, test, or future signal source) is responsible for
    pre-computing all fields; the engine performs no DB reads to fill gaps.
    """

    user_id: UUID
    telegram_user_id: int
    role: str
    auto_trade_on: bool
    paused: bool
    market_id: str
    market_question: Optional[str]
    yes_token_id: Optional[str]
    no_token_id: Optional[str]
    side: str                      # "yes" | "no" (lowercase)
    proposed_size_usdc: Decimal
    price: float
    market_liquidity: float
    market_status: str
    idempotency_key: str
    strategy_type: str
    risk_profile: str
    trading_mode: str              # always "paper" in current posture
    signal_ts: Optional[datetime] = None
    edge_bps: Optional[float] = None
    tp_pct: Optional[float] = None
    sl_pct: Optional[float] = None
    daily_loss_override: Optional[float] = None
    user_min_liquidity: float = 0.0
    max_drawdown_pct: Optional[float] = None
    active_preset: Optional[str] = None
    # Per-user live-trading capital cap (USDC). 0 means the user has not
    # opted in to live mode; gate step 15 rejects any live trade. Set via
    # /api/web/live/enable typed-confirm flow.
    live_capital_cap_usdc: float = 0.0


@dataclass(frozen=True)
class TradeResult:
    """Outcome of a single TradeEngine.execute() call."""

    approved: bool
    # "paper" on successful fill, "duplicate" on idempotent skip, None on rejection
    mode: Optional[str]
    order_id: Optional[UUID]
    position_id: Optional[UUID]
    rejection_reason: Optional[str]
    failed_gate_step: Optional[int]
    # chosen_mode: actual execution mode from the router (equals mode when approved)
    chosen_mode: Optional[str] = None
    # Kelly-adjusted final size committed to the router; None on rejection/duplicate
    final_size_usdc: Optional[Decimal] = None


class TradeEngine:
    """Signal-to-position paper trade engine for Track A.

    One instance is safe to share across the full process lifetime. All state
    lives in the DB; the engine itself is stateless.
    """

    async def execute(self, signal: TradeSignal) -> TradeResult:
        """Run signal through risk gate then execute via router (paper mode).

        Guarantees:
          * Risk gate is always evaluated before router_execute is called.
          * router_execute is NEVER called when the gate rejects.
          * Exceptions from the gate or router propagate to the caller —
            no silent swallowing.
        """
        gate_ctx = self._build_gate_context(signal)

        gate_result: GateResult = await _risk_evaluate(gate_ctx)

        # MONITORING: emit risk gate result so every pipeline stage is observable.
        await _event_bus.emit(
            "pipeline.risk_gate_evaluated",
            user_id=str(signal.user_id),
            market_id=signal.market_id,
            approved=gate_result.approved,
            reason=gate_result.reason if not gate_result.approved else None,
            failed_step=gate_result.failed_step if not gate_result.approved else None,
        )

        if not gate_result.approved:
            logger.info(
                "trade_engine: gate rejected user=%s market=%s reason=%s step=%s",
                signal.user_id, signal.market_id,
                gate_result.reason, gate_result.failed_step,
            )
            return TradeResult(
                approved=False,
                mode=None,
                order_id=None,
                position_id=None,
                rejection_reason=gate_result.reason,
                failed_gate_step=gate_result.failed_step,
                chosen_mode=None,
                final_size_usdc=None,
            )

        final_size = gate_result.final_size_usdc or signal.proposed_size_usdc

        raw = await _router_execute(
            chosen_mode=gate_result.chosen_mode,
            user_id=signal.user_id,
            telegram_user_id=signal.telegram_user_id,
            role=signal.role,
            trading_mode=signal.trading_mode,
            market_id=signal.market_id,
            market_question=signal.market_question,
            yes_token_id=signal.yes_token_id,
            no_token_id=signal.no_token_id,
            side=signal.side,
            size_usdc=final_size,
            price=signal.price,
            idempotency_key=signal.idempotency_key,
            strategy_type=signal.strategy_type,
            tp_pct=signal.tp_pct,
            sl_pct=signal.sl_pct,
            active_preset=signal.active_preset,
        )

        # Idempotent skip: paper engine returns status="duplicate" when the
        # idempotency key was already recorded. Surface this as mode="duplicate"
        # so callers can distinguish a new fill from a replay-safe no-op.
        raw_status = raw.get("status")
        if raw_status == "duplicate":
            out_mode: str = "duplicate"
        else:
            out_mode = raw.get("mode", "paper")
        raw_order_id = raw.get("order_id")
        raw_position_id = raw.get("position_id")

        # Use the router's actual execution mode as chosen_mode so the field
        # reflects what ran rather than what the gate decided (they diverge if
        # the router downgrades live→paper when guards flip between gate and
        # router evaluation).
        actual_mode = raw.get("mode") or gate_result.chosen_mode

        result = TradeResult(
            approved=True,
            mode=out_mode,
            order_id=UUID(str(raw_order_id)) if raw_order_id else None,
            position_id=UUID(str(raw_position_id)) if raw_position_id else None,
            rejection_reason=None,
            failed_gate_step=None,
            chosen_mode=actual_mode,
            final_size_usdc=final_size,
        )

        # Emit position.opened for non-copy-trade fills only.
        # Copy-trade monitor emits copy_trade.executed separately.
        if out_mode != "duplicate" and signal.strategy_type != "copy_trade":
            await _event_bus.emit(
                "position.opened",
                telegram_user_id=signal.telegram_user_id,
                market_id=signal.market_id,
                market_question=signal.market_question,
                side=signal.side,
                size_usdc=final_size,
                price=signal.price,
                tp_pct=signal.tp_pct,
                sl_pct=signal.sl_pct,
                strategy_type=signal.strategy_type,
                position_id=str(raw_position_id) if raw_position_id else None,
                mode=out_mode,
            )

        return result

    async def dry_run_execute(self, signal: TradeSignal) -> ExecutionDryRun:
        """Run the full pipeline (signal → risk → sizing) but stop before submission.

        Validates that the paper path and live path produce identical risk decisions
        for the same input.  No DB writes occur (risk_log aside from gate internal
        logging); no orders are submitted; no positions are created.

        Returns ExecutionDryRun describing what WOULD happen if execute() were called.
        """
        gate_ctx = self._build_gate_context(signal)
        gate_result: GateResult = await _risk_evaluate(gate_ctx)

        if not gate_result.approved:
            return ExecutionDryRun(
                market_id=signal.market_id,
                side=signal.side,
                size_usdc=None,
                entry_price=None,
                risk_decision=gate_result.reason,
                would_be_rejected=True,
                rejection_reason=gate_result.reason,
            )

        final_size = gate_result.final_size_usdc or signal.proposed_size_usdc
        return ExecutionDryRun(
            market_id=signal.market_id,
            side=signal.side,
            size_usdc=final_size,
            entry_price=signal.price,
            risk_decision="approved",
            would_be_rejected=False,
            rejection_reason=None,
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _build_gate_context(signal: TradeSignal) -> GateContext:
        return GateContext(
            user_id=signal.user_id,
            telegram_user_id=signal.telegram_user_id,
            role=signal.role,
            auto_trade_on=signal.auto_trade_on,
            paused=signal.paused,
            market_id=signal.market_id,
            side=signal.side,
            proposed_size_usdc=signal.proposed_size_usdc,
            proposed_price=signal.price,
            market_liquidity=signal.market_liquidity,
            market_status=signal.market_status,
            edge_bps=signal.edge_bps,
            signal_ts=signal.signal_ts,
            idempotency_key=signal.idempotency_key,
            strategy_type=signal.strategy_type,
            risk_profile=signal.risk_profile,
            daily_loss_override=signal.daily_loss_override,
            trading_mode=signal.trading_mode,
            user_min_liquidity=signal.user_min_liquidity,
            max_drawdown_pct=signal.max_drawdown_pct,
            live_capital_cap_usdc=signal.live_capital_cap_usdc,
        )
