"""PAPER-default invariant tests (F-LOW-2 — Lane 2 hardening).

Pins the rule: every new-user creation path writes
``user_settings.trading_mode='paper'`` EXPLICITLY in its INSERT, never
relying solely on the schema column default. This makes the invariant
greppable + breakable by a future migration only via a test failure.

Hermetic: no DB, no Telegram, no HTTP.
"""
from __future__ import annotations

import asyncio
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from projects.polymarket.crusaderbot import users as users_module
from projects.polymarket.crusaderbot.users import get_settings_for, upsert_user


def _ctx(return_value=None):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=return_value)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _make_pool(conn):
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_ctx(conn))
    return pool


# ---------------------------------------------------------------------------
# upsert_user — new-user branch must INSERT user_settings with 'paper'
# ---------------------------------------------------------------------------


def test_upsert_user_new_user_inserts_paper_settings():
    """New user → user_settings INSERT contains both columns AND 'paper'."""
    conn = MagicMock()
    queries: list[tuple[str, tuple]] = []

    async def _fetchrow(query, *args):
        # First call: SELECT users WHERE telegram → None (new user).
        # Second call: INSERT users RETURNING → row.
        # Third call: re-SELECT users (existing-user branch never used here).
        queries.append((query, args))
        if "INSERT INTO users" in query:
            return {"id": uuid4(), "telegram_user_id": args[0],
                    "username": args[1], "role": "user",
                    "auto_trade_on": False, "referrer_id": None}
        return None  # new user — no existing row

    async def _execute(query, *args):
        queries.append((query, args))

    conn.fetchrow = AsyncMock(side_effect=_fetchrow)
    conn.execute = AsyncMock(side_effect=_execute)
    conn.transaction = MagicMock(return_value=_ctx())
    pool = _make_pool(conn)

    # Stub _bootstrap_new_user + _enroll_signal_following so we test the
    # INSERT call shape in isolation.
    with patch.object(users_module, "get_pool", return_value=pool), \
         patch.object(users_module, "_bootstrap_new_user", new=AsyncMock()), \
         patch.object(users_module, "_enroll_signal_following", new=AsyncMock()):
        asyncio.run(upsert_user(12345, "alice"))

    settings_inserts = [
        (q, a) for q, a in queries
        if "INSERT INTO user_settings" in q
    ]
    assert settings_inserts, "user_settings INSERT must run for new user"
    query, _args = settings_inserts[0]
    assert "trading_mode" in query, \
        "INSERT must write trading_mode column explicitly (F-MEDIUM-1)"
    assert "'paper'" in query, \
        "INSERT must literal-write 'paper' so a future schema default " \
        "change cannot silently flip new users to live (F-MEDIUM-1)"


# ---------------------------------------------------------------------------
# get_settings_for — lazy-create branch must INSERT with 'paper'
# ---------------------------------------------------------------------------


def test_get_settings_for_lazy_insert_writes_paper():
    """When user_settings row is missing, lazy INSERT must write 'paper'."""
    conn = MagicMock()
    fetch_calls = {"count": 0}
    inserts: list[tuple[str, tuple]] = []

    async def _fetchrow(query, *args):
        fetch_calls["count"] += 1
        # First fetchrow returns None (missing row → triggers lazy INSERT).
        # Second returns a populated row (post-INSERT re-fetch).
        if fetch_calls["count"] == 1:
            return None
        return {"user_id": args[0], "trading_mode": "paper"}

    async def _execute(query, *args):
        inserts.append((query, args))

    conn.fetchrow = AsyncMock(side_effect=_fetchrow)
    conn.execute = AsyncMock(side_effect=_execute)
    pool = _make_pool(conn)

    with patch.object(users_module, "get_pool", return_value=pool):
        row = asyncio.run(get_settings_for(uuid4()))

    assert row["trading_mode"] == "paper"
    settings_inserts = [
        (q, a) for q, a in inserts if "INSERT INTO user_settings" in q
    ]
    assert settings_inserts, "lazy INSERT must run when row missing"
    query, _args = settings_inserts[0]
    assert "trading_mode" in query and "'paper'" in query, \
        "lazy INSERT must write trading_mode='paper' explicitly (F-MEDIUM-1)"


# ---------------------------------------------------------------------------
# Source-level guard: literal SQL inspection
# ---------------------------------------------------------------------------


def _normalize_python_strings(src: str) -> str:
    """Collapse Python implicit string-concat across line breaks so SQL
    statements split across adjacent literals are visible to substring
    checks. Replaces ``"<spaces+newline+spaces>"`` (the gap between two
    adjacent string literals) with the empty string.
    """
    import re

    return re.sub(r'"\s*\n\s*"', "", src)


def test_users_module_source_contains_explicit_paper_inserts():
    """Last-resort source guard: any future edit that drops the literal
    ``trading_mode='paper'`` from a ``user_settings`` INSERT will trip this.
    """
    import re
    from pathlib import Path

    src = _normalize_python_strings(
        Path(users_module.__file__).read_text(encoding="utf-8")
    )
    inserts = re.findall(
        r"INSERT INTO user_settings[^;]{0,500}",
        src,
        flags=re.IGNORECASE,
    )
    assert inserts, "users.py should contain at least one user_settings INSERT"
    for stmt in inserts:
        head = stmt[:300]
        assert "trading_mode" in head, (
            "user_settings INSERT must reference trading_mode explicitly "
            f"(F-MEDIUM-1). Offending stmt: {head[:160]}"
        )
        assert "'paper'" in head, (
            "user_settings INSERT must literal-write 'paper' "
            f"(F-MEDIUM-1). Offending stmt: {head[:160]}"
        )


def test_webtrader_signup_source_contains_explicit_paper_insert():
    """Same source guard for webtrader/backend/auth.py:signup_email."""
    import re
    from pathlib import Path

    from projects.polymarket.crusaderbot.webtrader.backend import auth

    src = _normalize_python_strings(
        Path(auth.__file__).read_text(encoding="utf-8")
    )
    inserts = re.findall(
        r"INSERT INTO user_settings[^;]{0,500}",
        src,
        flags=re.IGNORECASE,
    )
    assert inserts, (
        "webtrader signup must contain a user_settings INSERT for "
        "PAPER-default parity with Telegram path (F-MEDIUM-1)"
    )
    for stmt in inserts:
        head = stmt[:300]
        assert "trading_mode" in head and "'paper'" in head, (
            f"webtrader user_settings INSERT must write trading_mode='paper' "
            f"(F-MEDIUM-1). Offending stmt: {head[:160]}"
        )


def test_webtrader_signup_logs_bootstrap_failure():
    """F-LOW-1: webtrader signup must not silently swallow the
    _bootstrap_new_user exception. The literal ``logger.exception`` call
    is the contract; a future regression to ``pass`` will fail this test.
    """
    from pathlib import Path

    from projects.polymarket.crusaderbot.webtrader.backend import auth

    src = Path(auth.__file__).read_text(encoding="utf-8")
    # Look at the signup_email function body.
    assert "logger.exception(" in src, (
        "webtrader/backend/auth.py must log bootstrap exceptions, not "
        "swallow them silently (F-LOW-1, CLAUDE.md no-silent-failures HARD RULE)"
    )
    # And the bare ``except Exception: pass`` pattern must not be present
    # inside the signup path. (Coarse check — source-level.)
    assert "    except Exception:\n        pass" not in src, (
        "webtrader signup must not silently `pass` on bootstrap exception "
        "(F-LOW-1)"
    )
