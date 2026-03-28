"""
Telegram notification service — non-blocking, never raises.
"""

import os
import structlog
import aiohttp
from dataclasses import dataclass

log = structlog.get_logger()


@dataclass
class TradeNotification:
    market_id: str
    question: str
    outcome: str
    entry_price: float
    exit_price: float | None
    size: float
    ev: float
    pnl: float | None
    pnl_pct: float | None
    duration_minutes: float | None
    balance: float


async def _send(text: str) -> None:
    """Send a message to Telegram. Logs warning on failure, never raises."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        log.warning("telegram_not_configured")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    timeout = aiohttp.ClientTimeout(total=5)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    log.warning("telegram_bad_status", status=resp.status)
    except Exception as exc:
        log.warning("telegram_send_failed", error=str(exc))


async def send_open(t: TradeNotification) -> None:
    """Send trade OPEN notification."""
    text = (
        "\U0001f7e2 <b>OPEN</b>\n\n"
        f"{t.question} ({t.outcome})\n"
        f"Entry: {t.entry_price:.4f}\n"
        f"Size: ${t.size:.2f}\n"
        f"EV: +{t.ev:.4f}\n\n"
        f"Bal: ${t.balance:.2f}"
    )
    await _send(text)


async def send_closed(t: TradeNotification) -> None:
    """Send trade CLOSED notification with PnL and duration."""
    pnl_str = f"${t.pnl:+.2f} ({t.pnl_pct:+.1f}%)" if t.pnl is not None else "N/A"
    dur_str = f"{t.duration_minutes:.1f} min" if t.duration_minutes is not None else "N/A"
    text = (
        "\U0001f535 <b>CLOSED</b>\n\n"
        f"{t.question} ({t.outcome})\n\n"
        f"{t.entry_price:.4f} \u2192 {t.exit_price:.4f}\n"
        f"PnL: {pnl_str}\n\n"
        f"Duration: {dur_str}\n"
        f"Bal: ${t.balance:.2f}"
    )
    await _send(text)
