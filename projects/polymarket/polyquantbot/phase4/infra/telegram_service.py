"""Telegram service — pure STATE_UPDATED subscriber in Phase 4."""
from __future__ import annotations

import structlog
import httpx

from ..engine.event_bus import EventEnvelope

log = structlog.get_logger()


class TelegramService:
    """Sends Telegram notifications as a pure event subscriber."""

    def __init__(self, token: str, chat_id: str) -> None:
        """Initialise with bot token and chat ID."""
        self._token = token
        self._chat_id = chat_id
        self._base = f"https://api.telegram.org/bot{token}"

    async def handle_state_updated(self, envelope: EventEnvelope) -> None:
        """Route STATE_UPDATED events to the correct notification method."""
        action = envelope.payload.get("action", "")
        if action == "TRADE_OPENED":
            await self._send_trade_opened(envelope)
        elif action == "TRADE_CLOSED":
            await self._send_trade_closed(envelope)
        elif action == "SUMMARY":
            await self._send_summary(envelope)
        elif action == "CIRCUIT_OPEN":
            await self._send_circuit_open(envelope)

    async def _send_trade_opened(self, envelope: EventEnvelope) -> None:
        """Notify on new trade open."""
        t = envelope.payload.get("trade", {})
        balance = envelope.payload.get("balance", 0.0)
        msg = (
            f"\U0001f7e2 *TRADE OPENED*\n"
            f"Market: {t.get('question', t.get('market_id', 'N/A'))[:60]}\n"
            f"Entry: {t.get('entry_price', 0):.4f}\n"
            f"Size: ${t.get('size', 0):.2f}\n"
            f"EV: {t.get('ev', 0):.4f}\n"
            f"Fee: ${t.get('fee', 0):.4f}\n"
            f"Balance: ${balance:.2f}"
        )
        await self._send(msg)

    async def _send_trade_closed(self, envelope: EventEnvelope) -> None:
        """Notify on trade close."""
        t = envelope.payload.get("trade", {})
        pnl = t.get("pnl", 0.0)
        exit_price = t.get("exit_price")
        exit_str = f"{exit_price:.4f}" if exit_price is not None else "N/A"
        emoji = "\U0001f7e2" if pnl >= 0 else "\U0001f534"
        msg = (
            f"{emoji} *TRADE CLOSED*\n"
            f"Market: {t.get('question', t.get('market_id', 'N/A'))[:60]}\n"
            f"Exit: {exit_str} | Reason: {t.get('reason', 'N/A')}\n"
            f"PnL: ${pnl:+.4f}"
        )
        await self._send(msg)

    async def _send_summary(self, envelope: EventEnvelope) -> None:
        """Send periodic performance summary."""
        balance = envelope.payload.get("balance", 0.0)
        initial = envelope.payload.get("initial_balance", 1000.0)
        open_count = envelope.payload.get("open_count", 0)
        stats = envelope.payload.get("stats", {})
        total_return = ((balance - initial) / initial) * 100
        msg = (
            f"\U0001f4ca *SUMMARY*\n"
            f"Balance: ${balance:.2f} ({total_return:+.2f}%)\n"
            f"Open positions: {open_count}\n"
            f"Win rate: {stats.get('win_rate', 0):.1%}\n"
            f"Total PnL: ${stats.get('total_pnl', 0):+.4f}"
        )
        await self._send(msg)

    async def _send_circuit_open(self, envelope: EventEnvelope) -> None:
        """Alert when circuit breaker trips."""
        reason = envelope.payload.get("reason", "unknown")
        cooldown = envelope.payload.get("cooldown_seconds", 120)
        msg = (
            f"\u26a0\ufe0f *CIRCUIT BREAKER OPEN*\n"
            f"Reason: {reason}\n"
            f"Cooldown: {cooldown}s"
        )
        await self._send(msg)

    async def _send(self, text: str) -> None:
        """Send message to Telegram. Never raises."""
        if not self._token or not self._chat_id:
            return
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    f"{self._base}/sendMessage",
                    json={
                        "chat_id": self._chat_id,
                        "text": text,
                        "parse_mode": "Markdown",
                    },
                )
        except Exception as exc:
            log.warning("telegram_send_failed", error=str(exc))
