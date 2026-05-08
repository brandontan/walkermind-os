"""Hermetic tests for the investor-facing demo polish handlers.

Covers /about, /status, /demo plus the per-user rate limiter on /demo.
No DB, no Telegram network, no HTTP — every dependency is mocked at the
module boundary.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from projects.polymarket.crusaderbot.bot.handlers import demo_polish


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_update(*, user_id: int = 12345, message_text: str = "/demo"):
    """Build a minimal Update double accepted by the handlers."""
    message = SimpleNamespace(
        text=message_text,
        reply_text=AsyncMock(return_value=None),
    )
    user = SimpleNamespace(id=user_id, first_name="Test", username="test_user")
    return SimpleNamespace(
        message=message,
        effective_user=user,
        callback_query=None,
    )


def _ctx() -> MagicMock:
    return MagicMock()


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    demo_polish._reset_demo_rate_limit_for_tests()
    yield
    demo_polish._reset_demo_rate_limit_for_tests()


# ---------------------------------------------------------------------------
# /about
# ---------------------------------------------------------------------------


def test_about_command_replies_with_paper_mode_disclaimer():
    update = _make_update(message_text="/about")
    _run(demo_polish.about_command(update, _ctx()))
    update.message.reply_text.assert_called_once()
    text, kwargs = update.message.reply_text.call_args.args, update.message.reply_text.call_args.kwargs
    body = text[0]
    assert "Paper-trading mode is the default" in body
    assert "📄" in body
    assert "/demo" in body
    assert "/status" in body
    assert "/help" in body


def test_about_command_no_internal_jargon():
    update = _make_update(message_text="/about")
    _run(demo_polish.about_command(update, _ctx()))
    body = update.message.reply_text.call_args.args[0]
    # Reject WARP-internal jargon that must never reach end users.
    forbidden = ["WARP", "Tier 4", "FORGE", "SENTINEL", "ECHO", "CMD"]
    for token in forbidden:
        assert token not in body, f"investor copy must not mention {token!r}"


def test_about_command_handles_missing_message_gracefully():
    update = SimpleNamespace(message=None, effective_user=None, callback_query=None)
    # Must not raise.
    _run(demo_polish.about_command(update, _ctx()))


# ---------------------------------------------------------------------------
# /status
# ---------------------------------------------------------------------------


_HEALTH_OK_PAYLOAD = {
    "status": "ok",
    "service": "CrusaderBot",
    "ready": True,
    "checks": {
        "database": "ok",
        "telegram": "ok",
        "alchemy_rpc": "ok",
        "alchemy_ws": "ok",
    },
}

_HEALTH_DEGRADED_PAYLOAD = {
    "status": "degraded",
    "service": "CrusaderBot",
    "ready": True,
    "checks": {
        "database": "ok",
        "telegram": "ok",
        "alchemy_rpc": "error: 503",
        "alchemy_ws": "ok",
    },
}


def test_status_paper_mode_banner_when_guards_off():
    update = _make_update(message_text="/status")
    with patch(
        "projects.polymarket.crusaderbot.bot.handlers.demo_polish.run_health_checks",
        new=AsyncMock(return_value=_HEALTH_OK_PAYLOAD),
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.demo_polish._resolve_mode",
        return_value="paper",
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.demo_polish._resolve_version",
        return_value="abc1234",
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.demo_polish._uptime_seconds",
        return_value=125,
    ):
        _run(demo_polish.status_command(update, _ctx()))
    body = update.message.reply_text.call_args.args[0]
    assert "📄 *PAPER MODE*" in body
    assert "no real capital at risk" in body
    assert "abc1234" in body
    assert "2m" in body  # 125s == 2m
    assert "🟢" in body
    assert "OK" in body
    assert "Closed-beta build • paper trading active" in body


def test_status_live_mode_banner_when_all_guards_on():
    update = _make_update(message_text="/status")
    with patch(
        "projects.polymarket.crusaderbot.bot.handlers.demo_polish.run_health_checks",
        new=AsyncMock(return_value=_HEALTH_OK_PAYLOAD),
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.demo_polish._resolve_mode",
        return_value="live",
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.demo_polish._resolve_version",
        return_value="def5678",
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.demo_polish._uptime_seconds",
        return_value=86400 * 2 + 3600 * 4 + 60 * 30,
    ):
        _run(demo_polish.status_command(update, _ctx()))
    body = update.message.reply_text.call_args.args[0]
    assert "⚡ *LIVE MODE*" in body
    assert "2d 4h 30m" in body


def test_status_degraded_status_renders_yellow():
    update = _make_update(message_text="/status")
    with patch(
        "projects.polymarket.crusaderbot.bot.handlers.demo_polish.run_health_checks",
        new=AsyncMock(return_value=_HEALTH_DEGRADED_PAYLOAD),
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.demo_polish._resolve_mode",
        return_value="paper",
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.demo_polish._resolve_version",
        return_value="abc1234",
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.demo_polish._uptime_seconds",
        return_value=600,
    ):
        _run(demo_polish.status_command(update, _ctx()))
    body = update.message.reply_text.call_args.args[0]
    assert "🟡" in body
    assert "DEGRADED" in body
    assert "alchemy_rpc" in body


def test_status_health_check_failure_is_handled_gracefully():
    update = _make_update(message_text="/status")
    with patch(
        "projects.polymarket.crusaderbot.bot.handlers.demo_polish.run_health_checks",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        _run(demo_polish.status_command(update, _ctx()))
    body = update.message.reply_text.call_args.args[0]
    assert "PAPER MODE" in body
    assert "temporarily unavailable" in body


# ---------------------------------------------------------------------------
# /demo
# ---------------------------------------------------------------------------


def _make_pool_with_rows(rows: list[dict]):
    """Build a fake asyncpg-style pool whose ``fetch`` returns ``rows``."""
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=[SimpleNamespace(**r) for r in rows]
                          if rows and not isinstance(rows[0], dict)
                          else AsyncMock())
    # asyncpg Records support dict(record) — emulate with a list of dicts wrapped
    # in a class that supports both attribute and __iter__-of-tuples access.
    class _Row(dict):
        def __init__(self, d):
            super().__init__(d)
        def __iter__(self):
            return iter(self.keys())
    conn.fetch = AsyncMock(return_value=[_Row(r) for r in rows])
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool


def test_demo_empty_state_when_no_signals():
    update = _make_update(user_id=1, message_text="/demo")
    pool = _make_pool_with_rows([])
    with patch(
        "projects.polymarket.crusaderbot.bot.handlers.demo_polish.get_pool",
        return_value=pool,
    ):
        _run(demo_polish.demo_command(update, _ctx()))
    body = update.message.reply_text.call_args.args[0]
    assert "no active signals" in body
    assert "Paper mode" in body or "paper mode" in body.lower()


def test_demo_renders_top_three_signals_with_confidence():
    update = _make_update(user_id=2, message_text="/demo")
    rows = [
        {
            "feed_name": "Alpha Feed",
            "market_id": "m1",
            "side": "yes",
            "target_price": 0.62,
            "payload": {"confidence": 0.78},
            "published_at": datetime(2026, 5, 8, 11, 0, tzinfo=timezone.utc),
            "market_question": "Will it rain in Jakarta tomorrow?",
        },
        {
            "feed_name": "Beta Feed",
            "market_id": "m2",
            "side": "no",
            "target_price": 0.41,
            "payload": {"edge": 0.55},
            "published_at": datetime(2026, 5, 8, 10, 0, tzinfo=timezone.utc),
            "market_question": "BTC > $100k by year end?",
        },
        {
            "feed_name": "Gamma Feed",
            "market_id": "m3",
            "side": "yes",
            "target_price": None,
            "payload": {},
            "published_at": datetime(2026, 5, 8, 9, 0, tzinfo=timezone.utc),
            "market_question": None,
        },
    ]
    pool = _make_pool_with_rows(rows)
    with patch(
        "projects.polymarket.crusaderbot.bot.handlers.demo_polish.get_pool",
        return_value=pool,
    ):
        _run(demo_polish.demo_command(update, _ctx()))
    body = update.message.reply_text.call_args.args[0]
    # Top 3 visible + confidences
    assert "Will it rain in Jakarta tomorrow?" in body
    assert "BTC > $100k by year end?" in body
    assert "78%" in body
    assert "55%" in body
    # Empty payload renders as em-dash, not invented data.
    assert "—" in body
    # Sides surfaced uppercase
    assert "YES" in body
    assert "NO" in body
    # Paper-mode disclaimer present.
    assert "Paper mode" in body or "paper mode" in body.lower()


def test_demo_db_failure_falls_back_to_empty_state():
    update = _make_update(user_id=3, message_text="/demo")
    pool = MagicMock()
    pool.acquire.side_effect = RuntimeError("pg unavailable")
    with patch(
        "projects.polymarket.crusaderbot.bot.handlers.demo_polish.get_pool",
        return_value=pool,
    ):
        _run(demo_polish.demo_command(update, _ctx()))
    body = update.message.reply_text.call_args.args[0]
    assert "no active signals" in body


def test_demo_rate_limit_blocks_second_call_within_60s():
    pool = _make_pool_with_rows([])
    with patch(
        "projects.polymarket.crusaderbot.bot.handlers.demo_polish.get_pool",
        return_value=pool,
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.demo_polish._now",
        side_effect=[100.0, 130.0],  # second call 30s later — still within 60s
    ):
        u1 = _make_update(user_id=42, message_text="/demo")
        _run(demo_polish.demo_command(u1, _ctx()))
        u2 = _make_update(user_id=42, message_text="/demo")
        _run(demo_polish.demo_command(u2, _ctx()))
    body2 = u2.message.reply_text.call_args.args[0]
    assert "rate-limited" in body2
    assert "30s" in body2 or "31s" in body2 or "29s" in body2  # tolerance


def test_demo_rate_limit_clears_after_window():
    pool = _make_pool_with_rows([])
    with patch(
        "projects.polymarket.crusaderbot.bot.handlers.demo_polish.get_pool",
        return_value=pool,
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.demo_polish._now",
        side_effect=[100.0, 161.0],  # 61s later — window expired
    ):
        u1 = _make_update(user_id=99, message_text="/demo")
        _run(demo_polish.demo_command(u1, _ctx()))
        u2 = _make_update(user_id=99, message_text="/demo")
        _run(demo_polish.demo_command(u2, _ctx()))
    body2 = u2.message.reply_text.call_args.args[0]
    assert "rate-limited" not in body2


def test_demo_rate_limit_per_user_isolation():
    pool = _make_pool_with_rows([])
    with patch(
        "projects.polymarket.crusaderbot.bot.handlers.demo_polish.get_pool",
        return_value=pool,
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.demo_polish._now",
        side_effect=[100.0, 105.0],  # different user, 5s later
    ):
        u_a = _make_update(user_id=1, message_text="/demo")
        _run(demo_polish.demo_command(u_a, _ctx()))
        u_b = _make_update(user_id=2, message_text="/demo")
        _run(demo_polish.demo_command(u_b, _ctx()))
    # Neither call should be rate-limited — different telegram_user_ids.
    body_b = u_b.message.reply_text.call_args.args[0]
    assert "rate-limited" not in body_b


# ---------------------------------------------------------------------------
# Pure formatters
# ---------------------------------------------------------------------------


def test_format_uptime_zero_is_zero_minutes():
    assert demo_polish._format_uptime(0) == "0m"


def test_format_uptime_minutes_only():
    assert demo_polish._format_uptime(125) == "2m"


def test_format_uptime_hours_and_minutes():
    assert demo_polish._format_uptime(3 * 3600 + 12 * 60) == "3h 12m"


def test_format_uptime_days_hours_minutes():
    assert demo_polish._format_uptime(2 * 86400 + 4 * 3600 + 30 * 60) == "2d 4h 30m"


def test_extract_confidence_picks_first_known_key():
    assert demo_polish._extract_confidence({"confidence": 0.5}) == "50%"
    assert demo_polish._extract_confidence({"edge": 0.3}) == "30%"
    assert demo_polish._extract_confidence({"score": 0.9}) == "90%"


def test_extract_confidence_returns_dash_when_missing():
    assert demo_polish._extract_confidence({}) == "—"
    assert demo_polish._extract_confidence(None) == "—"
    assert demo_polish._extract_confidence({"unrelated": 1}) == "—"


def test_extract_confidence_rejects_out_of_range_values():
    assert demo_polish._extract_confidence({"confidence": 1.5}) == "—"
    assert demo_polish._extract_confidence({"confidence": -0.1}) == "—"


def test_extract_confidence_parses_jsonb_string_payload():
    """asyncpg returns JSONB as str when no JSON codec is registered.

    The /demo handler must parse the string before key lookup, otherwise
    every real signal renders confidence as ``—``. Mirrors the
    ``signal_evaluator._payload_dict`` compatibility path.
    """
    assert demo_polish._extract_confidence('{"confidence": 0.42}') == "42%"
    assert demo_polish._extract_confidence('{"edge": 0.7}') == "70%"
    assert demo_polish._extract_confidence('{"score": 0.05}') == "5%"


def test_extract_confidence_handles_malformed_json_string():
    """Garbled JSON falls back to em-dash, not a parse exception."""
    assert demo_polish._extract_confidence("not-json") == "—"
    assert demo_polish._extract_confidence("{") == "—"
    assert demo_polish._extract_confidence("") == "—"


def test_payload_dict_passes_dict_through():
    assert demo_polish._payload_dict({"a": 1}) == {"a": 1}


def test_payload_dict_parses_json_string():
    assert demo_polish._payload_dict('{"confidence": 0.5}') == {"confidence": 0.5}


def test_payload_dict_returns_empty_for_non_dict_json():
    """JSON arrays / scalars must not leak through as a dict."""
    assert demo_polish._payload_dict("[1,2,3]") == {}
    assert demo_polish._payload_dict("123") == {}
    assert demo_polish._payload_dict("null") == {}


def test_payload_dict_returns_empty_for_garbage():
    assert demo_polish._payload_dict("not json") == {}
    assert demo_polish._payload_dict(None) == {}
    assert demo_polish._payload_dict(42) == {}


def test_escape_md_passes_safe_text_through():
    assert demo_polish._escape_md("plain text") == "plain text"
    assert demo_polish._escape_md("") == ""
    assert demo_polish._escape_md(None) == ""


def test_escape_md_escapes_v1_metacharacters():
    r"""``_ * \` [`` must be backslash-escaped before Markdown V1 interp."""
    assert demo_polish._escape_md("under_score") == "under\\_score"
    assert demo_polish._escape_md("a*b") == "a\\*b"
    assert demo_polish._escape_md("`code`") == "\\`code\\`"
    assert demo_polish._escape_md("[link]") == "\\[link]"


def test_escape_md_escapes_backslash_first():
    """Backslashes must be escaped first so the metachar loop does not
    double-escape what it just inserted.
    """
    assert demo_polish._escape_md("a\\b") == "a\\\\b"


def test_demo_renders_real_jsonb_string_payload_with_confidence():
    """End-to-end: asyncpg-style JSONB-as-string must render correctly."""
    update = _make_update(user_id=77, message_text="/demo")
    rows = [
        {
            "feed_name": "Alpha",
            "market_id": "m1",
            "side": "yes",
            "target_price": 0.62,
            "payload": '{"confidence": 0.81}',  # asyncpg without codec
            "published_at": datetime(2026, 5, 8, 11, 0, tzinfo=timezone.utc),
            "market_question": "Will it rain tomorrow?",
        },
    ]
    pool = _make_pool_with_rows(rows)
    with patch(
        "projects.polymarket.crusaderbot.bot.handlers.demo_polish.get_pool",
        return_value=pool,
    ):
        _run(demo_polish.demo_command(update, _ctx()))
    body = update.message.reply_text.call_args.args[0]
    assert "81%" in body, "confidence must be parsed from JSON-string payload"
    assert "—" not in body.split("Confidence: *")[1].split("*")[0]


def test_demo_escapes_markdown_metacharacters_in_db_strings():
    """Operator-supplied feed names + market questions must be escaped
    before flowing into a ``ParseMode.MARKDOWN`` reply, otherwise Telegram
    can reject the message or alter formatting.
    """
    update = _make_update(user_id=88, message_text="/demo")
    rows = [
        {
            "feed_name": "alpha_feed*v1",
            "market_id": "m1",
            "side": "yes",
            "target_price": 0.62,
            "payload": {"confidence": 0.5},
            "published_at": datetime(2026, 5, 8, 11, 0, tzinfo=timezone.utc),
            "market_question": "Will BTC > $100k by `Q4`? [poll]",
        },
    ]
    pool = _make_pool_with_rows(rows)
    with patch(
        "projects.polymarket.crusaderbot.bot.handlers.demo_polish.get_pool",
        return_value=pool,
    ):
        _run(demo_polish.demo_command(update, _ctx()))
    body = update.message.reply_text.call_args.args[0]
    # Underscores, asterisks, backticks, opening brackets in DB-supplied
    # text must arrive escaped — otherwise Telegram parsing breaks.
    assert "alpha\\_feed\\*v1" in body
    assert "\\`Q4\\`" in body
    assert "\\[poll]" in body


def test_truncate_short_string_passthrough():
    assert demo_polish._truncate("hello", 80) == "hello"


def test_truncate_long_string_appends_ellipsis():
    out = demo_polish._truncate("x" * 200, 80)
    assert len(out) == 80 and out.endswith("…")
