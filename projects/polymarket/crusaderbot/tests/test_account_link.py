"""Reverse Telegram-link domain tests — code mint + redeem/merge logic.

Hermetic: no DB. asyncpg pool/connection faked at the fetchrow/fetchval/execute
level (mirrors tests/test_users.py).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from projects.polymarket.crusaderbot.domain.activation import account_link
from projects.polymarket.crusaderbot.domain.activation.account_link import (
    AccountLinkError,
    LinkOutcome,
    format_code_for_display,
    generate_link_code,
    redeem_link_code,
)


# ── pool/conn fakes ───────────────────────────────────────────────────────────


def _ctx(value=None):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=value)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _make_pool(conn):
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_ctx(conn))
    return pool


def _redeem_conn(*, code_row, primary_row, dup_row=None, dup_mode="paper", dup_counts=0):
    conn = MagicMock()
    conn.executed: list[str] = []

    async def fetchrow(query, *args):
        if "account_link_codes" in query:
            return code_row
        if "telegram_user_id = $1" in query:   # dup lookup by tg id
            return dup_row
        if "FROM users WHERE id = $1" in query:  # primary lookup
            return primary_row
        return None

    async def fetchval(query, *args):
        if "trading_mode" in query:
            return dup_mode
        if "COUNT(*)" in query:
            return dup_counts
        return None

    async def execute(query, *args):
        conn.executed.append(query)

    conn.fetchrow = fetchrow
    conn.fetchval = fetchval
    conn.execute = execute
    conn.transaction = MagicMock(return_value=_ctx())
    return conn


def _run_redeem(conn, code="ABCD-EFGH", tg_id=999, username="bob"):
    pool = _make_pool(conn)
    with patch.object(account_link, "get_pool", return_value=pool), \
         patch.object(account_link.audit, "write", AsyncMock()):
        return asyncio.run(redeem_link_code(code, tg_id, username))


def _future():
    return datetime.now(timezone.utc) + timedelta(minutes=10)


def _past():
    return datetime.now(timezone.utc) - timedelta(minutes=1)


# ── format / normalise ────────────────────────────────────────────────────────


def test_format_code_adds_hyphen():
    assert format_code_for_display("abcdefgh") == "ABCD-EFGH"


# ── generate_link_code ────────────────────────────────────────────────────────


def test_generate_rejects_already_linked():
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=12345)  # telegram_user_id present
    conn.execute = AsyncMock()
    with patch.object(account_link, "get_pool", return_value=_make_pool(conn)):
        with pytest.raises(AccountLinkError):
            asyncio.run(generate_link_code(uuid4()))


def test_generate_mints_code_and_clears_old():
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=None)  # no telegram linked
    conn.execute = AsyncMock()
    with patch.object(account_link, "get_pool", return_value=_make_pool(conn)):
        code = asyncio.run(generate_link_code(uuid4()))
    assert len(code) == 8 and code.isalnum() and code.isupper()
    # DELETE old + INSERT new
    queries = " ".join(c.args[0] for c in conn.execute.await_args_list)
    assert "DELETE FROM account_link_codes" in queries
    assert "INSERT INTO account_link_codes" in queries


# ── redeem: error paths ───────────────────────────────────────────────────────


def test_redeem_invalid_code():
    res = _run_redeem(_redeem_conn(code_row=None, primary_row=None))
    assert res.outcome is LinkOutcome.INVALID_CODE


def test_redeem_consumed_code_is_invalid():
    code_row = {"user_id": uuid4(), "expires_at": _future(), "consumed_at": datetime.now(timezone.utc)}
    res = _run_redeem(_redeem_conn(code_row=code_row, primary_row=None))
    assert res.outcome is LinkOutcome.INVALID_CODE


def test_redeem_expired():
    code_row = {"user_id": uuid4(), "expires_at": _past(), "consumed_at": None}
    res = _run_redeem(_redeem_conn(code_row=code_row, primary_row=None))
    assert res.outcome is LinkOutcome.EXPIRED


def test_redeem_primary_already_linked_other_tg():
    pid = uuid4()
    code_row = {"user_id": pid, "expires_at": _future(), "consumed_at": None}
    primary = {"id": pid, "telegram_user_id": 111}  # different from 999
    res = _run_redeem(_redeem_conn(code_row=code_row, primary_row=primary))
    assert res.outcome is LinkOutcome.PRIMARY_ALREADY_LINKED


# ── redeem: success paths ─────────────────────────────────────────────────────


def test_redeem_clean_attach_no_duplicate():
    pid = uuid4()
    code_row = {"user_id": pid, "expires_at": _future(), "consumed_at": None}
    primary = {"id": pid, "telegram_user_id": None}
    conn = _redeem_conn(code_row=code_row, primary_row=primary, dup_row=None)
    res = _run_redeem(conn)
    assert res.outcome is LinkOutcome.OK_LINKED
    assert res.canonical_user_id == pid
    joined = " ".join(conn.executed)
    assert "UPDATE users SET telegram_user_id = $1" in joined
    assert "consumed_at = NOW()" in joined


def test_redeem_already_linked_same_tg():
    pid = uuid4()
    code_row = {"user_id": pid, "expires_at": _future(), "consumed_at": None}
    primary = {"id": pid, "telegram_user_id": 999}  # same as redeeming tg id
    res = _run_redeem(_redeem_conn(code_row=code_row, primary_row=primary))
    assert res.outcome is LinkOutcome.OK_ALREADY


def test_redeem_merges_fresh_duplicate():
    pid, did = uuid4(), uuid4()
    code_row = {"user_id": pid, "expires_at": _future(), "consumed_at": None}
    primary = {"id": pid, "telegram_user_id": None}
    dup = {"id": did}
    conn = _redeem_conn(code_row=code_row, primary_row=primary, dup_row=dup,
                        dup_mode="paper", dup_counts=0)
    res = _run_redeem(conn)
    assert res.outcome is LinkOutcome.OK_MERGED
    joined = " ".join(conn.executed)
    # tombstone the duplicate (free tg id + synthetic email + merged_into)
    assert "telegram_user_id = NULL" in joined
    assert "merged_into = $3" in joined
    # reassign tg id to canonical account
    assert "UPDATE users SET telegram_user_id = $1" in joined


def test_redeem_blocks_duplicate_with_history():
    pid, did = uuid4(), uuid4()
    code_row = {"user_id": pid, "expires_at": _future(), "consumed_at": None}
    primary = {"id": pid, "telegram_user_id": None}
    dup = {"id": did}
    conn = _redeem_conn(code_row=code_row, primary_row=primary, dup_row=dup,
                        dup_mode="paper", dup_counts=3)  # has positions
    res = _run_redeem(conn)
    assert res.outcome is LinkOutcome.TG_HAS_HISTORY
    # no tombstone / reassign happened
    joined = " ".join(conn.executed)
    assert "telegram_user_id = NULL" not in joined


def test_redeem_blocks_live_duplicate():
    pid, did = uuid4(), uuid4()
    code_row = {"user_id": pid, "expires_at": _future(), "consumed_at": None}
    primary = {"id": pid, "telegram_user_id": None}
    dup = {"id": did}
    conn = _redeem_conn(code_row=code_row, primary_row=primary, dup_row=dup,
                        dup_mode="live", dup_counts=0)
    res = _run_redeem(conn)
    assert res.outcome is LinkOutcome.TG_HAS_HISTORY


# ── wiring pins (endpoint + bot command) ──────────────────────────────────────


def test_telegram_link_command_registered():
    """/link must be registered and route to account_link.link_command."""
    import inspect

    from projects.polymarket.crusaderbot.bot import dispatcher
    src = inspect.getsource(dispatcher)
    assert 'CommandHandler("link"' in src
    assert "account_link.link_command" in src


def test_link_command_uses_redeem():
    import inspect

    from projects.polymarket.crusaderbot.bot.handlers import account_link as h
    src = inspect.getsource(h.link_command)
    assert "redeem_link_code" in src
    # plain-text replies (no MarkdownV2) to avoid escaping the outcome message
    assert "parse_mode" not in src


def _me_conn(row):
    conn = MagicMock()

    async def fetchrow(query, *args):
        return row

    conn.fetchrow = fetchrow
    return conn


def test_get_me_reports_linked_email_and_telegram():
    """/me must surface persisted email + telegram link state so Settings
    renders 'connected' rows instead of re-showing the link forms on refresh."""
    from projects.polymarket.crusaderbot.webtrader.backend import router as r
    conn = _me_conn({"email": "walker@x.com", "username": "walk", "telegram_user_id": 123, "role": "user"})
    with patch.object(r, "get_pool", return_value=_make_pool(conn)):
        res = asyncio.run(r.get_me({"user_id": "uid", "first_name": "W"}))
    assert res["email"] == "walker@x.com"
    assert res["telegram_linked"] is True
    assert res["username"] == "walk"


def test_get_me_excludes_tombstone_email():
    """Synthetic tombstone emails (merged-*@telegram.local) are not real
    logins and must surface as email=None."""
    from projects.polymarket.crusaderbot.webtrader.backend import router as r
    conn = _me_conn({"email": "merged-abc@telegram.local", "username": "walk", "telegram_user_id": 123, "role": "user"})
    with patch.object(r, "get_pool", return_value=_make_pool(conn)):
        res = asyncio.run(r.get_me({"user_id": "uid", "first_name": "W"}))
    assert res["email"] is None
    assert res["telegram_linked"] is True


def test_webtrader_link_endpoints_present():
    import inspect

    from projects.polymarket.crusaderbot.webtrader.backend import router as r
    start_src = inspect.getsource(r.link_telegram_start)
    assert "generate_link_code" in start_src
    assert 'per_user_rate_limit("account_link"' in inspect.getsource(r)
    status_src = inspect.getsource(r.link_telegram_status)
    assert "telegram_user_id" in status_src
