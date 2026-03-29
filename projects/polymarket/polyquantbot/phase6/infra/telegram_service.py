"""Telegram service — Phase 6.

Extended from Phase 5 with Phase 6 TRADE_OPENED fields:
  - decision_mode: TAKER | MAKER | HYBRID
  - expected_cost: cost fraction
"""
from __future__ import annotations

import os

import aiohttp
import structlog

from ..engine.event_bus import EventEnvelope

log = structlog.get_logger()


async def _send(text: str) -> None:
    """Send message to Telegram. Never raises."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        log.warning("telegram_not_configured")
        return
    timeout = aiohttp.ClientTimeout(total=5)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            ) as resp:
                if resp.status != 200:
                    log.warning("telegram_bad_status", status=resp.status)
    except Exception as exc:
        log.warning("telegram_send_failed", error=str(exc))


async def handle_state_updated(envelope: EventEnvelope) -> None:
    """Route STATE_UPDATED events to the correct notification method."""
    p = envelope.payload
    action = p.get("action", "")
    bound = log.bind(
        correlation_id=envelope.correlation_id,
        market_id=envelope.market_id,
        action=action,
    )
    try:
        if action == "TRADE_OPENED":
            mode_line = f"\nMode: {p.get('decision_mode', 'N/A')}"
            cost_line = (
                f"\nCost: {p['expected_cost']:.4f}"
                if p.get("expected_cost") is not None
                else ""
            )
            latency_line = (
                f"\nLatency: {p['execution_ms']}ms"
                if p.get("execution_ms")
                else ""
            )
            text = (
                "\U0001f7e2 <b>ORDER FILLED</b>\n\n"
                f"Strategy: {p.get('strategy', 'N/A')}\n"
                f"Market: {p['question']}\n"
                f"Outcome: {p['outcome']}\n"
                f"Size: ${p['size']:.2f}  Fee: ${p['fee']:.4f}\n"
                f"Price: {p['entry_price']:.4f}\n"
                f"EV: +{p['ev']:.4f}"
                f"{mode_line}{cost_line}{latency_line}\n\n"
                f"Bal: ${p['balance']:.2f}"
            )
            await _send(text)
            bound.info("telegram_open_sent")

        elif action == "TRADE_CLOSED":
            pnl = p.get("pnl", 0.0)
            pnl_pct = p.get("pnl_pct", 0.0)
            dur = p.get("duration_minutes", 0.0)
            text = (
                "\U0001f535 <b>CLOSED</b>\n\n"
                f"Strategy: {p.get('strategy', 'N/A')}\n"
                f"{p['question']} ({p['outcome']})\n\n"
                f"{p['entry_price']:.4f} \u2192 {p['exit_price']:.4f}\n"
                f"PnL: ${pnl:+.2f} ({pnl_pct:+.1f}%)\n"
                f"Reason: {p.get('reason', 'N/A')}\n"
                f"Duration: {dur:.1f} min\n"
                f"Bal: ${p['balance']:.2f}"
            )
            await _send(text)
            bound.info("telegram_closed_sent", pnl=pnl)

        elif action == "SUMMARY":
            stats = p.get("stats", {})
            text = (
                "\U0001f4ca <b>SUMMARY</b>\n\n"
                f"Balance: ${p['balance']:.2f}\n"
                f"PnL: ${p['total_pnl']:+.2f}\n"
                f"Open: {p['open_count']}\n\n"
                f"Trades: {stats.get('trade_count', 0)}\n"
                f"Winrate: {stats.get('winrate', 0.0):.1f}%\n"
                f"Avg PnL: ${stats.get('avg_pnl', 0.0):+.2f}\n"
                f"Fill Rate: {stats.get('fill_rate', 0.0):.1%}\n"
                f"Avg Slippage: {stats.get('avg_slippage_pct', 0.0):.3f}%"
            )
            await _send(text)
            bound.info("telegram_summary_sent")

        elif action == "STRATEGY_STATUS":
            lines = []
            for s in p.get("strategies", []):
                status = "on" if s["enabled"] else "off"
                lines.append(
                    f"{s['name'].capitalize()}: ${s['pnl']:+.0f} "
                    f"[{s['score']:.2f}] ({status})"
                )
            text = "\U0001f4ca <b>STRATEGY STATUS</b>\n\n" + "\n".join(lines)
            await _send(text)
            bound.info("telegram_strategy_status_sent")

        elif action == "CIRCUIT_OPEN":
            text = (
                "\u26a0\ufe0f <b>CIRCUIT BREAKER OPEN</b>\n\n"
                f"Reason: {p.get('reason', 'N/A')}\n"
                f"Cooldown: {p.get('cooldown_seconds', 0)}s"
            )
            await _send(text)
            bound.info("telegram_circuit_open_sent")

        else:
            bound.debug("state_updated_ignored", action=action)

    except Exception as exc:
        bound.warning("telegram_handler_error", error=str(exc))
