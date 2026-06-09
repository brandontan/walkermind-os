"""WARP-76 H2 — operator monitoring / alerting + structured trade-event logs.

Three concerns are pinned here:

1. **Operator daily-P&L summary (alert #4 — NEW).** Runtime tests of
   ``jobs.operator_daily_summary``: aggregate metrics, rendered text, the
   operator page fires with the right content, and a notify outage is
   swallowed (fail-soft). These imports need the runtime stack, so they are
   ``pytest.importorskip``-guarded — they run in CI (full deps) and skip
   cleanly in a dependency-less sandbox.

2. **All four operator alert types are WIRED (source-contract).** Read straight
   from production source (no imports, always runs) so the wiring can never
   silently regress. The "fires at runtime" proof for the three pre-existing
   alerts lives in their own suites:
     * kill-switch        → tests/test_kill_switch_broker_cancel.py
     * infra-degraded     → tests/test_router_infra_fallback.py
     * orphan reconcile   → tests/test_warp74_reconcile.py / test_live_reconcile.py
   Alert #4 (operator daily summary) is proven at runtime in section 1 above.

3. **Structured trade-event log fields (source-contract).** ``user_id`` +
   ``market_id`` + ``rule`` on open / close / scan_skip / gate_deny, in
   ``services/signal_scan/signal_scan_job.py`` and ``domain/execution/paper.py``.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

# Crusaderbot package root (…/projects/polymarket/crusaderbot), derived from this
# file's location so the source-contract checks need no runtime imports.
_PKG = Path(__file__).resolve().parent.parent


def _src(*parts: str) -> str:
    return _PKG.joinpath(*parts).read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Operator daily-P&L summary — runtime (alert #4)
# ─────────────────────────────────────────────────────────────────────────────


class _FakeConn:
    def __init__(self, row: dict) -> None:
        self._row = row

    async def fetchrow(self, *_a: Any, **_k: Any) -> dict:
        return self._row


class _FakeAcquire:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _FakeConn:
        return self._conn

    async def __aexit__(self, *_a: Any) -> bool:
        return False


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire(self._conn)


_ROW = {
    "opened_today": 12,
    "closed_today": 9,
    "wins_today": 5,
    "losses_today": 4,
    "net_delta": "3.21",
    "active_users": 4,
}


@pytest.mark.asyncio
async def test_operator_summary_collect_metrics_shape(monkeypatch) -> None:
    ods = pytest.importorskip(
        "projects.polymarket.crusaderbot.jobs.operator_daily_summary"
    )
    monkeypatch.setattr(ods, "get_pool", lambda: _FakePool(_FakeConn(_ROW)))
    m = await ods.collect_metrics()
    assert m["opened_today"] == 12
    assert m["closed_today"] == 9
    assert m["wins_today"] == 5 and m["losses_today"] == 4
    assert str(m["net_delta"]) == "3.21"
    assert m["active_users"] == 4


def test_operator_summary_format_text() -> None:
    ods = pytest.importorskip(
        "projects.polymarket.crusaderbot.jobs.operator_daily_summary"
    )
    text = ods.format_operator_summary(
        {
            "opened_today": 12,
            "closed_today": 9,
            "wins_today": 5,
            "losses_today": 4,
            "net_delta": __import__("decimal").Decimal("3.21"),
            "active_users": 4,
        }
    )
    assert "DAILY PAPER P&amp;L — OPERATOR SUMMARY" in text
    assert "opened today: <b>12</b>" in text
    assert "closed today: <b>9</b> (W <b>5</b> / L <b>4</b>)" in text
    assert "net delta: <b>+$3.21</b>" in text
    assert "active users: <b>4</b>" in text


@pytest.mark.asyncio
async def test_operator_summary_run_job_fires_alert(monkeypatch) -> None:
    ods = pytest.importorskip(
        "projects.polymarket.crusaderbot.jobs.operator_daily_summary"
    )
    pages: list[str] = []

    async def _notify(text: str, *_a: Any, **_k: Any) -> None:
        pages.append(text)

    monkeypatch.setattr(ods, "get_pool", lambda: _FakePool(_FakeConn(_ROW)))
    monkeypatch.setattr(ods.notifications, "notify_operator", _notify)
    metrics = await ods.run_job()
    assert len(pages) == 1, "operator daily summary must page exactly once"
    assert "DAILY PAPER P&amp;L — OPERATOR SUMMARY" in pages[0]
    assert "net delta: <b>+$3.21</b>" in pages[0]
    assert metrics["opened_today"] == 12


@pytest.mark.asyncio
async def test_operator_summary_notify_failure_is_fail_soft(monkeypatch) -> None:
    ods = pytest.importorskip(
        "projects.polymarket.crusaderbot.jobs.operator_daily_summary"
    )

    async def _boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("telegram down")

    monkeypatch.setattr(ods, "get_pool", lambda: _FakePool(_FakeConn(_ROW)))
    monkeypatch.setattr(ods.notifications, "notify_operator", _boom)
    # Must NOT raise — a notify outage cannot crash the scheduled sweep.
    metrics = await ods.run_job()
    assert metrics["closed_today"] == 9


# ─────────────────────────────────────────────────────────────────────────────
# 2. All four operator alert types are wired (source-contract)
# ─────────────────────────────────────────────────────────────────────────────


def test_alert_kill_switch_wired() -> None:
    s = _src("domain", "risk", "kill_switch_exec.py")
    assert "notify_operator(" in s
    assert "KILL SWITCH ACTIVATED" in s


def test_alert_infra_degraded_wired() -> None:
    s = _src("domain", "execution", "router.py")
    assert "notify_operator(" in s
    assert "LIVE INFRA DEGRADED" in s


def test_alert_orphan_reconcile_wired() -> None:
    s = _src("domain", "execution", "live_reconcile.py")
    # orphan/untracked-exposure page routed through the best-effort wrapper
    assert "_page_operator" in s
    assert "notify_operator(" in s


def test_alert_operator_daily_summary_wired() -> None:
    s = _src("jobs", "operator_daily_summary.py")
    assert "notify_operator(" in s
    assert "DAILY PAPER" in s


def test_operator_summary_registered_in_scheduler() -> None:
    s = _src("scheduler.py")
    assert "operator_daily_summary" in s
    assert "operator_daily_summary.run_job" in s


# ─────────────────────────────────────────────────────────────────────────────
# 3. Structured trade-event log fields (source-contract)
# ─────────────────────────────────────────────────────────────────────────────


def _logcall(source: str, event: str) -> str:
    """Return a window starting at the log.info("<event>", …) call.

    The trade-event log calls are single physical lines, so a fixed window
    from the event marker captures the full keyword-argument list without
    needing to balance parentheses in a regex.
    """
    marker = f'"{event}"'
    i = source.find(marker)
    assert i != -1, f"log.info({event!r}, …) not found"
    return source[i:i + 400]


def test_paper_open_log_has_user_market_rule() -> None:
    body = _logcall(_src("domain", "execution", "paper.py"), "paper_trade_open")
    assert "user_id=" in body
    assert "market_id=" in body
    assert "rule=" in body


def test_paper_close_log_has_user_market_rule() -> None:
    body = _logcall(_src("domain", "execution", "paper.py"), "paper_trade_close")
    assert "user_id=" in body
    assert "market_id=" in body
    assert "rule=" in body


def test_signal_scan_bind_has_user_market_rule() -> None:
    s = _src("services", "signal_scan", "signal_scan_job.py")
    # _process_candidate binds the per-candidate logger; every scan_outcome
    # event (accepted / rejected / skipped_*) inherits these fields.
    i = s.find("rule=cand.strategy_name")
    assert i != -1, "rule=cand.strategy_name not bound in signal_scan_job"
    window = s[max(0, i - 250):i + 50]
    assert "logger.bind(" in window
    assert "user_id=" in window
    assert "market_id=" in window
