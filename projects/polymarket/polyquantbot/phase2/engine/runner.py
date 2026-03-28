"""
Phase 2 main loop.
Cycle:
  1. Evaluate exits for all open positions
  2. If slots available: scan → signals → portfolio select → execute
  3. Every N cycles: send Telegram summary
Run: python -m engine.runner
"""

import asyncio
import os
import time
import structlog
import yaml
from dotenv import load_dotenv

from infra.polymarket_client import fetch_markets
from infra.telegram_service import TradeNotification, send_open, send_closed, send_summary
from core.signal_model import BayesianSignalModel
from core.execution.paper_executor import execute_paper_order
from engine.state_manager import StateManager, OpenTrade
from engine.portfolio_manager import select_trades
from engine.position_manager import evaluate_exits
from engine.performance_tracker import PerformanceTracker

load_dotenv()
log = structlog.get_logger()


def load_config(path: str = "config.yaml") -> dict:
    """Load YAML config from the given path."""
    with open(path) as f:
        return yaml.safe_load(f)


async def run() -> None:
    """Start the Phase 2 polyquantbot main loop."""
    cfg = load_config()
    t_cfg = cfg["trading"]
    p_cfg = cfg["paper"]
    e_cfg = cfg["execution"]
    pos_cfg = cfg["position"]

    poll_interval: int     = t_cfg["poll_interval_seconds"]
    min_ev: float          = t_cfg["min_ev_threshold"]
    max_pos_pct: float     = t_cfg["max_position_pct"]
    max_concurrent: int    = t_cfg["max_concurrent_positions"]
    max_per_cycle: int     = t_cfg["max_trades_per_cycle"]
    max_exposure: float    = t_cfg["max_total_exposure_pct"]
    summary_every: int     = t_cfg["summary_every_n_cycles"]
    initial_balance: float = p_cfg["initial_balance"]
    slippage_bps: int      = p_cfg["slippage_bps"]
    depth_threshold: float = p_cfg["market_depth_threshold"]
    fee_pct: float         = e_cfg["fee_pct"]
    tp_pct: float          = pos_cfg["tp_pct"]
    sl_pct: float          = pos_cfg["sl_pct"]
    timeout_min: float     = pos_cfg["timeout_minutes"]

    db_path = os.getenv("DATABASE_PATH", "./data/phase2.db")
    state = StateManager(db_path=db_path, initial_balance=initial_balance)
    await state.init()

    tracker = PerformanceTracker(state)
    model = BayesianSignalModel(min_ev_threshold=min_ev)
    cycle = 0

    log.info("phase2_runner_started", poll_interval=poll_interval, max_concurrent=max_concurrent)

    while True:
        cycle_start = time.time()
        cycle += 1

        try:
            # ── STEP 1: Evaluate exits for all open positions ────────────────────────
            open_positions = await state.get_open_positions()
            exits = evaluate_exits(open_positions, tp_pct, sl_pct, timeout_min)

            for decision in exits:
                balance = await state.get_balance()
                new_balance = balance + decision.pnl
                await state.close_trade(decision.trade.trade_id, decision.exit_price, decision.pnl)
                await state.update_balance(new_balance)
                await tracker.record(pnl=decision.pnl, ev=decision.trade.ev)

                duration = (time.time() - decision.trade.opened_at) / 60.0
                cost_basis = decision.trade.entry_price * decision.trade.size
                pnl_pct = (decision.pnl / cost_basis * 100) if cost_basis > 0 else 0.0

                notif = TradeNotification(
                    market_id=decision.trade.market_id,
                    question=decision.trade.question,
                    outcome=decision.trade.outcome,
                    entry_price=decision.trade.entry_price,
                    exit_price=decision.exit_price,
                    size=decision.trade.size,
                    ev=decision.trade.ev,
                    fee=decision.trade.fee,
                    pnl=decision.pnl,
                    pnl_pct=pnl_pct,
                    duration_minutes=duration,
                    balance=new_balance,
                )
                await send_closed(notif)
                log.info(
                    "position_closed",
                    trade_id=decision.trade.trade_id,
                    reason=decision.reason,
                    pnl=decision.pnl,
                    balance=round(new_balance, 2),
                )

            # ── STEP 2: Entry scan (only if slots available) ───────────────────────
            open_positions = await state.get_open_positions()
            open_market_ids = {p.market_id for p in open_positions}

            if len(open_positions) < max_concurrent:
                markets = await fetch_markets(limit=10)
                signals = model.generate_all(markets)
                balance = await state.get_balance()

                if not signals:
                    log.info("no_signal_found", markets_scanned=len(markets))
                else:
                    candidates = select_trades(
                        signals=signals,
                        balance=balance,
                        open_market_ids=open_market_ids,
                        max_trades=max_per_cycle,
                        max_positions=max_concurrent,
                        current_position_count=len(open_positions),
                        max_total_exposure_pct=max_exposure,
                        max_position_pct=max_pos_pct,
                    )

                    for candidate in candidates:
                        sig = candidate.signal
                        order = await execute_paper_order(
                            market_id=sig.market_id,
                            outcome=sig.outcome,
                            price=sig.p_market,
                            size=candidate.size,
                            slippage_bps=slippage_bps,
                            fee_pct=fee_pct,
                            market_depth_threshold=depth_threshold,
                        )

                        trade = OpenTrade(
                            trade_id=order.order_id,
                            market_id=sig.market_id,
                            question=sig.question,
                            outcome=sig.outcome,
                            entry_price=order.filled_price,
                            size=order.filled_size,
                            ev=sig.ev,
                            fee=order.fee,
                            opened_at=time.time(),
                        )
                        await state.save_trade(trade)

                        notif = TradeNotification(
                            market_id=trade.market_id,
                            question=trade.question,
                            outcome=trade.outcome,
                            entry_price=trade.entry_price,
                            exit_price=None,
                            size=trade.size,
                            ev=trade.ev,
                            fee=trade.fee,
                            pnl=None,
                            pnl_pct=None,
                            duration_minutes=None,
                            balance=balance,
                        )
                        await send_open(notif)
                        log.info(
                            "position_opened",
                            trade_id=trade.trade_id,
                            market_id=trade.market_id,
                            ev=round(sig.ev, 4),
                            size=trade.size,
                            fill_status=order.status,
                        )
            else:
                log.info("max_positions_reached", count=len(open_positions), max=max_concurrent)

            # ── STEP 3: Periodic summary ─────────────────────────────────────────
            if cycle % summary_every == 0:
                balance = await state.get_balance()
                open_positions = await state.get_open_positions()
                stats = await tracker.snapshot()
                await send_summary(
                    balance=balance,
                    initial_balance=initial_balance,
                    open_count=len(open_positions),
                    stats=stats,
                )

        except Exception:
            log.exception("runner_cycle_error")

        # ── Sleep until next cycle ────────────────────────────────────────────
        elapsed = time.time() - cycle_start
        await asyncio.sleep(max(0.0, poll_interval - elapsed))


if __name__ == "__main__":
    asyncio.run(run())
