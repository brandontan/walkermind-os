from __future__ import annotations

import os
import secrets
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel

from projects.polymarket.polyquantbot.server.settlement.schemas import AdminInterventionRequest

log = structlog.get_logger(__name__)


class AdminInterventionBody(BaseModel):
    workflow_id: str
    action: str
    admin_user_id: str
    reason: str


def build_settlement_operator_router() -> APIRouter:
    router = APIRouter(prefix="/admin/settlement", tags=["settlement-admin"])

    def _check_admin(request: Request) -> None:
        token = request.headers.get("X-Settlement-Admin-Token", "")
        expected = os.environ.get("SETTLEMENT_ADMIN_TOKEN", "")
        if not expected or not secrets.compare_digest(token, expected):
            raise HTTPException(status_code=403, detail="forbidden")

    @router.get("/status/{workflow_id}")
    async def get_settlement_status(
        workflow_id: str,
        request: Request,
        _: None = Depends(_check_admin),
    ) -> dict:
        svc = getattr(request.app.state, "settlement_operator_service", None)
        if svc is None:
            raise HTTPException(
                status_code=503, detail="settlement_operator_service_not_ready"
            )
        try:
            result = await svc.get_settlement_status(workflow_id)
            return {"ok": True, "data": jsonable_encoder(result)}
        except Exception as exc:
            log.exception("settlement_status_route_error", workflow_id=workflow_id)
            raise HTTPException(status_code=500, detail="settlement_status_error") from exc

    @router.get("/retry/{workflow_id}")
    async def get_retry_status(
        workflow_id: str,
        request: Request,
        _: None = Depends(_check_admin),
    ) -> dict:
        svc = getattr(request.app.state, "settlement_operator_service", None)
        if svc is None:
            raise HTTPException(
                status_code=503, detail="settlement_operator_service_not_ready"
            )
        try:
            result = await svc.get_retry_status(workflow_id)
            return {"ok": True, "data": jsonable_encoder(result)}
        except Exception as exc:
            log.exception("settlement_retry_route_error", workflow_id=workflow_id)
            raise HTTPException(status_code=500, detail="settlement_retry_error") from exc

    @router.get("/failed-batches")
    async def get_failed_batches(
        request: Request,
        _: None = Depends(_check_admin),
    ) -> dict:
        svc = getattr(request.app.state, "settlement_operator_service", None)
        if svc is None:
            raise HTTPException(
                status_code=503, detail="settlement_operator_service_not_ready"
            )
        try:
            result = await svc.get_failed_batches()
            return {"ok": True, "data": jsonable_encoder(list(result))}
        except Exception as exc:
            log.exception("settlement_failed_batches_route_error")
            raise HTTPException(status_code=500, detail="settlement_failed_batches_error") from exc

    @router.post("/intervene")
    async def apply_admin_intervention(
        body: AdminInterventionBody,
        request: Request,
        _: None = Depends(_check_admin),
    ) -> dict:
        svc = getattr(request.app.state, "settlement_operator_service", None)
        if svc is None:
            raise HTTPException(
                status_code=503, detail="settlement_operator_service_not_ready"
            )
        try:
            intervention = AdminInterventionRequest(
                workflow_id=body.workflow_id,
                action=body.action,
                admin_user_id=body.admin_user_id,
                reason=body.reason,
            )
            result = await svc.apply_admin_intervention(intervention)
            if result is None:
                raise HTTPException(
                    status_code=404, detail="workflow_not_found"
                )
            return {"ok": True, "data": jsonable_encoder(result)}
        except HTTPException:
            raise
        except Exception as exc:
            log.exception(
                "settlement_intervene_route_error",
                workflow_id=body.workflow_id,
                action=body.action,
            )
            raise HTTPException(status_code=500, detail="settlement_intervene_error") from exc

    return router
