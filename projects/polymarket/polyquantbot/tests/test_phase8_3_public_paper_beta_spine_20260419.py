from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from projects.polymarket.polyquantbot.server.core.public_beta_state import STATE
from projects.polymarket.polyquantbot.server.main import create_app
from projects.polymarket.polyquantbot.server.workers.paper_beta_worker import run_worker_loop


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    STATE.mode = "paper"
    STATE.autotrade_enabled = False
    STATE.kill_switch = False
    STATE.pnl = 0.0
    STATE.drawdown = 0.0
    STATE.exposure = 0.0
    STATE.last_risk_reason = ""
    STATE.positions.clear()
    STATE.processed_signals.clear()


def test_health_and_ready_routes() -> None:
    app = create_app()
    with TestClient(app) as client:
        health = client.get("/health")
        ready = client.get("/ready")
    assert health.status_code == 200
    assert ready.status_code == 200
    assert health.json()["status"] == "ok"
    assert ready.json()["status"] == "ready"


def test_beta_mode_and_kill_routes() -> None:
    app = create_app()
    with TestClient(app) as client:
        mode = client.post("/beta/mode", json={"mode": "paper"})
        kill = client.post("/beta/kill", json={})
        status = client.get("/beta/status")
    assert mode.status_code == 200
    assert kill.status_code == 200
    assert status.json()["kill_switch"] is True


@pytest.mark.asyncio
async def test_worker_boot_smoke() -> None:
    await run_worker_loop(iterations=1)
    assert isinstance(STATE.positions, list)
