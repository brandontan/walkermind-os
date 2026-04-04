"""telegram.utils.telegram_sender — private-chat Telegram sender.

Routes bot notifications to the most recently captured Telegram user chat ID
(``/start`` DM) and avoids any fixed group-channel dependency.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Awaitable, Callable, Optional

import aiohttp
import structlog

log = structlog.get_logger(__name__)

USER_CHAT_ID: Optional[int] = None
_TOKEN_ENV_KEYS: tuple[str, ...] = ("TELEGRAM_TOKEN", "TELEGRAM_BOT_TOKEN")
_CHAT_ID_FILE: Path = Path(
    os.getenv(
        "TELEGRAM_USER_CHAT_ID_FILE",
        "projects/polymarket/polyquantbot/infra/telegram_user_chat_id.txt",
    )
)
_custom_sender: Optional[Callable[[int, str], Awaitable[None]]] = None


def _resolve_token() -> str:
    """Return Telegram bot token from environment."""
    for key in _TOKEN_ENV_KEYS:
        token = os.getenv(key, "").strip()
        if token:
            return token
    return ""


def set_sender(sender: Optional[Callable[[int, str], Awaitable[None]]]) -> None:
    """Inject optional async sender(chat_id, msg) implementation."""
    global _custom_sender  # noqa: PLW0603
    _custom_sender = sender


def set_user_chat_id(chat_id: Optional[int]) -> None:
    """Set and persist active private chat ID.

    Overwrite is intentionally allowed (single-user system behavior).
    """
    global USER_CHAT_ID  # noqa: PLW0603
    if chat_id is None:
        USER_CHAT_ID = None
        return

    USER_CHAT_ID = int(chat_id)
    try:
        _CHAT_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CHAT_ID_FILE.write_text(str(USER_CHAT_ID), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        log.warning("telegram_sender_chat_id_persist_failed", error=str(exc))


def load_user_chat_id() -> None:
    """Load persisted private chat ID if present."""
    global USER_CHAT_ID  # noqa: PLW0603
    if USER_CHAT_ID is not None:
        return
    try:
        raw = _CHAT_ID_FILE.read_text(encoding="utf-8").strip()
        if raw:
            USER_CHAT_ID = int(raw)
    except FileNotFoundError:
        return
    except Exception as exc:  # noqa: BLE001
        log.warning("telegram_sender_chat_id_load_failed", error=str(exc))


async def send(msg: str) -> None:
    """Send message to captured private chat.

    If no private chat ID is known, logs warning and returns without raising.
    """
    load_user_chat_id()
    if USER_CHAT_ID is None:
        log.warning("telegram_sender_no_user_chat_id")
        return

    if _custom_sender is not None:
        try:
            await _custom_sender(USER_CHAT_ID, msg)
        except Exception as exc:  # noqa: BLE001
            log.warning("telegram_sender_custom_send_failed", error=str(exc))
        return

    token = _resolve_token()
    if not token:
        log.warning("telegram_sender_missing_token")
        return

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": USER_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    log.warning(
                        "telegram_sender_non_200",
                        status=resp.status,
                        body=body[:200],
                    )
    except Exception as exc:  # noqa: BLE001
        log.warning("telegram_sender_request_failed", error=str(exc))
