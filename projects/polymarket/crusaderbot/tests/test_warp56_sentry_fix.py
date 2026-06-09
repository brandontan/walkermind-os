"""Regression tests for WARP-56 — Sentry P0 fixes (issue #1257).

Covers:
1. _coerce_jsonb in signal_scan_job — must narrow to fallback type so JSON
   scalars (`'"balanced"'`, `'1'`) and lists never leak into
   strategy.initialize() and trigger ValueError.
2. _log in domain/risk/gate — must catch ForeignKeyViolationError silently
   so /admin/dry-run with a synthetic user_id stops paging Sentry.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from projects.polymarket.crusaderbot.domain.risk import gate as gate_mod
from projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job import (
    _coerce_jsonb,
)


# --------------------------------------------------------------------------
# Bug 2: _coerce_jsonb narrows return to fallback type
# --------------------------------------------------------------------------


def test_coerce_jsonb_none_returns_default_dict():
    assert _coerce_jsonb(None, {}) == {}


def test_coerce_jsonb_none_returns_default_list():
    assert _coerce_jsonb(None, []) == []


def test_coerce_jsonb_dict_passes_through():
    assert _coerce_jsonb({"momentum": {"drop_pct": 0.05}}, {}) == {
        "momentum": {"drop_pct": 0.05}
    }


def test_coerce_jsonb_list_passes_through():
    assert _coerce_jsonb(["a", "b"], []) == ["a", "b"]


def test_coerce_jsonb_json_string_scalar_returns_default():
    """asyncpg returns JSONB scalar as quoted string — must NOT leak as str."""
    # '"balanced"' parses to the string "balanced" — not a dict, so default.
    assert _coerce_jsonb('"balanced"', {}) == {}


def test_coerce_jsonb_json_number_returns_default():
    assert _coerce_jsonb("1", {}) == {}


def test_coerce_jsonb_invalid_json_returns_default():
    assert _coerce_jsonb("not json at all", {}) == {}


def test_coerce_jsonb_empty_dict_json_returns_empty_dict():
    assert _coerce_jsonb("{}", {}) == {}


def test_coerce_jsonb_dict_json_returns_dict():
    assert _coerce_jsonb('{"momentum": {"drop_pct": 0.05}}', {}) == {
        "momentum": {"drop_pct": 0.05}
    }


def test_coerce_jsonb_list_json_with_dict_fallback_returns_default():
    """Caller expects dict; parsed list is wrong shape → default."""
    assert _coerce_jsonb('["a", "b"]', {}) == {}


def test_coerce_jsonb_dict_json_with_list_fallback_returns_default():
    """Caller expects list; parsed dict is wrong shape → default."""
    assert _coerce_jsonb('{"a": 1}', []) == []


def test_coerce_jsonb_dict_get_does_not_raise_after_string_input():
    """The full failure mode: even when DB returns a JSON scalar string,
    downstream .get() must work because we always return a dict."""
    result = _coerce_jsonb('"balanced"', {})
    # If this returned a string, .get(...) would AttributeError. The whole
    # point of the narrowing is that this call is now safe.
    assert result.get("momentum", {}) == {}


# --------------------------------------------------------------------------
# Bug 3 (WARP-82): _log no longer writes to the DB — pure stdout/Sentry sink
# (risk_log is dropped). It must never acquire the pool / execute SQL / raise.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_does_no_db_write_and_never_raises():
    """_log must never acquire the pool (risk_log dropped) and never raise —
    for both a rejection and an approval."""
    mock_pool = MagicMock()
    with patch.object(gate_mod, "get_pool", return_value=mock_pool):
        await gate_mod._log(
            UUID("22222222-2222-2222-2222-222222222222"),
            "0xmarket", 7, False, "max_concurrent_trades",
        )
        await gate_mod._log(
            UUID("22222222-2222-2222-2222-222222222222"),
            "0xmarket", 1, True, "ok",
        )
    mock_pool.acquire.assert_not_called()


@pytest.mark.asyncio
async def test_log_rejection_warns_and_approval_infos(caplog):
    """Rejection → WARNING stdout (+ Sentry separately); approval → INFO.
    Neither happy path logs at ERROR (which would page Sentry's breadcrumb)."""
    caplog.set_level(logging.INFO)
    await gate_mod._log(
        UUID("11111111-1111-1111-1111-111111111111"),
        "0xmarket", 7, False, "max_concurrent_trades",
    )
    await gate_mod._log(
        UUID("11111111-1111-1111-1111-111111111111"),
        "0xmarket", 1, True, "ok",
    )
    msgs = [(r.levelname, r.getMessage()) for r in caplog.records]
    assert any(lvl == "WARNING" and "risk_event approved=False" in m for lvl, m in msgs)
    assert any(lvl == "INFO" and "risk_event approved=True" in m for lvl, m in msgs)
    assert not [r for r in caplog.records if r.levelname == "ERROR"]
