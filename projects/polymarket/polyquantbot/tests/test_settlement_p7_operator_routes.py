"""Priority 7 — Settlement Operator Routes — Tests.

Test IDs: ST-39 .. ST-47

Coverage:
  ST-39  GET /admin/settlement/status returns 403 on missing token
  ST-40  GET /admin/settlement/retry returns 403 on wrong token
  ST-41  GET /admin/settlement/status returns 503 when service not wired
  ST-42  GET /admin/settlement/retry returns 503 when service not wired
  ST-43  GET /admin/settlement/status/{id} returns SettlementStatusView shape
  ST-44  GET /admin/settlement/retry/{id} returns RetryStatusView shape
  ST-45  GET /admin/settlement/failed-batches returns list
  ST-46  POST /admin/settlement/intervene returns AdminInterventionResult shape
  ST-47  POST /admin/settlement/intervene returns 404 when workflow not found
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from projects.polymarket.polyquantbot.server.api.settlement_operator_routes import (
    build_settlement_operator_router,
)
from projects.polymarket.polyquantbot.server.settlement.schemas import (
    AdminInterventionResult,
    FailedBatchView,
    RetryStatusView,
    SettlementStatusView,
)

_TOKEN = "test_settlement_token"
_HEADERS = {"X-Settlement-Admin-Token": _TOKEN}


def _utc() -> datetime:
    return datetime(2026, 4, 28, 10, 0, 0, tzinfo=timezone.utc)


def _make_app(svc=None) -> TestClient:
    app = FastAPI()
    app.include_router(build_settlement_operator_router())
    if svc is not None:
        app.state.settlement_operator_service = svc
    return TestClient(app, raise_server_exceptions=False)


def _mock_status_view(workflow_id: str = "wf_001") -> SettlementStatusView:
    return SettlementStatusView(
        workflow_id=workflow_id,
        status="NOT_FOUND",
        amount=0.0,
        currency="USD",
        wallet_id="",
        mode="paper",
        retry_attempt_count=0,
        created_at=_utc(),
        updated_at=_utc(),
    )


def _mock_retry_view(workflow_id: str = "wf_001") -> RetryStatusView:
    return RetryStatusView(
        workflow_id=workflow_id,
        current_attempt=0,
        max_attempts=5,
        last_outcome="none",
        is_exhausted=False,
        is_fatal=False,
    )


def _mock_intervention_result(workflow_id: str = "wf_001") -> AdminInterventionResult:
    return AdminInterventionResult(
        workflow_id=workflow_id,
        action="force_cancel",
        success=True,
        previous_status="PROCESSING",
        new_status="CANCELLED",
    )


def _make_svc(**overrides):
    svc = MagicMock()
    svc.get_settlement_status = AsyncMock(
        return_value=overrides.get("status", _mock_status_view())
    )
    svc.get_retry_status = AsyncMock(
        return_value=overrides.get("retry", _mock_retry_view())
    )
    svc.get_failed_batches = AsyncMock(
        return_value=overrides.get("batches", [])
    )
    svc.apply_admin_intervention = AsyncMock(
        return_value=overrides.get("intervention", _mock_intervention_result())
    )
    return svc


# ── ST-39: 403 on missing token ───────────────────────────────────────────────

def test_st_39_status_requires_token():
    """ST-39: GET /admin/settlement/status returns 403 when token is absent."""
    client = _make_app()
    resp = client.get("/admin/settlement/status/wf_001")
    assert resp.status_code == 403


# ── ST-40: 403 on wrong token ─────────────────────────────────────────────────

def test_st_40_retry_wrong_token_returns_403():
    """ST-40: GET /admin/settlement/retry returns 403 when token is incorrect."""
    with patch.dict("os.environ", {"SETTLEMENT_ADMIN_TOKEN": _TOKEN}):
        client = _make_app()
        resp = client.get(
            "/admin/settlement/retry/wf_001",
            headers={"X-Settlement-Admin-Token": "wrong_token"},
        )
    assert resp.status_code == 403


# ── ST-41: 503 when service not wired (status) ────────────────────────────────

def test_st_41_status_503_when_not_wired():
    """ST-41: GET /admin/settlement/status returns 503 when service absent from app.state."""
    with patch.dict("os.environ", {"SETTLEMENT_ADMIN_TOKEN": _TOKEN}):
        client = _make_app(svc=None)
        resp = client.get(
            "/admin/settlement/status/wf_001",
            headers=_HEADERS,
        )
    assert resp.status_code == 503


# ── ST-42: 503 when service not wired (retry) ─────────────────────────────────

def test_st_42_retry_503_when_not_wired():
    """ST-42: GET /admin/settlement/retry returns 503 when service absent from app.state."""
    with patch.dict("os.environ", {"SETTLEMENT_ADMIN_TOKEN": _TOKEN}):
        client = _make_app(svc=None)
        resp = client.get(
            "/admin/settlement/retry/wf_001",
            headers=_HEADERS,
        )
    assert resp.status_code == 503


# ── ST-43: Status route returns SettlementStatusView shape ────────────────────

def test_st_43_status_route_returns_view_shape():
    """ST-43: GET /admin/settlement/status/{id} returns ok=True and view fields."""
    with patch.dict("os.environ", {"SETTLEMENT_ADMIN_TOKEN": _TOKEN}):
        client = _make_app(svc=_make_svc())
        resp = client.get(
            "/admin/settlement/status/wf_001",
            headers=_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["workflow_id"] == "wf_001"
    assert data["status"] == "NOT_FOUND"
    assert "retry_attempt_count" in data
    assert "created_at" in data


# ── ST-44: Retry route returns RetryStatusView shape ──────────────────────────

def test_st_44_retry_route_returns_view_shape():
    """ST-44: GET /admin/settlement/retry/{id} returns ok=True and view fields."""
    with patch.dict("os.environ", {"SETTLEMENT_ADMIN_TOKEN": _TOKEN}):
        client = _make_app(svc=_make_svc())
        resp = client.get(
            "/admin/settlement/retry/wf_001",
            headers=_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["workflow_id"] == "wf_001"
    assert data["current_attempt"] == 0
    assert data["max_attempts"] == 5
    assert data["is_exhausted"] is False


# ── ST-45: Failed-batches returns list ────────────────────────────────────────

def test_st_45_failed_batches_returns_list():
    """ST-45: GET /admin/settlement/failed-batches returns ok=True with list data."""
    with patch.dict("os.environ", {"SETTLEMENT_ADMIN_TOKEN": _TOKEN}):
        client = _make_app(svc=_make_svc(batches=[]))
        resp = client.get(
            "/admin/settlement/failed-batches",
            headers=_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert isinstance(body["data"], list)


# ── ST-46: Intervene returns AdminInterventionResult shape ────────────────────

def test_st_46_intervene_returns_result_shape():
    """ST-46: POST /admin/settlement/intervene returns ok=True and intervention fields."""
    with patch.dict("os.environ", {"SETTLEMENT_ADMIN_TOKEN": _TOKEN}):
        client = _make_app(svc=_make_svc())
        resp = client.post(
            "/admin/settlement/intervene",
            headers=_HEADERS,
            json={
                "workflow_id": "wf_001",
                "action": "force_cancel",
                "admin_user_id": "op_01",
                "reason": "test intervention",
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["workflow_id"] == "wf_001"
    assert data["action"] == "force_cancel"
    assert data["success"] is True


# ── ST-47: Intervene returns 404 when workflow not found ──────────────────────

def test_st_47_intervene_404_when_workflow_not_found():
    """ST-47: POST /admin/settlement/intervene returns 404 when service returns None."""
    svc = _make_svc(intervention=None)
    svc.apply_admin_intervention = AsyncMock(return_value=None)
    with patch.dict("os.environ", {"SETTLEMENT_ADMIN_TOKEN": _TOKEN}):
        client = _make_app(svc=svc)
        resp = client.post(
            "/admin/settlement/intervene",
            headers=_HEADERS,
            json={
                "workflow_id": "wf_missing",
                "action": "force_cancel",
                "admin_user_id": "op_01",
                "reason": "test",
            },
        )
    assert resp.status_code == 404
    assert "workflow_not_found" in resp.json().get("detail", "")
