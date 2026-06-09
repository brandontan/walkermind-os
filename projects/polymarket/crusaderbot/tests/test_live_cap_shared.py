"""Shared live-cap validator + Telegram/WebTrader sync regression pins.

Covers the single source of truth (domain/activation/live_opt_in_gate.py) for
the per-user live capital cap, and pins that the Telegram /enable_live flow
writes the cap (the CRITICAL gap that previously left Telegram live users
stuck at gate step 15 `live_not_opted_in`).
"""
from __future__ import annotations

import inspect

import pytest

from projects.polymarket.crusaderbot.domain.activation.live_opt_in_gate import (
    LIVE_CAP_MAX_USDC,
    LIVE_CAP_MIN_USDC,
    LIVE_ENABLE_CONFIRM_PHRASE,
    LiveCapError,
    validate_live_capital_cap,
)


# ── validator: accepts ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("500", 500.0),
        ("1", 1.0),
        ("10000", 10_000.0),
        ("$1,000", 1_000.0),
        ("2_500", 2_500.0),
        (" 750.50 ", 750.50),
        (250, 250.0),
        (10_000.0, 10_000.0),
    ],
)
def test_validate_cap_accepts_valid(raw, expected):
    assert validate_live_capital_cap(raw) == pytest.approx(expected)


# ── validator: rejects ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    ["0", "-5", "10001", "100000", "", "abc", "$", "nan", "inf", None],
)
def test_validate_cap_rejects_invalid(raw):
    with pytest.raises(LiveCapError):
        validate_live_capital_cap(raw)


def test_cap_bounds_are_canonical():
    assert LIVE_CAP_MIN_USDC == 0.0
    assert LIVE_CAP_MAX_USDC == 10_000.0
    assert LIVE_ENABLE_CONFIRM_PHRASE == "ENABLE LIVE TRADING FOR MY ACCOUNT"


# ── Telegram flow: pins the cap actually gets written (CRITICAL fix) ───────────


def test_telegram_enable_live_writes_capital_cap():
    """The Telegram live_gate callback must write live_capital_cap_usdc
    alongside trading_mode='live'. Without it, gate step 15 rejects every
    live trade with live_not_opted_in (the bug this lane fixes)."""
    from projects.polymarket.crusaderbot.bot.handlers import live_gate

    src = inspect.getsource(live_gate.live_gate_callback)
    assert "trading_mode=\"live\"" in src
    assert "live_capital_cap_usdc=cap" in src
    # cap must be validated before write (defense-in-depth)
    assert "validate_live_capital_cap" in src


def test_telegram_has_cap_capture_step():
    """The /enable_live flow must have a dedicated cap-capture awaiting state
    so the user is prompted for a cap instead of defaulting to 0."""
    from projects.polymarket.crusaderbot.bot.handlers import live_gate

    assert hasattr(live_gate, "AWAITING_CAP")
    text_src = inspect.getsource(live_gate.text_input)
    assert "validate_live_capital_cap" in text_src
    assert "AWAITING_CAP" in text_src


def test_telegram_disable_live_reverts_to_paper():
    """/disable_live must flip back to paper and preserve the cap."""
    from projects.polymarket.crusaderbot.bot.handlers import live_gate

    assert hasattr(live_gate, "disable_live_command")
    src = inspect.getsource(live_gate.disable_live_command)
    assert "trading_mode=\"paper\"" in src
    # cap is NOT overwritten on disable (preserved for next enable)
    assert "live_capital_cap_usdc" not in src


def test_mode_change_event_returns_status():
    """write_mode_change_event must report success/failure (no silent swallow)
    so callers can surface a soft warning (CLAUDE.md: no silent failures)."""
    from projects.polymarket.crusaderbot.domain.activation import live_opt_in_gate

    src = inspect.getsource(live_opt_in_gate.write_mode_change_event)
    assert "-> bool" in src
    assert "return True" in src
    assert "return False" in src
