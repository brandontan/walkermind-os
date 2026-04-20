from __future__ import annotations

import pytest

pytest.importorskip(
    "fastapi",
    reason="fastapi dependency is required for Phase 8.9 dependency-complete exit-criteria validation.",
)
from fastapi.testclient import TestClient

from projects.polymarket.polyquantbot.server.core.public_beta_state import STATE
from projects.polymarket.polyquantbot.server.main import create_app


def _reset_state() -> None:
    STATE.mode = "paper"
    STATE.autotrade_enabled = False
    STATE.kill_switch = False
    STATE.last_risk_reason = ""
    STATE.positions.clear()


def test_beta_status_exit_criteria_contract_is_operator_meaningful(monkeypatch) -> None:
    _reset_state()
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("FALCON_ENABLED", "false")
    app = create_app()
    with TestClient(app) as client:
        payload = client.get("/beta/status").json()

    exit_criteria = payload["exit_criteria"]
    assert payload["paper_only_execution_boundary"] is True
    assert payload["managed_beta_state"]["safely_bounded_to_paper"] is True
    assert payload["managed_beta_state"]["controllable"] is True
    assert payload["readiness_interpretation"]["live_trading_ready"] is False
    assert exit_criteria["total_checks"] >= 7
    assert exit_criteria["checks"]["paper_only_execution_boundary"]["pass"] is True
    assert exit_criteria["checks"]["known_limitations_disclosed"]["pass"] is True
    assert exit_criteria["live_trading_ready"] is False


def test_beta_admin_surface_reports_managed_state_without_live_authority(monkeypatch) -> None:
    _reset_state()
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("FALCON_ENABLED", "false")
    app = create_app()
    with TestClient(app) as client:
        payload = client.get("/beta/admin").json()

    assert payload["paper_only_execution_boundary"] is True
    assert payload["managed_beta_state"]["state"] in {"managed", "needs_attention"}
    assert payload["admin_summary"]["beta_controllable"] is True
    assert payload["admin_summary"]["live_execution_privileges_enabled"] is False
    assert payload["exit_criteria"]["live_trading_ready"] is False


def test_beta_admin_surface_exposes_required_config_truth_when_falcon_enabled(monkeypatch) -> None:
    _reset_state()
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("FALCON_ENABLED", "true")
    monkeypatch.setenv("FALCON_API_KEY", "test-key")
    app = create_app()
    with TestClient(app) as client:
        payload = client.get("/beta/admin").json()

    config_state = payload["required_config_state"]
    criteria_checks = payload["exit_criteria"]["checks"]

    assert config_state["enabled"] is True
    assert config_state["api_key_configured"] is True
    assert config_state["config_valid_for_enabled_mode"] is True
    assert criteria_checks["required_config_present"]["pass"] is True
