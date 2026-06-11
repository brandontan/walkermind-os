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
    # OPTIONAL manual live cap (USDC); 0 = no manual cap. The authoritative
    # live bound is the user's REAL deposited balance (live_balance_usdc) —
    # gate step 15 enforces min(manual cap if >0, real balance).
    live_capital_cap_usdc: float = 0.0
    # The user's REAL deposited balance — preloaded by the scan loader
    # (live-mode-truth lane); the live bankroll for sizing + step 15.
    # None = legacy construction site; the gate falls back to a one-shot read.
    live_balance_usdc: Optional[float] = None
    # Per-user concurrent-trades override (1..20). None = use profile default.
    max_concurrent_override: Optional[int] = None
    # WARP-89 (gate-hotpath-db-fix): authoritative risk-profile CAP%
    # (capital_alloc_pct) PRELOADED once per user per tick by the scan orchestrator
    # and flowed into GateContext.capital_alloc_pct so the per-candidate risk gate
    # does ZERO asyncpg reads for it. None = caller did not preload → the gate falls
    # back to its one-shot DB loader (legacy construction sites only).
    capital_alloc_pct: Optional[float] = None
    # Per-task opt-in bypass for global auto_trade_on (gate step 2). Copy-trade
    # tasks set this True because copy_trade_tasks.status='active' is the
    # explicit per-task opt-in. ctx.paused is still honoured.
    bypass_auto_trade_check: bool = False
    # Opaque per-strategy snapshot (e.g. weather city/bucket bounds, entry
    # forecast mean, high-water price). Persisted to positions.strategy_metadata
    # and replayed into the strategy exit hook so exits like the weather
    # trailing-stop + adaptive forecast-shift have the data they need. None for
    # strategies that emit no metadata.
    strategy_metadata: Optional[dict] = None
    # Robustness gate (Phase-2c-1b). False only when the candidate's module is
    # classified UNTRADEABLE and ROBUSTNESS_GATE_ENABLED is on. Default True → no
    # effect. Flows into GateContext.module_live_eligible (downgrade-only: a live
    # trade becomes paper; never enables live).
    module_live_eligible: bool = True
    # WARP-87 follow-up (smart-strike-cell-cap-binding): the trading cell
    # ("{asset}/{timeframe}", e.g. "btc/5m"), live order-book depth (USDC) and
    # complete-set spread the Smart Strike candidate measured at scan time. Threaded
    # straight into GateContext so the LIVE-only step-14b slippage gate binds the
    # per-cell size cap (ctx.cell) and estimates slippage from the REAL depth/spread.
    # None (legacy / non-Smart-Strike / fast_topup candidate) → no per-cell cap and
    # the gate's existing depth=market_liquidity / spread=1.0 fallback applies.
    cell: Optional[str] = None
    orderbook_depth_usdc: Optional[float] = None
    spread: Optional[float] = None
    # WARP (smart-strike-slippage-edge-gate, F1): LIVE step-14b edge policy for a
    # candidate with no measured edge. Threaded into GateContext.require_measured_edge.
    # Default True (back-compat: non-scan callers keep the prior HALT-on-no-edge);
    # the scan path sets it from the resolved SMART_STRIKE_REQUIRE_MEASURED_EDGE
    # toggle (env default False → per-cell cap is the sole control for a capped cell).
    require_measured_edge: bool = True
    # Option 3 (smart-strike-real-edge): the Smart Strike candidate's measured GROSS
    # edge (bps) = the entry-side oracle fair-value edge, used as the step-14b
    # slippage-of-edge denominator in real-edge mode (require_measured_edge True).
    # None for a non-Smart-Strike candidate / when the oracle gave no positive edge.
    slippage_gross_edge_bps: Optional[float] = None


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
            strategy_metadata=signal.strategy_metadata,
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
            # getattr: stub TradeSignals in existing harnesses predate the
            # field; None routes the gate to its one-shot fallback read.
            live_balance_usdc=getattr(signal, "live_balance_usdc", None),
            max_concurrent_override=signal.max_concurrent_override,
            # WARP-89: pass the preloaded CAP% straight through to the gate so the
            # per-candidate evaluate() reads it instead of doing a DB SELECT.
            capital_alloc_pct=signal.capital_alloc_pct,
            bypass_auto_trade_check=signal.bypass_auto_trade_check,
            module_live_eligible=signal.module_live_eligible,
            # WARP-86: thread the user's active preset so the gate's AUTO entry
            # constraint (step 4) sees it and fences AUTO to candle_auto only.
            active_preset=signal.active_preset,
            # WARP-87 follow-up (smart-strike-cell-cap-binding): thread the trading
            # cell + real order-book depth/spread so the LIVE-only step-14b slippage
            # gate binds the per-cell size cap (ctx.cell) and estimates slippage from
            # the candidate's measured depth/spread instead of the fallback inputs.
            cell=signal.cell,
            orderbook_depth_usdc=signal.orderbook_depth_usdc,
            spread=signal.spread,
            # WARP (smart-strike-slippage-edge-gate, F1): LIVE no-edge policy.
            require_measured_edge=signal.require_measured_edge,
            # Option 3 (smart-strike-real-edge): measured slippage gross-edge (bps).
            slippage_gross_edge_bps=signal.slippage_gross_edge_bps,
        )
