"""Regression pins for PAPER -> LIVE notification isolation (#1792)."""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def test_alert_query_filters_by_ack_watermark_and_current_mode() -> None:
    """LIVE AlertCenter must not count/show structured PAPER alert rows.

    The production bug was old PAPER web notifications surviving the switch.
    The backend query must keep the existing acknowledgement watermark and add
    metadata.mode filtering against user_settings.trading_mode.
    """
    src = (_ROOT / "webtrader" / "backend" / "router.py").read_text(encoding="utf-8")
    assert "us.alerts_ack_at IS NULL OR a.created_at > us.alerts_ack_at" in src
    assert "a.metadata->>'mode'" in src
    assert "LOWER(a.metadata->>'mode') = COALESCE(us.trading_mode, 'paper')" in src
    assert "a.user_id IS NULL" in src


def test_live_switch_archives_user_alertcenter_rows_without_deleting_audit() -> None:
    """PAPER -> LIVE switch archives existing user-scoped AlertCenter rows.

    Records are retained in system_alerts for audit/debugging, but dismissed so
    the LIVE context and unread counter start clean immediately after switch.
    """
    src = (_ROOT / "domain" / "activation" / "live_mode.py").read_text(encoding="utf-8")
    assert "UPDATE system_alerts" in src
    assert "SET dismissed = TRUE" in src
    assert "WHERE user_id = $1" in src
    assert "created_at <= NOW()" in src
    assert "DELETE FROM system_alerts" not in src


def test_frontend_refreshes_alertcenter_on_settings_sse() -> None:
    """The switch writes user_settings, so settings SSE must refresh chrome.

    This prevents stale in-memory PAPER alert rows/unread counts from staying
    visible until a full page reload after the backend has already isolated the
    LIVE context.
    """
    src = (_ROOT / "webtrader" / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "settings: () =>" in src
    assert "setAlerts([]);" in src
    assert "refreshTradingMode();" in src


def test_daily_report_web_alerts_are_tagged_paper_mode() -> None:
    """Future Daily P&L summaries are explicitly PAPER-context alerts."""
    src = (_ROOT / "jobs" / "daily_pnl_summary.py").read_text(encoding="utf-8")
    assert 'alert_kind="daily_report"' in src
    assert 'metadata={"mode": "paper"}' in src
