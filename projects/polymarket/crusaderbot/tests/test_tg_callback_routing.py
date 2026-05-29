"""WARP•R00T audit Lane 4 — Telegram callback routing (B6).

MVP `_dashboard_cb` / `_settings_cb` are attached FIRST (group 0), so they win
over the legacy `dashboard_nav_cb` / `settings_callback` for `^dashboard:` /
`^settings:`. They only handled their own screens and silently bounced every
other sub-route to the MVP home — so `settings:tpsl`, `settings:wallet`,
`settings:health`, `settings:admin`, `dashboard:insights`, `dashboard:portfolio`
were dead. Now MVP keeps the screens it owns and delegates the rest to legacy.

Hermetic: no DB/network — delegate targets + MVP screens are monkeypatched.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from projects.polymarket.crusaderbot.bot.handlers.mvp import dashboard as mvp_dash
from projects.polymarket.crusaderbot.bot.handlers.mvp import settings as mvp_set
from projects.polymarket.crusaderbot.bot.handlers import dashboard as legacy_dash
from projects.polymarket.crusaderbot.bot.handlers import settings as legacy_set


def _upd(data: str) -> MagicMock:
    q = MagicMock()
    q.data = data
    u = MagicMock()
    u.callback_query = q
    return u


# ── dashboard ────────────────────────────────────────────────────────────────

def test_dashboard_main_shows_mvp_home(monkeypatch):
    seen = {}
    async def fake_show(update, ctx): seen["home"] = True
    async def fake_nav(update, ctx): seen["nav"] = True
    monkeypatch.setattr(mvp_dash, "show_dashboard", fake_show)
    monkeypatch.setattr(legacy_dash, "dashboard_nav_cb", fake_nav)
    asyncio.run(mvp_dash._dashboard_cb(_upd("dashboard:main"), MagicMock()))
    assert seen.get("home") and not seen.get("nav")


def test_dashboard_insights_delegates_to_legacy(monkeypatch):
    seen = {}
    async def fake_show(update, ctx): seen["home"] = True
    async def fake_nav(update, ctx): seen["nav"] = True
    monkeypatch.setattr(mvp_dash, "show_dashboard", fake_show)
    monkeypatch.setattr(legacy_dash, "dashboard_nav_cb", fake_nav)
    asyncio.run(mvp_dash._dashboard_cb(_upd("dashboard:insights"), MagicMock()))
    assert seen.get("nav") and not seen.get("home")


def test_dashboard_portfolio_delegates_to_legacy(monkeypatch):
    seen = {}
    async def fake_nav(update, ctx): seen["nav"] = True
    monkeypatch.setattr(legacy_dash, "dashboard_nav_cb", fake_nav)
    asyncio.run(mvp_dash._dashboard_cb(_upd("dashboard:portfolio"), MagicMock()))
    assert seen.get("nav")


# ── settings ─────────────────────────────────────────────────────────────────

def test_settings_tpsl_delegates_to_legacy(monkeypatch):
    seen = {}
    async def fake_cb(update, ctx): seen["legacy"] = True
    monkeypatch.setattr(legacy_set, "settings_callback", fake_cb)
    asyncio.run(mvp_set._settings_cb(_upd("settings:tpsl"), MagicMock()))
    assert seen.get("legacy")


def test_settings_wallet_delegates_to_legacy(monkeypatch):
    seen = {}
    async def fake_cb(update, ctx): seen["legacy"] = True
    monkeypatch.setattr(legacy_set, "settings_callback", fake_cb)
    asyncio.run(mvp_set._settings_cb(_upd("settings:wallet"), MagicMock()))
    assert seen.get("legacy")


def test_settings_risk_stays_on_mvp(monkeypatch):
    """MVP owns 'risk' — it must NOT delegate to legacy."""
    seen = {}
    async def fake_risk(update, ctx): seen["mvp_risk"] = True
    async def fake_cb(update, ctx): seen["legacy"] = True
    monkeypatch.setattr(mvp_set, "show_risk", fake_risk)
    monkeypatch.setattr(legacy_set, "settings_callback", fake_cb)
    asyncio.run(mvp_set._settings_cb(_upd("settings:risk"), MagicMock()))
    assert seen.get("mvp_risk") and not seen.get("legacy")
