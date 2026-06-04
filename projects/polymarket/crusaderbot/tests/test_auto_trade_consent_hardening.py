"""WARP-75 — auto-trade consent & coverage hardening (F1 + F3).

F1 (consent integrity): onboarding must NEVER enable autonomous trading as a
side effect. Both onboarding completion paths (``start.skip_deposit_cb`` and the
concierge wizard ``onboarding._launch_cb``) configure the chosen preset but leave
``auto_trade_on`` at its default FALSE — the user must make a deliberate explicit
act (Dashboard "Auto Mode" toggle) to start the loop. Real capital additionally
requires the typed-CONFIRM live activation gate (unchanged).

F3 (coverage): an opted-in user must never be SILENTLY skipped. Two previously
silent gaps now emit structured warnings: a non-NULL preset that maps to no
strategy (deny-by-default), and a user who opted in but is missing the
``signal_following`` enrolment row the scan joins on.

All hermetic — no DB, no broker, no network.
"""
from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from projects.polymarket.crusaderbot.bot.handlers import onboarding as onboarding_mod
from projects.polymarket.crusaderbot.bot.handlers import start as start_mod
from projects.polymarket.crusaderbot.services.signal_scan import signal_scan_job as ssj


# ===========================================================================
# F1 — onboarding never side-effect-enables auto_trade_on
# ===========================================================================


def test_skip_deposit_cb_source_does_not_enable_auto_trade():
    """Consent regression guard: skip_deposit_cb must not call set_auto_trade."""
    src = inspect.getsource(start_mod.skip_deposit_cb)
    assert "set_auto_trade(" not in src, (
        "WARP-75 F1: onboarding skip_deposit_cb must not enable auto_trade_on "
        "as a side effect — explicit user opt-in only"
    )


def test_launch_cb_source_does_not_enable_auto_trade():
    """Consent regression guard: the concierge wizard launch must not auto-enable."""
    src = inspect.getsource(onboarding_mod._launch_cb)
    assert "set_auto_trade(" not in src, (
        "WARP-75 F1: onboarding _launch_cb must not enable auto_trade_on "
        "as a side effect — explicit user opt-in only"
    )


def test_skip_deposit_cb_configures_preset_but_leaves_autotrade_off(monkeypatch):
    """Behavioural: skip_deposit_cb applies the preset config and completes
    onboarding, WITHOUT enabling auto_trade_on (the module no longer imports
    set_auto_trade, so no enable path exists)."""
    uid = uuid4()
    preset = SimpleNamespace(
        key="close_sweep", strategies=["late_entry_v3"],
        tp_pct=0.9, sl_pct=0.4, max_position_pct=0.05,
    )
    update_settings = AsyncMock()
    set_onboarding_complete = AsyncMock()
    show_dashboard = AsyncMock()

    monkeypatch.setattr(start_mod, "upsert_user", AsyncMock(return_value={"id": uid}))
    monkeypatch.setattr(start_mod, "get_preset", lambda k: preset)
    monkeypatch.setattr(start_mod, "get_settings_for",
                        AsyncMock(return_value={"risk_profile": "balanced"}))
    monkeypatch.setattr(start_mod, "capital_for_risk_profile", lambda rp: 0.40)
    monkeypatch.setattr(start_mod, "update_settings", update_settings)
    monkeypatch.setattr(start_mod, "set_onboarding_complete", set_onboarding_complete)
    # show_dashboard_for_cb is imported lazily inside the handler.
    import projects.polymarket.crusaderbot.bot.handlers.dashboard as dash_mod
    monkeypatch.setattr(dash_mod, "show_dashboard_for_cb", show_dashboard)

    # The module must not even have a set_auto_trade symbol to call.
    assert not hasattr(start_mod, "set_auto_trade")

    q = SimpleNamespace(answer=AsyncMock())
    update = SimpleNamespace(
        callback_query=q,
        effective_user=SimpleNamespace(id=42, username="tester"),
    )
    ctx = SimpleNamespace(user_data={"onboard_preset_key": "close_sweep"})

    asyncio.run(start_mod.skip_deposit_cb(update, ctx))

    # preset config was applied ...
    update_settings.assert_awaited_once()
    assert update_settings.await_args.kwargs.get("active_preset") == "close_sweep"
    # ... and onboarding completed, but no auto-trade enable happened.
    set_onboarding_complete.assert_awaited_once()
    show_dashboard.assert_awaited_once()


# ===========================================================================
# F3 — opted-in-but-unenrolled coverage warning
# ===========================================================================


class _FetchvalConn:
    def __init__(self, value: int | Exception) -> None:
        self._value = value

    async def fetchval(self, sql: str, *args: Any) -> Any:
        if isinstance(self._value, Exception):
            raise self._value
        return self._value


def _patch_pool(monkeypatch, value: int | Exception) -> None:
    conn = _FetchvalConn(value)
    acm = MagicMock()
    acm.__aenter__ = AsyncMock(return_value=conn)
    acm.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire.return_value = acm
    monkeypatch.setattr(ssj, "get_pool", lambda: pool)


def test_count_optedin_unenrolled_returns_query_value(monkeypatch):
    _patch_pool(monkeypatch, 3)
    assert asyncio.run(ssj._count_optedin_unenrolled()) == 3


def test_count_optedin_unenrolled_zero(monkeypatch):
    _patch_pool(monkeypatch, 0)
    assert asyncio.run(ssj._count_optedin_unenrolled()) == 0


def test_count_optedin_unenrolled_failsoft_returns_negative_one(monkeypatch):
    """A query failure must never break the scan — returns -1 and logs."""
    _patch_pool(monkeypatch, RuntimeError("db down"))
    assert asyncio.run(ssj._count_optedin_unenrolled()) == -1


# ===========================================================================
# F3 — unmapped-preset guard predicate
# ===========================================================================


@pytest.mark.parametrize(
    "preset",
    ["candle_auto", "close_sweep", "safe_close", "flip_hunter",
     "weather_monitor", "playbook"],
)
def test_valid_presets_map_to_a_strategy(preset):
    """Every shipping preset resolves to at least one strategy — the guard must
    NOT skip these."""
    assert ssj._PRESET_ALLOWED.get(preset), f"{preset} must map to a strategy"


@pytest.mark.parametrize("preset", ["contrarian", "full_auto", "whale_mirror", ""])
def test_unmapped_presets_are_falsy(preset):
    """Legacy / renamed / typo presets map to nothing → the F3 guard logs and
    skips instead of firing nothing silently."""
    assert not ssj._PRESET_ALLOWED.get(preset)
