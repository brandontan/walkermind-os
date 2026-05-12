from projects.polymarket.crusaderbot.scripts.realtime_paper_system_validation import _guard_checks


def test_guard_checks_report_all_keys(monkeypatch):
    monkeypatch.delenv("ENABLE_LIVE_TRADING", raising=False)
    monkeypatch.setenv("USE_REAL_CLOB", "false")
    rows = _guard_checks()
    assert len(rows) == 5
    assert all(r.status == "PASSED" for r in rows)
