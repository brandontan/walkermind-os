"""Orchestration admin API routes — Priority 6 Phase C (sections 41–42).

All routes require ORCHESTRATION_ADMIN_TOKEN via X-Orchestration-Admin-Token header.
Routes read/mutate app.state.orchestration_service (OrchestratorService).
Returns 503 when the service is not wired (DB not connected at startup).

Routes:
  GET  /admin/orchestration/wallets                     — CrossWalletState snapshot
  GET  /admin/orchestration/wallets/{wallet_id}         — per-wallet WalletHealthStatus
  POST /admin/orchestration/wallets/{wallet_id}/enable  — enable wallet
  POST /admin/orchestration/wallets/{wallet_id}/disable — disable wallet
  POST /admin/orchestration/halt                        — set global halt
  DELETE /admin/orchestration/halt                      — clear global halt
  GET  /admin/orchestration/decisions                   — recent decision log
"""
from __future__ import annotations

import os
from typing import Any

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

log = structlog.get_logger(__name__)

_DEFAULT_SCOPE_TENANT = "system"
_DEFAULT_SCOPE_USER = "paper_user"


def build_orchestration_router() -> APIRouter:
    """Build and return the orchestration admin API router."""
    router = APIRouter(prefix="/admin/orchestration", tags=["orchestration-admin"])

    def _get_service(request: Request) -> Any:
        return getattr(request.app.state, "orchestration_service", None)

    def _check_admin(request: Request) -> bool:
        admin_token = os.environ.get("ORCHESTRATION_ADMIN_TOKEN", "")
        request_token = request.headers.get("X-Orchestration-Admin-Token", "")
        return bool(admin_token) and request_token == admin_token

    # ── GET /admin/orchestration/wallets ──────────────────────────────────────

    @router.get("/wallets")
    async def get_wallet_state(request: Request) -> JSONResponse:
        """Return unified CrossWalletState snapshot for the operator scope."""
        if not _check_admin(request):
            return JSONResponse(
                status_code=403,
                content={"status": "forbidden", "reason": "invalid_or_missing_admin_token"},
            )
        svc = _get_service(request)
        if svc is None:
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "reason": "orchestration_service_not_wired"},
            )
        try:
            state = await svc.aggregate(
                tenant_id=_DEFAULT_SCOPE_TENANT,
                user_id=_DEFAULT_SCOPE_USER,
            )
            return JSONResponse(content={
                "status": "ok",
                "cross_wallet_state": {
                    "tenant_id": state.tenant_id,
                    "user_id": state.user_id,
                    "wallet_count": state.wallet_count,
                    "active_count": state.active_count,
                    "total_exposure_pct": state.total_exposure_pct,
                    "max_drawdown_pct": state.max_drawdown_pct,
                    "has_conflict": state.has_conflict,
                    "conflict_reasons": list(state.conflict_reasons),
                    "wallets": [
                        {
                            "wallet_id": w.wallet_id,
                            "lifecycle_status": w.lifecycle_status,
                            "is_enabled": w.is_enabled,
                            "risk_state": w.risk_state,
                            "drawdown_pct": w.drawdown_pct,
                            "exposure_pct": w.exposure_pct,
                        }
                        for w in state.wallets
                    ],
                    "aggregated_at": state.aggregated_at.isoformat(),
                },
            })
        except Exception as exc:
            log.error("orchestration_route_get_wallets_error", error=str(exc))
            return JSONResponse(
                status_code=500,
                content={"status": "error", "reason": str(exc)},
            )

    # ── GET /admin/orchestration/wallets/{wallet_id} ──────────────────────────

    @router.get("/wallets/{wallet_id}")
    async def get_wallet_health(request: Request, wallet_id: str) -> JSONResponse:
        """Return per-wallet WalletHealthStatus."""
        if not _check_admin(request):
            return JSONResponse(
                status_code=403,
                content={"status": "forbidden", "reason": "invalid_or_missing_admin_token"},
            )
        svc = _get_service(request)
        if svc is None:
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "reason": "orchestration_service_not_wired"},
            )
        try:
            state = await svc.aggregate(
                tenant_id=_DEFAULT_SCOPE_TENANT,
                user_id=_DEFAULT_SCOPE_USER,
            )
            health = next((w for w in state.wallets if w.wallet_id == wallet_id), None)
            if health is None:
                return JSONResponse(
                    status_code=404,
                    content={"status": "not_found", "wallet_id": wallet_id},
                )
            return JSONResponse(content={
                "status": "ok",
                "wallet": {
                    "wallet_id": health.wallet_id,
                    "lifecycle_status": health.lifecycle_status,
                    "is_enabled": health.is_enabled,
                    "risk_state": health.risk_state,
                    "drawdown_pct": health.drawdown_pct,
                    "exposure_pct": health.exposure_pct,
                    "last_updated": health.last_updated.isoformat(),
                },
            })
        except Exception as exc:
            log.error("orchestration_route_get_wallet_health_error", error=str(exc))
            return JSONResponse(
                status_code=500,
                content={"status": "error", "reason": str(exc)},
            )

    # ── POST /admin/orchestration/wallets/{wallet_id}/enable ─────────────────

    @router.post("/wallets/{wallet_id}/enable")
    async def enable_wallet(request: Request, wallet_id: str) -> JSONResponse:
        """Enable a wallet for routing selection."""
        if not _check_admin(request):
            return JSONResponse(
                status_code=403,
                content={"status": "forbidden", "reason": "invalid_or_missing_admin_token"},
            )
        svc = _get_service(request)
        if svc is None:
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "reason": "orchestration_service_not_wired"},
            )
        try:
            result, persist_ok = await svc.enable_wallet(
                tenant_id=_DEFAULT_SCOPE_TENANT,
                user_id=_DEFAULT_SCOPE_USER,
                wallet_id=wallet_id,
            )
            if not persist_ok:
                log.error("orchestration_route_enable_wallet_persist_failed", wallet_id=wallet_id)
                return JSONResponse(
                    status_code=500,
                    content={
                        "status": "error",
                        "reason": "wallet_controls_persist_failed",
                        "wallet_id": wallet_id,
                        "action": "enable",
                    },
                )
            return JSONResponse(content={
                "status": "ok",
                "wallet_id": result.wallet_id,
                "action": result.action,
                "reason": result.reason,
            })
        except Exception as exc:
            log.error("orchestration_route_enable_wallet_error", error=str(exc))
            return JSONResponse(
                status_code=500,
                content={"status": "error", "reason": str(exc)},
            )

    # ── POST /admin/orchestration/wallets/{wallet_id}/disable ────────────────

    @router.post("/wallets/{wallet_id}/disable")
    async def disable_wallet(request: Request, wallet_id: str) -> JSONResponse:
        """Disable a wallet from routing selection."""
        if not _check_admin(request):
            return JSONResponse(
                status_code=403,
                content={"status": "forbidden", "reason": "invalid_or_missing_admin_token"},
            )
        svc = _get_service(request)
        if svc is None:
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "reason": "orchestration_service_not_wired"},
            )
        try:
            body: dict[str, Any] = {}
            try:
                body = await request.json()
            except Exception:
                pass
            reason = str(body.get("reason", "")) if body else ""
            result, persist_ok = await svc.disable_wallet(
                tenant_id=_DEFAULT_SCOPE_TENANT,
                user_id=_DEFAULT_SCOPE_USER,
                wallet_id=wallet_id,
                reason=reason,
            )
            if not persist_ok:
                log.error("orchestration_route_disable_wallet_persist_failed", wallet_id=wallet_id)
                return JSONResponse(
                    status_code=500,
                    content={
                        "status": "error",
                        "reason": "wallet_controls_persist_failed",
                        "wallet_id": wallet_id,
                        "action": "disable",
                    },
                )
            return JSONResponse(content={
                "status": "ok",
                "wallet_id": result.wallet_id,
                "action": result.action,
                "reason": result.reason,
            })
        except Exception as exc:
            log.error("orchestration_route_disable_wallet_error", error=str(exc))
            return JSONResponse(
                status_code=500,
                content={"status": "error", "reason": str(exc)},
            )

    # ── POST /admin/orchestration/halt ────────────────────────────────────────

    @router.post("/halt")
    async def set_halt(request: Request) -> JSONResponse:
        """Set global halt — blocks all routing until cleared."""
        if not _check_admin(request):
            return JSONResponse(
                status_code=403,
                content={"status": "forbidden", "reason": "invalid_or_missing_admin_token"},
            )
        svc = _get_service(request)
        if svc is None:
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "reason": "orchestration_service_not_wired"},
            )
        try:
            body: dict[str, Any] = {}
            try:
                body = await request.json()
            except Exception:
                pass
            reason = str(body.get("reason", "operator halt")) if body else "operator halt"
            persist_ok = await svc.set_global_halt(
                tenant_id=_DEFAULT_SCOPE_TENANT,
                user_id=_DEFAULT_SCOPE_USER,
                reason=reason,
            )
            if not persist_ok:
                log.error("orchestration_route_set_halt_persist_failed")
                return JSONResponse(
                    status_code=500,
                    content={"status": "error", "reason": "wallet_controls_persist_failed", "action": "halt_set"},
                )
            return JSONResponse(content={"status": "ok", "action": "halt_set", "reason": reason})
        except Exception as exc:
            log.error("orchestration_route_set_halt_error", error=str(exc))
            return JSONResponse(
                status_code=500,
                content={"status": "error", "reason": str(exc)},
            )

    # ── DELETE /admin/orchestration/halt ──────────────────────────────────────

    @router.delete("/halt")
    async def clear_halt(request: Request) -> JSONResponse:
        """Clear global halt — routing resumes."""
        if not _check_admin(request):
            return JSONResponse(
                status_code=403,
                content={"status": "forbidden", "reason": "invalid_or_missing_admin_token"},
            )
        svc = _get_service(request)
        if svc is None:
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "reason": "orchestration_service_not_wired"},
            )
        try:
            persist_ok = await svc.clear_global_halt(
                tenant_id=_DEFAULT_SCOPE_TENANT,
                user_id=_DEFAULT_SCOPE_USER,
            )
            if not persist_ok:
                log.error("orchestration_route_clear_halt_persist_failed")
                return JSONResponse(
                    status_code=500,
                    content={"status": "error", "reason": "wallet_controls_persist_failed", "action": "halt_cleared"},
                )
            return JSONResponse(content={"status": "ok", "action": "halt_cleared"})
        except Exception as exc:
            log.error("orchestration_route_clear_halt_error", error=str(exc))
            return JSONResponse(
                status_code=500,
                content={"status": "error", "reason": str(exc)},
            )

    # ── GET /admin/orchestration/decisions ────────────────────────────────────

    @router.get("/decisions")
    async def get_decisions(request: Request) -> JSONResponse:
        """Return recent orchestration routing decisions from the DB log."""
        if not _check_admin(request):
            return JSONResponse(
                status_code=403,
                content={"status": "forbidden", "reason": "invalid_or_missing_admin_token"},
            )
        svc = _get_service(request)
        if svc is None:
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "reason": "orchestration_service_not_wired"},
            )
        try:
            decisions = await svc.recent_decisions(
                tenant_id=_DEFAULT_SCOPE_TENANT,
                user_id=_DEFAULT_SCOPE_USER,
                limit=50,
            )
            return JSONResponse(content={"status": "ok", "decisions": decisions, "count": len(decisions)})
        except Exception as exc:
            log.error("orchestration_route_get_decisions_error", error=str(exc))
            return JSONResponse(
                status_code=500,
                content={"status": "error", "reason": str(exc)},
            )

    return router
