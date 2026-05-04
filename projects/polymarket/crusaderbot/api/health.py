"""Health + readiness endpoints.

``GET /health`` runs every dependency check defined in
``crusaderbot.monitoring.health`` (database, Telegram, Alchemy RPC,
Alchemy WS) and returns the aggregated verdict. The endpoint is wired
into the operator-alert dispatcher: a failure observed for two
consecutive checks pages the operator (subject to a 5-minute cooldown).

``GET /ready`` is preserved for backwards compatibility with prior
Fly.io / load-balancer probes; it now mirrors the ``ready`` boolean from
the same aggregated check.
"""
from __future__ import annotations

from fastapi import APIRouter, Response

from ..monitoring import alerts as monitoring_alerts
from ..monitoring.health import run_health_checks

router = APIRouter()


@router.get("/health")
async def health(response: Response):
    result = await run_health_checks()
    # Surface degraded/down states with non-200 so external probes (Fly.io
    # http_checks) can react. ``degraded`` keeps ``ready=true`` per spec, so
    # we still report 200 there — operators are paged via the alert path.
    response.status_code = 200 if result["ready"] else 503
    # Fire-and-forget: alert delivery (Telegram retry+backoff) MUST NOT
    # extend /health latency. Cooldown + threshold gating live inside the
    # alerts module; the background task swallows + logs any failure.
    monitoring_alerts.schedule_health_record(result)
    return result


@router.get("/ready")
async def ready(response: Response):
    result = await run_health_checks()
    response.status_code = 200 if result["ready"] else 503
    return {"ready": result["ready"], "checks": result["checks"]}
