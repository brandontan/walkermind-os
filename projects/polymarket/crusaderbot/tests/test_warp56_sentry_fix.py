"""Regression tests for WARP-56 — Sentry P0 fixes (issue #1257).

Covers:
1. _coerce_jsonb in signal_scan_job — must narrow to fallback type so JSON
   scalars (`'"balanced"'`, `'1'`) and lists never leak into
   strategy.initialize() and trigger ValueError.
2. _log in domain/risk/gate — must catch ForeignKeyViolationError silently
   so /admin/dry-run with a synthetic user_id stops paging Sentry.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import asyncpg
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
# Bug 3: _log catches ForeignKeyViolationError silently
# --------------------------------------------------------------------------


def _fk_violation():
    """Construct an asyncpg ForeignKeyViolationError without a real DB."""
    return asyncpg.exceptions.ForeignKeyViolationError(
        "insert or update on table \"risk_log\" violates foreign key constraint "
        "\"risk_log_user_id_fkey\""
    )


@pytest.mark.asyncio
async def test_log_swallows_foreign_key_violation_for_synthetic_user(caplog):
    """dry-run uses a fake user_id — FK violation must not surface to Sentry."""
    fake_user = UUID("00000000-0000-0000-0000-000000000001")

    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock(side_effect=_fk_violation())
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch.object(gate_mod, "get_pool", return_value=mock_pool):
        # Must not raise — the FK violation is expected for synthetic users.
        await gate_mod._log(fake_user, "0xmarket", 0, True, "ok")

    # ERROR records would trigger Sentry's logging breadcrumb integration.
    # Confirm no ERROR was emitted (only DEBUG).
    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert error_records == [], (
        f"FK violation must not log at ERROR (Sentry-tracked). Got: "
        f"{[r.getMessage() for r in error_records]}"
    )


@pytest.mark.asyncio
async def test_log_still_errors_on_unexpected_exception(caplog):
    """Non-FK exceptions must still log at ERROR so real bugs reach Sentry."""
    fake_user = UUID("11111111-1111-1111-1111-111111111111")

    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock(side_effect=RuntimeError("unexpected DB error"))
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch.object(gate_mod, "get_pool", return_value=mock_pool):
        await gate_mod._log(fake_user, "0xmarket", 0, True, "ok")

    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert any("risk_log insert failed" in r.getMessage() for r in error_records)


@pytest.mark.asyncio
async def test_log_succeeds_on_valid_insert():
    """Sanity: a successful INSERT path completes without exception."""
    real_user = UUID("22222222-2222-2222-2222-222222222222")

    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock(return_value="INSERT 0 1")
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch.object(gate_mod, "get_pool", return_value=mock_pool):
        await gate_mod._log(real_user, "0xmarket", 7, False, "max_concurrent_trades")

    mock_conn.execute.assert_awaited_once()
