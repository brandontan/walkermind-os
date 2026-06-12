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


# ---------------------------------------------------------------------
# Full paper-session reset (R00T-expanded #1792 scope)
# ---------------------------------------------------------------------

def test_switch_archives_paper_ledger_and_reseeds_fresh_bankroll() -> None:
    """PAPER -> LIVE must archive the active paper LEDGER rows (not just
    positions/orders) and reseed a fresh $1,000 paper bankroll, so a
    returning paper user sees a clean session — not the stale 904.16 state.
    Audit rows are retained (archived flag), never deleted.
    """
    src = (_ROOT / "domain" / "activation" / "live_mode.py").read_text(encoding="utf-8")
    assert "UPDATE ledger AS l" in src
    assert "SET archived = TRUE" in src
    assert "DELETE FROM ledger" not in src
    # Fresh bankroll: wallet reset + a fresh paper deposit ledger row.
    assert "UPDATE wallets SET balance_usdc = $2 WHERE user_id = $1" in src
    assert "INSERT INTO ledger" in src
    assert "PAPER_STARTING_BALANCE_USDC" in src
    # Only on a genuine PAPER -> LIVE transition.
    assert 'if from_mode != "live":' in src


def test_migration_098_adds_ledger_archived_column() -> None:
    """The paper-session boundary needs a ledger.archived flag (additive,
    idempotent, default FALSE so existing rows are untouched)."""
    sql = (_ROOT / "migrations" / "098_ledger_archived.sql").read_text(encoding="utf-8")
    assert "ALTER TABLE ledger ADD COLUMN IF NOT EXISTS archived BOOLEAN" in sql
    assert "DEFAULT FALSE" in sql


def test_wallet_feeds_exclude_archived_ledger_rows() -> None:
    """The paper wallet feeds (/wallet, /wallet/ledger) must drop archived
    rows so a prior paper session does not resurface after PAPER->LIVE->PAPER.
    """
    src = (_ROOT / "webtrader" / "backend" / "router.py").read_text(encoding="utf-8")
    assert "AND NOT l.archived" in src
    assert "{'' if _mode_live else 'NOT '}{_flt} AND NOT l.archived" in src


def test_activity_and_orders_are_mode_scoped() -> None:
    """/activity and /orders previously had NO mode filter and leaked
    'paper_archived' rows after a switch. Both must filter by current mode.
    """
    src = (_ROOT / "webtrader" / "backend" / "router.py").read_text(encoding="utf-8")
    # /activity
    assert "AND p.mode = $3" in src
    # /orders
    assert "AND o.mode = $4" in src


def test_switch_dismisses_unmodeled_paper_alert_rows() -> None:
    """R00T hardening: the /alerts mode filter lets user rows with EMPTY
    metadata.mode pass (legacy unmodeled PAPER rows). The switch-time
    dismissed=TRUE must cover them — it is unconditional on metadata, keyed
    only on user_id + dismissed=FALSE + created_at — so old unmodeled paper
    AlertCenter rows cannot survive into the LIVE context.
    """
    live_src = (_ROOT / "domain" / "activation" / "live_mode.py").read_text(encoding="utf-8")
    # The dismiss UPDATE has NO metadata predicate — covers modeled + unmodeled.
    assert "UPDATE system_alerts" in live_src
    assert "SET dismissed = TRUE" in live_src
    assert "metadata" not in live_src.split("UPDATE system_alerts")[1].split("balance")[0]
