"""Source-level regression pins for the mode/status display fixes.

WARP•R00T audit Theme #1: the Telegram MVP surfaces read trading-mode and
auto-trade status from DB columns that do not exist (`live_mode_enabled`,
`live_trading_enabled`, `auto_trade_enabled`), so they always rendered PAPER /
STOPPED regardless of reality. These pins fail closed if any phantom key is
reintroduced and assert the canonical keys remain wired.

No DB, no network — pure source inspection, resolved relative to this file so
the tests run from the repo root or from within the project dir.
"""
from __future__ import annotations

import pathlib

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_MVP = _ROOT / "bot/handlers/mvp"

# Phantom DB keys that must never appear in any MVP handler again.
_PHANTOM_KEYS = ("live_mode_enabled", "live_trading_enabled", "auto_trade_enabled")


def _src(rel: str) -> str:
    return (_MVP / rel).read_text(encoding="utf-8")


def test_no_phantom_keys_in_mvp_handlers() -> None:
    for rel in ("settings.py", "autotrade.py", "onboarding.py"):
        text = _src(rel)
        for key in _PHANTOM_KEYS:
            assert key not in text, f"phantom key {key!r} reintroduced in mvp/{rel}"


def test_settings_reads_trading_mode_from_settings_row() -> None:
    text = _src("settings.py")
    assert 'settings.get("trading_mode")' in text, (
        "mvp/settings.py must read trading_mode from the user_settings row"
    )


def test_autotrade_reads_canonical_auto_trade_on() -> None:
    text = _src("autotrade.py")
    assert 'u.get("auto_trade_on")' in text, (
        "mvp/autotrade.py must read the canonical users.auto_trade_on column"
    )


def test_onboarding_reads_canonical_auto_trade_on() -> None:
    text = _src("onboarding.py")
    assert 'u.get("auto_trade_on")' in text, (
        "mvp/onboarding.py must read the canonical users.auto_trade_on column"
    )


def test_fetch_settings_selects_trading_mode() -> None:
    text = (_MVP / "_users.py").read_text(encoding="utf-8")
    assert "trading_mode" in text, (
        "_users.fetch_settings must SELECT trading_mode so the settings UI can show it"
    )
