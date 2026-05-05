"""Hermetic tests for the R12f operator-dashboard handlers.

Exercises the pure formatters (``_render_dashboard``, ``_render_jobs``,
``_render_auditlog``, ``_format_uptime``, ``_truncate``,
``_parse_limit``) directly, plus the operator-gate wiring on the four
new commands using ``ContextTypes``-style doubles. No DB, no Telegram
network calls.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from projects.polymarket.crusaderbot.bot.handlers import admin


# ---------- Pure helpers ----------------------------------------------------


def test_format_uptime_minutes():
    assert admin._format_uptime(0) == "0m"
    assert admin._format_uptime(59) == "0m"
    assert admin._format_uptime(125) == "2m"


def test_format_uptime_hours():
    assert admin._format_uptime(3 * 3600 + 12 * 60) == "3h 12m"


def test_format_uptime_days():
    assert admin._format_uptime(2 * 86400 + 4 * 3600 + 30 * 60) == "2d 4h 30m"


def test_format_duration_handles_none():
    assert admin._format_duration_ms(None, None) == "—"
    now = datetime.now(timezone.utc)
    assert admin._format_duration_ms(now, None) == "—"


def test_format_duration_milliseconds():
    start = datetime(2026, 5, 5, 0, 0, 0, tzinfo=timezone.utc)
    out = admin._format_duration_ms(start, start + timedelta(milliseconds=350))
    assert out == "350ms"


def test_format_duration_seconds():
    start = datetime(2026, 5, 5, 0, 0, 0, tzinfo=timezone.utc)
    out = admin._format_duration_ms(start, start + timedelta(seconds=12.4))
    assert out == "12.4s"


def test_format_duration_minutes():
    start = datetime(2026, 5, 5, 0, 0, 0, tzinfo=timezone.utc)
    out = admin._format_duration_ms(start, start + timedelta(seconds=125))
    assert out == "2.1m"


def test_truncate_passthrough_under_limit():
    assert admin._truncate("hello", 80) == "hello"


def test_truncate_appends_ellipsis_over_limit():
    out = admin._truncate("x" * 200, 80)
    assert len(out) == 80 and out.endswith("…")


def test_truncate_handles_none():
    assert admin._truncate(None, 80) == ""


# ---------- _parse_limit ----------------------------------------------------


def test_parse_limit_default_when_no_args():
    assert admin._parse_limit([], 10) == (10, False)


def test_parse_limit_picks_integer():
    assert admin._parse_limit(["5"], 10) == (5, False)


def test_parse_limit_recognises_failed_token():
    assert admin._parse_limit(["failed"], 10) == (10, True)


def test_parse_limit_combines_failed_and_n():
    assert admin._parse_limit(["failed", "7"], 10) == (7, True)


def test_parse_limit_clamps_to_max():
    assert admin._parse_limit(["999"], 10) == (admin.MAX_OPS_LIMIT, False)


def test_parse_limit_ignores_garbage():
    assert admin._parse_limit(["nope"], 10) == (10, False)


# ---------- Renderers -------------------------------------------------------


def _job_row(name: str, status: str, *, error: str | None = None,
             duration_ms: int = 100) -> dict:
    start = datetime(2026, 5, 5, 0, 0, 0, tzinfo=timezone.utc)
    return {
        "job_name": name,
        "status": status,
        "started_at": start,
        "finished_at": start + timedelta(milliseconds=duration_ms),
        "error": error,
    }


def test_render_dashboard_kill_switch_inactive():
    snapshot = {
        "uptime_seconds": 90,
        "hostname": "fly-machine-abc",
        "db_ok": True,
        "active_users": 12,
        "open_positions": 3,
        "total_usdc": 1234.5,
        "auto_trade_users": 7,
        "kill_switch_active": False,
        "lock_mode": False,
        "recent_jobs": [_job_row("market_sync", "success")],
        "errors": [],
    }
    out = admin._render_dashboard(snapshot)
    assert "Operator Dashboard" in out
    assert "🟢 inactive" in out
    assert "1m" in out  # uptime
    assert "$1,234.50" in out
    assert "market_sync" in out
    assert "(LOCK)" not in out


def test_render_dashboard_kill_switch_locked():
    snapshot = {
        "uptime_seconds": 0,
        "hostname": "h",
        "db_ok": True,
        "active_users": 0,
        "open_positions": 0,
        "total_usdc": 0,
        "auto_trade_users": 0,
        "kill_switch_active": True,
        "lock_mode": True,
        "recent_jobs": [],
        "errors": [],
    }
    out = admin._render_dashboard(snapshot)
    assert "🔴 ACTIVE" in out
    assert "(LOCK)" in out
    assert "_No recent job runs recorded._" in out


def test_render_dashboard_handles_missing_fields():
    snapshot = {
        "uptime_seconds": 0,
        "hostname": "h",
        "db_ok": False,
        "active_users": None,
        "open_positions": None,
        "total_usdc": None,
        "auto_trade_users": None,
        "kill_switch_active": False,
        "lock_mode": False,
        "recent_jobs": [],
        "errors": ["db: down"],
    }
    out = admin._render_dashboard(snapshot)
    assert "❌" in out  # DB down
    assert "N/A" in out
    assert "Some fields unavailable" in out


def test_render_jobs_empty_default():
    assert "_No job runs recorded yet._" in admin._render_jobs([], False)


def test_render_jobs_empty_failed_filter_message():
    assert "_No matching job runs._" in admin._render_jobs([], True)


def test_render_jobs_truncates_long_errors():
    long_err = "Boom! " + "x" * 500
    rows = [_job_row("redeem", "failed", error=long_err)]
    out = admin._render_jobs(rows, only_failed=True)
    assert "Recent failed job runs" in out
    assert "❌" in out
    # Error fragment is truncated to 80 chars in the renderer.
    assert "…" in out


def test_render_auditlog_empty():
    assert "_Audit log is empty._" in admin._render_auditlog([])


def test_render_auditlog_truncates_user_id():
    rows = [{
        "ts": datetime(2026, 5, 5, 12, 30, 0, tzinfo=timezone.utc),
        "actor_role": "operator",
        "action": "kill_switch_pause",
        "user_id": "abcdefghijklmno",
    }]
    out = admin._render_auditlog(rows)
    assert "operator" in out
    assert "kill_switch_pause" in out
    # user_id truncated to 8 chars + ellipsis = 8 chars
    assert "abcdefg…" in out


# ---------- Operator gate ---------------------------------------------------


def _fake_settings(operator_id: int = 42):
    return SimpleNamespace(OPERATOR_CHAT_ID=operator_id)


def _fake_update(user_id: int, *, command_args: list[str] | None = None,
                 message: bool = True):
    msg = SimpleNamespace(reply_text=AsyncMock())
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        message=msg if message else None,
        callback_query=None,
    )


def _fake_ctx(args: list[str] | None = None):
    return SimpleNamespace(args=args or [])


def test_ops_dashboard_rejects_non_operator_silently():
    update = _fake_update(user_id=999)  # not the operator
    ctx = _fake_ctx()
    with patch.object(admin, "get_settings", return_value=_fake_settings(42)):
        asyncio.run(admin.ops_dashboard_command(update, ctx))
    update.message.reply_text.assert_not_called()


def test_killswitch_rejects_non_operator_silently():
    update = _fake_update(user_id=999)
    ctx = _fake_ctx(args=["pause"])
    with patch.object(admin, "get_settings", return_value=_fake_settings(42)):
        asyncio.run(admin.killswitch_command(update, ctx))
    update.message.reply_text.assert_not_called()


def test_jobs_rejects_non_operator_silently():
    update = _fake_update(user_id=999)
    with patch.object(admin, "get_settings", return_value=_fake_settings(42)):
        asyncio.run(admin.jobs_command(update, _fake_ctx()))
    update.message.reply_text.assert_not_called()


def test_auditlog_rejects_non_operator_silently():
    update = _fake_update(user_id=999)
    with patch.object(admin, "get_settings", return_value=_fake_settings(42)):
        asyncio.run(admin.auditlog_command(update, _fake_ctx()))
    update.message.reply_text.assert_not_called()


# ---------- Operator happy paths -------------------------------------------


def test_ops_dashboard_renders_for_operator():
    update = _fake_update(user_id=42)
    ctx = _fake_ctx()
    snapshot = {
        "uptime_seconds": 60,
        "hostname": "h",
        "db_ok": True,
        "active_users": 1,
        "open_positions": 0,
        "total_usdc": 0,
        "auto_trade_users": 0,
        "kill_switch_active": False,
        "lock_mode": False,
        "recent_jobs": [],
        "errors": [],
    }
    with patch.object(admin, "get_settings", return_value=_fake_settings(42)), \
         patch.object(admin, "_collect_dashboard_snapshot",
                      AsyncMock(return_value=snapshot)):
        asyncio.run(admin.ops_dashboard_command(update, ctx))
    update.message.reply_text.assert_awaited_once()
    args, kwargs = update.message.reply_text.call_args
    assert "Operator Dashboard" in args[0]
    assert kwargs["reply_markup"] is not None


def test_killswitch_usage_with_no_args():
    update = _fake_update(user_id=42)
    ctx = _fake_ctx(args=[])
    with patch.object(admin, "get_settings", return_value=_fake_settings(42)):
        asyncio.run(admin.killswitch_command(update, ctx))
    args, _ = update.message.reply_text.call_args
    assert "Usage" in args[0]


def test_killswitch_invalid_action_shows_usage():
    update = _fake_update(user_id=42)
    ctx = _fake_ctx(args=["nuke"])
    with patch.object(admin, "get_settings", return_value=_fake_settings(42)):
        asyncio.run(admin.killswitch_command(update, ctx))
    args, _ = update.message.reply_text.call_args
    assert "Usage" in args[0]


def test_killswitch_pause_calls_set_active_and_replies():
    update = _fake_update(user_id=42)
    ctx = _fake_ctx(args=["pause"])
    set_active = AsyncMock(return_value={
        "active": True, "lock_mode": False, "users_disabled": 0,
    })
    with patch.object(admin, "get_settings", return_value=_fake_settings(42)), \
         patch.object(admin.ops_kill_switch, "set_active", set_active), \
         patch.object(admin.audit, "write", AsyncMock()), \
         patch.object(admin, "_broadcast_pause", AsyncMock(return_value=3)):
        asyncio.run(admin.killswitch_command(update, ctx))
    set_active.assert_awaited_once()
    kwargs = set_active.await_args.kwargs
    assert kwargs["action"] == "pause"
    assert kwargs["actor_id"] == 42
    args, _ = update.message.reply_text.call_args
    assert "ACTIVE" in args[0]


def test_killswitch_resume_calls_set_active_and_replies():
    update = _fake_update(user_id=42)
    ctx = _fake_ctx(args=["resume"])
    set_active = AsyncMock(return_value={
        "active": False, "lock_mode": False, "users_disabled": 0,
    })
    with patch.object(admin, "get_settings", return_value=_fake_settings(42)), \
         patch.object(admin.ops_kill_switch, "set_active", set_active), \
         patch.object(admin.audit, "write", AsyncMock()):
        asyncio.run(admin.killswitch_command(update, ctx))
    set_active.assert_awaited_once()
    args, _ = update.message.reply_text.call_args
    assert "deactivated" in args[0].lower()


def test_killswitch_lock_disables_users_and_replies():
    update = _fake_update(user_id=42)
    ctx = _fake_ctx(args=["lock"])
    set_active = AsyncMock(return_value={
        "active": True, "lock_mode": True, "users_disabled": 5,
    })
    with patch.object(admin, "get_settings", return_value=_fake_settings(42)), \
         patch.object(admin.ops_kill_switch, "set_active", set_active), \
         patch.object(admin.audit, "write", AsyncMock()), \
         patch.object(admin, "_broadcast_pause", AsyncMock(return_value=5)):
        asyncio.run(admin.killswitch_command(update, ctx))
    args, _ = update.message.reply_text.call_args
    assert "LOCKED" in args[0]
    assert "5 users" in args[0]


def test_jobs_invokes_tracker_with_default_limit():
    update = _fake_update(user_id=42)
    ctx = _fake_ctx(args=[])
    fetch = AsyncMock(return_value=[_job_row("market_sync", "success")])
    with patch.object(admin, "get_settings", return_value=_fake_settings(42)), \
         patch.object(admin.job_tracker, "fetch_recent", fetch):
        asyncio.run(admin.jobs_command(update, ctx))
    fetch.assert_awaited_once()
    kwargs = fetch.await_args.kwargs
    assert kwargs["limit"] == admin.DEFAULT_JOB_LIMIT
    assert kwargs["only_failed"] is False


def test_jobs_failed_filter_passes_through():
    update = _fake_update(user_id=42)
    ctx = _fake_ctx(args=["failed"])
    fetch = AsyncMock(return_value=[])
    with patch.object(admin, "get_settings", return_value=_fake_settings(42)), \
         patch.object(admin.job_tracker, "fetch_recent", fetch):
        asyncio.run(admin.jobs_command(update, ctx))
    fetch.assert_awaited_once()
    assert fetch.await_args.kwargs["only_failed"] is True


def test_auditlog_default_limit():
    update = _fake_update(user_id=42)
    ctx = _fake_ctx(args=[])
    rows = [{
        "ts": datetime(2026, 5, 5, tzinfo=timezone.utc),
        "actor_role": "operator", "action": "kill_switch_pause",
        "user_id": "abc",
    }]
    fetch = AsyncMock(return_value=rows)
    with patch.object(admin, "get_settings", return_value=_fake_settings(42)), \
         patch.object(admin, "_fetch_audit_tail", fetch):
        asyncio.run(admin.auditlog_command(update, ctx))
    fetch.assert_awaited_once_with(admin.DEFAULT_AUDIT_LIMIT)
    args, _ = update.message.reply_text.call_args
    assert "kill_switch_pause" in args[0]
