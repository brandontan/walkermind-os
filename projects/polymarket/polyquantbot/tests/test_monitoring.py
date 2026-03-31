"""Phase 11 — Observability Layer Tests.

Validates monitoring/schema.py, monitoring/metrics_exporter.py,
and monitoring/server.py.

Scenarios covered:

  OBS-01  SCHEMA — MetricsSnapshot serialises correctly to dict
  OBS-02  SCHEMA — SystemState values are correct strings
  OBS-03  EXPORTER — snapshot() returns all-None when no sources injected
  OBS-04  EXPORTER — latency_p95_ms computed correctly from MetricsValidator
  OBS-05  EXPORTER — fill_rate computed correctly from MetricsValidator
  OBS-06  EXPORTER — avg_slippage_bps pulled from FillTracker when available
  OBS-07  EXPORTER — drawdown_pct computed from PnL timeline
  OBS-08  EXPORTER — system_state RUNNING when RiskGuard not disabled
  OBS-09  EXPORTER — system_state HALTED when RiskGuard is disabled
  OBS-10  EXPORTER — snapshot() never raises even when sources have bad state
  OBS-11  EXPORTER — logging loop starts and stops cleanly
  OBS-12  EXPORTER — logging loop is idempotent (double start)
  OBS-13  SERVER   — GET /health returns {"status": "ok"}
  OBS-14  SERVER   — GET /metrics returns valid JSON matching schema fields
  OBS-15  SERVER   — GET /metrics reflects HALTED state when kill switch fired
  OBS-16  SERVER   — server failure (port in use) does NOT raise from start()
  OBS-17  EXPORTER — execution_success_rate from FillTracker aggregate
  OBS-18  EXPORTER — fill_rate returns None when no orders submitted
  OBS-19  EXPORTER — drawdown_pct returns None when PnL timeline empty
  OBS-20  SERVER   — /metrics returns 500 with JSON error when exporter raises
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

# ── Module under test ─────────────────────────────────────────────────────────

from projects.polymarket.polyquantbot.monitoring.schema import (
    MetricsSnapshot,
    SystemState,
)
from projects.polymarket.polyquantbot.monitoring.metrics_exporter import MetricsExporter
from projects.polymarket.polyquantbot.monitoring.server import MetricsServer

# ── Real source modules ───────────────────────────────────────────────────────

from projects.polymarket.polyquantbot.phase9.metrics_validator import MetricsValidator
from projects.polymarket.polyquantbot.phase8.risk_guard import RiskGuard
from projects.polymarket.polyquantbot.execution.fill_tracker import FillTracker


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_validator(**kwargs) -> MetricsValidator:
    defaults = dict(
        ev_capture_target=0.75,
        fill_rate_target=0.70,
        p95_latency_target_ms=500.0,
        max_drawdown_target=0.08,
        min_trades=30,
    )
    defaults.update(kwargs)
    return MetricsValidator(**defaults)


def _make_guard() -> RiskGuard:
    return RiskGuard(daily_loss_limit=-2000.0, max_drawdown_pct=0.08)


def _make_tracker() -> FillTracker:
    return FillTracker()


# ─────────────────────────────────────────────────────────────────────────────
# OBS-01  SCHEMA — MetricsSnapshot serialises correctly to dict
# ─────────────────────────────────────────────────────────────────────────────

def test_obs01_snapshot_to_dict():
    snap = MetricsSnapshot(
        latency_p95_ms=42.5,
        avg_slippage_bps=3.2,
        fill_rate=0.85,
        execution_success_rate=0.88,
        drawdown_pct=1.5,
        system_state=SystemState.RUNNING,
        snapshot_ts=1_700_000_000.0,
    )
    d = snap.to_dict()
    assert d["latency_p95_ms"] == 42.5
    assert d["avg_slippage_bps"] == 3.2
    assert d["fill_rate"] == 0.85
    assert d["execution_success_rate"] == 0.88
    assert d["drawdown_pct"] == 1.5
    assert d["system_state"] == "RUNNING"
    assert d["snapshot_ts"] == 1_700_000_000.0


# ─────────────────────────────────────────────────────────────────────────────
# OBS-02  SCHEMA — SystemState values
# ─────────────────────────────────────────────────────────────────────────────

def test_obs02_system_state_values():
    assert SystemState.RUNNING.value == "RUNNING"
    assert SystemState.PAUSED.value == "PAUSED"
    assert SystemState.HALTED.value == "HALTED"


# ─────────────────────────────────────────────────────────────────────────────
# OBS-03  EXPORTER — snapshot() returns all-None when no sources injected
# ─────────────────────────────────────────────────────────────────────────────

def test_obs03_snapshot_no_sources():
    exporter = MetricsExporter()
    snap = exporter.snapshot()
    assert snap.latency_p95_ms is None
    assert snap.avg_slippage_bps is None
    assert snap.fill_rate is None
    assert snap.execution_success_rate is None
    assert snap.drawdown_pct is None
    assert snap.system_state == SystemState.RUNNING
    assert snap.snapshot_ts > 0


# ─────────────────────────────────────────────────────────────────────────────
# OBS-04  EXPORTER — latency_p95_ms computed from MetricsValidator
# ─────────────────────────────────────────────────────────────────────────────

def test_obs04_latency_p95_from_validator():
    mv = _make_validator()
    # Record 20 samples: 10..200ms
    for i in range(1, 21):
        mv.record_latency(float(i * 10))

    exporter = MetricsExporter(metrics_validator=mv)
    snap = exporter.snapshot()
    assert snap.latency_p95_ms is not None
    # p95 of [10, 20, ..., 200] (20 values): index = ceil(20*0.95)-1 = ceil(19)-1 = 18 → 190
    assert snap.latency_p95_ms == 190.0


# ─────────────────────────────────────────────────────────────────────────────
# OBS-05  EXPORTER — fill_rate from MetricsValidator
# ─────────────────────────────────────────────────────────────────────────────

def test_obs05_fill_rate_from_validator():
    mv = _make_validator()
    for _ in range(10):
        mv.record_fill(filled=True)
    for _ in range(5):
        mv.record_fill(filled=False)

    exporter = MetricsExporter(metrics_validator=mv)
    snap = exporter.snapshot()
    # 10 filled / 15 submitted
    assert snap.fill_rate == pytest.approx(10 / 15, rel=1e-4)


# ─────────────────────────────────────────────────────────────────────────────
# OBS-06  EXPORTER — avg_slippage_bps from FillTracker
# ─────────────────────────────────────────────────────────────────────────────

def test_obs06_avg_slippage_from_fill_tracker():
    ft = _make_tracker()
    ft.record_submission("o1", "mkt1", "YES", 0.60, 100.0)
    ft.record_fill("o1", executed_price=0.61, filled_size=100.0)
    # slippage = (0.61 - 0.60) / 0.60 * 10000 ≈ 166.67 bps

    exporter = MetricsExporter(fill_tracker=ft)
    snap = exporter.snapshot()
    assert snap.avg_slippage_bps is not None
    assert snap.avg_slippage_bps == pytest.approx(166.67, rel=1e-3)


# ─────────────────────────────────────────────────────────────────────────────
# OBS-07  EXPORTER — drawdown_pct from PnL timeline
# ─────────────────────────────────────────────────────────────────────────────

def test_obs07_drawdown_pct():
    mv = _make_validator()
    # PnL: 0 → 100 → 50 (drawdown = 50% from peak 100)
    for pnl in [0.0, 100.0, 50.0]:
        mv.record_pnl_sample(pnl)

    exporter = MetricsExporter(metrics_validator=mv)
    snap = exporter.snapshot()
    assert snap.drawdown_pct is not None
    assert snap.drawdown_pct == pytest.approx(50.0, rel=1e-3)


# ─────────────────────────────────────────────────────────────────────────────
# OBS-08  EXPORTER — system_state RUNNING when guard healthy
# ─────────────────────────────────────────────────────────────────────────────

def test_obs08_system_state_running():
    guard = _make_guard()
    exporter = MetricsExporter(risk_guard=guard)
    snap = exporter.snapshot()
    assert snap.system_state == SystemState.RUNNING


# ─────────────────────────────────────────────────────────────────────────────
# OBS-09  EXPORTER — system_state HALTED when kill switch fired
# ─────────────────────────────────────────────────────────────────────────────

async def test_obs09_system_state_halted():
    guard = _make_guard()
    await guard.trigger_kill_switch("test_halt")
    exporter = MetricsExporter(risk_guard=guard)
    snap = exporter.snapshot()
    assert snap.system_state == SystemState.HALTED


# ─────────────────────────────────────────────────────────────────────────────
# OBS-10  EXPORTER — snapshot() never raises with bad source state
# ─────────────────────────────────────────────────────────────────────────────

def test_obs10_snapshot_never_raises():
    mock_validator_with_invalid_state = MagicMock()
    mock_validator_with_invalid_state._latency_samples_ms = None          # will cause AttributeError in sorted()
    mock_validator_with_invalid_state._orders_submitted = "not_a_number"  # will cause TypeError in division
    mock_validator_with_invalid_state._pnl_timeline = "bad"

    exporter = MetricsExporter(metrics_validator=mock_validator_with_invalid_state)
    snap = exporter.snapshot()   # must not raise
    assert snap is not None
    assert snap.system_state == SystemState.RUNNING


# ─────────────────────────────────────────────────────────────────────────────
# OBS-11  EXPORTER — logging loop starts and stops cleanly
# ─────────────────────────────────────────────────────────────────────────────

async def test_obs11_logging_loop_start_stop():
    exporter = MetricsExporter(log_interval_s=3600.0)  # long interval — won't fire
    await exporter.start_logging_loop()
    assert exporter._logging_task is not None
    assert not exporter._logging_task.done()
    await exporter.stop_logging_loop()
    assert exporter._logging_task is None


# ─────────────────────────────────────────────────────────────────────────────
# OBS-12  EXPORTER — logging loop is idempotent
# ─────────────────────────────────────────────────────────────────────────────

async def test_obs12_logging_loop_idempotent():
    exporter = MetricsExporter(log_interval_s=3600.0)
    await exporter.start_logging_loop()
    task_first = exporter._logging_task
    await exporter.start_logging_loop()   # second call — should be no-op
    assert exporter._logging_task is task_first
    await exporter.stop_logging_loop()


# ─────────────────────────────────────────────────────────────────────────────
# OBS-13  SERVER — GET /health returns {"status": "ok"}
# ─────────────────────────────────────────────────────────────────────────────

async def test_obs13_health_endpoint():
    from aiohttp.test_utils import TestClient, TestServer

    exporter = MetricsExporter()
    srv = MetricsServer(exporter=exporter)
    client = TestClient(TestServer(srv._app))
    await client.start_server()
    try:
        resp = await client.get("/health")
        assert resp.status == 200
        body = await resp.json()
        assert body == {"status": "ok"}
    finally:
        await client.close()


# ─────────────────────────────────────────────────────────────────────────────
# OBS-14  SERVER — GET /metrics returns valid JSON with schema fields
# ─────────────────────────────────────────────────────────────────────────────

async def test_obs14_metrics_endpoint_schema():
    from aiohttp.test_utils import TestClient, TestServer

    exporter = MetricsExporter()
    srv = MetricsServer(exporter=exporter)
    client = TestClient(TestServer(srv._app))
    await client.start_server()
    try:
        resp = await client.get("/metrics")
        assert resp.status == 200
        body = await resp.json()
        expected_keys = {
            "latency_p95_ms",
            "avg_slippage_bps",
            "fill_rate",
            "execution_success_rate",
            "drawdown_pct",
            "system_state",
            "snapshot_ts",
        }
        assert expected_keys.issubset(set(body.keys()))
        assert body["system_state"] == "RUNNING"
        assert isinstance(body["snapshot_ts"], float)
    finally:
        await client.close()


# ─────────────────────────────────────────────────────────────────────────────
# OBS-15  SERVER — /metrics reflects HALTED state after kill switch
# ─────────────────────────────────────────────────────────────────────────────

async def test_obs15_metrics_halted_state():
    from aiohttp.test_utils import TestClient, TestServer

    guard = _make_guard()
    await guard.trigger_kill_switch("test_obs15")
    exporter = MetricsExporter(risk_guard=guard)
    srv = MetricsServer(exporter=exporter)
    client = TestClient(TestServer(srv._app))
    await client.start_server()
    try:
        resp = await client.get("/metrics")
        body = await resp.json()
        assert body["system_state"] == "HALTED"
    finally:
        await client.close()


# ─────────────────────────────────────────────────────────────────────────────
# OBS-16  SERVER — start() does not raise on port conflict
# ─────────────────────────────────────────────────────────────────────────────

async def test_obs16_server_start_port_conflict():
    exporter = MetricsExporter()
    srv = MetricsServer(exporter=exporter, host="127.0.0.1", port=19999)
    # Patch TCPSite.start to simulate OSError (port in use)
    with patch("aiohttp.web.TCPSite.start", side_effect=OSError("address in use")):
        await srv.start()   # must not propagate the OSError
    # Server runner should be cleaned up
    assert srv._runner is None


# ─────────────────────────────────────────────────────────────────────────────
# OBS-17  EXPORTER — execution_success_rate from FillTracker aggregate
# ─────────────────────────────────────────────────────────────────────────────

def test_obs17_execution_success_rate_from_fill_tracker():
    ft = _make_tracker()
    ft.record_submission("o1", "mkt1", "YES", 0.60, 100.0)
    ft.record_fill("o1", executed_price=0.60, filled_size=100.0)
    ft.record_submission("o2", "mkt1", "NO", 0.40, 50.0)
    ft.mark_missed("o2")

    exporter = MetricsExporter(fill_tracker=ft)
    snap = exporter.snapshot()
    # 1 filled, 1 missed → 0.5 success rate
    assert snap.execution_success_rate == pytest.approx(0.5, rel=1e-4)


# ─────────────────────────────────────────────────────────────────────────────
# OBS-18  EXPORTER — fill_rate returns None when no orders
# ─────────────────────────────────────────────────────────────────────────────

def test_obs18_fill_rate_none_when_no_orders():
    mv = _make_validator()
    exporter = MetricsExporter(metrics_validator=mv)
    snap = exporter.snapshot()
    assert snap.fill_rate is None


# ─────────────────────────────────────────────────────────────────────────────
# OBS-19  EXPORTER — drawdown_pct returns None when PnL timeline empty
# ─────────────────────────────────────────────────────────────────────────────

def test_obs19_drawdown_none_when_no_pnl():
    mv = _make_validator()
    exporter = MetricsExporter(metrics_validator=mv)
    snap = exporter.snapshot()
    assert snap.drawdown_pct is None


# ─────────────────────────────────────────────────────────────────────────────
# OBS-20  SERVER — /metrics returns 500 JSON when exporter raises
# ─────────────────────────────────────────────────────────────────────────────

async def test_obs20_metrics_500_on_exporter_error():
    from aiohttp.test_utils import TestClient, TestServer

    mock_exporter_with_error = MagicMock()
    mock_exporter_with_error.snapshot.side_effect = RuntimeError("forced_error")

    srv = MetricsServer(exporter=mock_exporter_with_error)
    client = TestClient(TestServer(srv._app))
    await client.start_server()
    try:
        resp = await client.get("/metrics")
        assert resp.status == 500
        body = await resp.json()
        assert "error" in body
    finally:
        await client.close()
