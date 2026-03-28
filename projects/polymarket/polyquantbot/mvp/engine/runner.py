"""
Main async loop: scan → signal → execute → monitor → close.
Run with: python -m engine.runner
"""

import asyncio
import os
import time
import random
import structlog
import yaml
from dotenv import load_dotenv

from infra.polymarket_client import fetch_markets
from infra.telegram_service import TradeNotification, send_open, send_closed
from core.signal_model import BayesianSignalModel
from core.risk_manager import get_position_size
from core.execution.paper_executor import execute_paper_order
from engine.state_manager import StateManager, OpenTrade

load_dotenv()
log = structlog.get_logger()


# ── Config loader ─────────────────────────────────────────────────────────────────────────────

def load_config(path: str = "config.yaml") -> dict:
    """Load YAML config from the given path."""
    with open(path) as f:
        return yaml.safe_load(f)


# ── Exit decision ────────────────────────────────────────────────────────────────────────

def should_exit(
    trade: OpenTrade,
    current_price: float,
    tp_pct: float,
    sl_pct: float,
    timeout_minutes: float,
) -> tuple[bool, str, float]:
    """
    Evaluate exit conditions.
    Returns (should_exit, reason, exit_price).
    """
    elapsed_minutes = (time.time() - trade.opened_at) / 60.0
    gain_pct = (current_price - trade.entry_price) / trade.entry_price

    if gain_pct >= tp_pct:
        return True, "TP", current_price
    if gain_pct <= -sl_pct:
        return True, "SL", current_price
    if elapsed_minutes >= timeout_minutes:
        return True, "TIMEOUT", current_price
    return False, "", current_price


# ── Main loop ─────────────────────────────────────────────────────────────────────────────

async def run() -> None:
    """Start the polyquantbot MVP main loop."""
    cfg = load_config()

    trading_cfg = cfg["trading"]
    paper_cfg = cfg["paper"]
    exit_cfg = cfg.get("exit", {})

    poll_interval: int = trading_cfg["poll_interval_seconds"]
    min_ev: float = trading_cfg["min_ev_threshold"]
    max_pos_pct: float = trading_cfg["max_position_pct"]
    initial_balance: float = paper_cfg["initial_balance"]
    slippage_bps: int = paper_cfg["slippage_bps"]
    tp_pct: float = exit_cfg.get("take_profit_pct", 0.10)
    sl_pct: float = exit_cfg.get("stop_loss_pct", 0.05)
    timeout_min: float = exit_cfg.get("timeout_minutes", 30)

    db_path: str = os.getenv("DATABASE_PATH", "./data/mvp.db")

    state = StateManager(db_path=db_path, initial_balance=initial_balance)
    await state.init()

    model = BayesianSignalModel(min_ev_threshold=min_ev)
    cooldown = False   # skip 1 cycle after close

    log.info("runner_started", poll_interval=poll_interval)

    while True:
        cycle_start = time.time()

        try:
            # ── 1. Check open trade ─────────────────────────────────────────────────────
            open_trade = await state.get_open_trade()

            if open_trade:
                # Simulate current market price drift
                drift = random.uniform(-0.03, 0.05)
                current_price = max(0.01, min(0.99, open_trade.entry_price + drift))

                do_exit, reason, exit_price = should_exit(
                    open_trade, current_price, tp_pct, sl_pct, timeout_min
                )

                if do_exit:
                    pnl = (exit_price - open_trade.entry_price) * open_trade.size
                    new_balance = await state.get_balance() + pnl
                    await state.close_trade(open_trade.trade_id, exit_price, pnl)
                    await state.update_balance(new_balance)

                    duration = (time.time() - open_trade.opened_at) / 60.0
                    pnl_pct = (pnl / (open_trade.entry_price * open_trade.size)) * 100

                    notif = TradeNotification(
                        market_id=open_trade.market_id,
                        question=open_trade.question,
                        outcome=open_trade.outcome,
                        entry_price=open_trade.entry_price,
                        exit_price=exit_price,
                        size=open_trade.size,
                        ev=open_trade.ev,
                        pnl=pnl,
                        pnl_pct=pnl_pct,
                        duration_minutes=duration,
                        balance=new_balance,
                    )
                    await send_closed(notif)
                    log.info(
                        "trade_closed",
                        reason=reason,
                        pnl=round(pnl, 2),
                        balance=round(new_balance, 2),
                    )
                    cooldown = True   # skip next entry cycle

            else:
                # ── 2. No open trade — scan for new signal ───────────────────────────
                if cooldown:
                    log.info("cooldown_cycle_skipped")
                    cooldown = False
                else:
                    markets = await fetch_markets(limit=10)

                    signals = []
                    for m in markets:
                        sig = model.generate_signal(m)
                        if sig:
                            signals.append(sig)

                    best = model.select_best(signals)

                    if best:
                        balance = await state.get_balance()
                        size = get_position_size(
                            balance=balance,
                            ev=best.ev,
                            p_model=best.p_model,
                            p_market=best.p_market,
                            max_position_pct=max_pos_pct,
                        )

                        if size > 0:
                            order = await execute_paper_order(
                                market_id=best.market_id,
                                outcome=best.outcome,
                                price=best.p_market,
                                size=size,
                                slippage_bps=slippage_bps,
                            )

                            trade = OpenTrade(
                                trade_id=order.order_id,
                                market_id=best.market_id,
                                question=best.question,
                                outcome=best.outcome,
                                entry_price=order.filled_price,
                                size=order.filled_size,
                                ev=best.ev,
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
                                pnl=None,
                                pnl_pct=None,
                                duration_minutes=None,
                                balance=balance,
                            )
                            await send_open(notif)
                            log.info(
                                "trade_opened",
                                market_id=trade.market_id,
                                ev=round(best.ev, 4),
                                size=trade.size,
                            )
                        else:
                            log.warning("position_size_zero", balance=balance)
                    else:
                        log.info("no_signal_found", markets_scanned=len(markets))

        except Exception:
            log.exception("runner_cycle_error")

        # ── Sleep until next cycle ────────────────────────────────────────────────────────
        elapsed = time.time() - cycle_start
        sleep_for = max(0.0, poll_interval - elapsed)
        await asyncio.sleep(sleep_for)


if __name__ == "__main__":
    asyncio.run(run())
