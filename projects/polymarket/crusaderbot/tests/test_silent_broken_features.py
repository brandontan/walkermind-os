"""Regression tests for WARP•R00T audit Theme #2 — silently broken features.

Two backend bugs where a real failure was swallowed and the feature died with
no user signal:

1. copy-trade monitor built `signal_ts` with a naive `datetime.utcnow()`; risk
   gate step 9 does `datetime.now(timezone.utc) - signal_ts`, which raised
   TypeError (naive vs aware). The monitor caught it and returned, so every
   copy-trade candidate silently failed at the gate.
2. withdrawal approve/reject notifications passed `parse_mode=` to
   `notify_user_by_telegram_id`, which did not accept it -> TypeError caught
   silently -> users never received the outcome notification.
"""
from __future__ import annotations

import asyncio
import pathlib
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

_ROOT = pathlib.Path(__file__).resolve().parent.parent


# ── Bug 1: copy-trade monitor signal_ts must be tz-aware ──────────────────────

def test_copy_trade_monitor_signal_ts_is_tz_aware_source() -> None:
    src = (_ROOT / "services/copy_trade/monitor.py").read_text(encoding="utf-8")
    assert "datetime.utcnow()" not in src, (
        "monitor must not build a naive signal_ts — gate step 9 needs tz-aware"
    )
    assert "datetime.now(timezone.utc)" in src


def test_gate_step9_rejects_naive_signal_ts_contract() -> None:
    """Documents the contract the bug violated: aware-minus-naive raises."""
    aware_now = datetime.now(timezone.utc)
    naive_ts = datetime.utcnow()  # noqa: DTZ003 — intentionally naive for the check
    try:
        _ = (aware_now - naive_ts).total_seconds()
        raised = False
    except TypeError:
        raised = True
    assert raised, "aware-minus-naive must raise — confirms why tz-aware is required"


# ── Bug 2: notify_user_by_telegram_id must accept + forward parse_mode ────────

def test_notify_user_by_telegram_id_forwards_parse_mode() -> None:
    from projects.polymarket.crusaderbot import notifications as notif
    from telegram.constants import ParseMode

    with patch.object(notif, "send", new=AsyncMock(return_value=True)) as mock_send:
        asyncio.run(
            notif.notify_user_by_telegram_id(123, "hi", parse_mode=ParseMode.MARKDOWN_V2)
        )
    mock_send.assert_awaited_once()
    # parse_mode must reach send() so MarkdownV2-escaped withdrawal messages render
    assert mock_send.await_args.kwargs.get("parse_mode") == ParseMode.MARKDOWN_V2


def test_notify_user_by_telegram_id_defaults_html() -> None:
    from projects.polymarket.crusaderbot import notifications as notif
    from telegram.constants import ParseMode

    with patch.object(notif, "send", new=AsyncMock(return_value=True)) as mock_send:
        asyncio.run(notif.notify_user_by_telegram_id(123, "hi"))
    assert mock_send.await_args.kwargs.get("parse_mode") == ParseMode.HTML
