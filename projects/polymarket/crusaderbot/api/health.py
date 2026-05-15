"""Health + readiness endpoints.

``GET /health`` runs every dependency check defined in
``crusaderbot.monitoring.health`` (database, Telegram, Alchemy RPC,
Alchemy WS) and returns the aggregated verdict. The endpoint is wired
into the operator-alert dispatcher: a failure observed for two
consecutive checks pages the operator (subject to a 5-minute cooldown).

The response payload includes both:
  - the R12b deep-dependency keys (``service``, ``checks``, ``ready``)
    used by the alert dispatcher and existing probes; and
  - the demo-readiness keys (``status``, ``uptime_seconds``, ``version``,
    ``mode``, ``timestamp``) consumed by Fly.io HTTP health checks and
    the operator dashboard.

``mode`` reads the three operator activation guards
(``ENABLE_LIVE_TRADING``, ``EXECUTION_PATH_VALIDATED``,
``CAPITAL_MODE_CONFIRMED``) and reports ``"paper"`` whenever any of them
is unset — i.e. the runtime is locked to paper unless ALL three are
explicitly opened. This is the same contract the risk gate enforces.

``GET /ready`` is preserved for backwards compatibility with prior
Fly.io / load-balancer probes; it now mirrors the ``ready`` boolean from
the same aggregated check.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Response

from ..config import get_settings
from ..monitoring import alerts as monitoring_alerts
from ..monitoring.health import run_health_checks

router = APIRouter()

# Captured once at module import so /health reports time since process boot.
_PROCESS_START_MONOTONIC: float = time.monotonic()


def _uptime_seconds() -> int:
    return int(time.monotonic() - _PROCESS_START_MONOTONIC)


def _resolve_mode() -> str:
    """Return ``"paper"`` unless every operator activation guard is open.

    Mirrors the contract documented in the issue brief: the runtime
    advertises ``paper`` whenever any of the three activation guards
    (ENABLE_LIVE_TRADING, EXECUTION_PATH_VALIDATED, CAPITAL_MODE_CONFIRMED)
    is unset. Live mode requires ALL three explicitly True.
    """
    s = get_settings()
    if s.ENABLE_LIVE_TRADING and s.EXECUTION_PATH_VALIDATED and s.CAPITAL_MODE_CONFIRMED:
        return "live"
    return "paper"


def _extract_fly_image_id(image_ref: str) -> str | None:
    """Pull a stable, deploy-distinct identifier out of ``FLY_IMAGE_REF``.

    Fly populates ``FLY_IMAGE_REF`` on every machine with the full image
    reference, typically::

        registry.fly.io/<app>:deployment-01H4D7M0J3K2P5N1Q8R6S9T2X4

    The deployment ULID portion is unique per release, so it satisfies
    the "version differs across releases" check the rollback runbook
    relies on. ``deployment-`` prefix is stripped so the surfaced id is
    the bare ULID. Returns ``None`` for empty / unset input.
    """
    s = (image_ref or "").strip()
    if not s:
        return None
    tag = s.rsplit(":", 1)[-1] if ":" in s else s
    if tag.startswith("deployment-"):
        tag = tag[len("deployment-"):]
    return tag or None


def _resolve_version() -> str:
    """Return the deployed build identifier, or ``"unknown"``.

    Resolution order:

    1. ``APP_VERSION`` — preferred. Stamped by the CD workflow at deploy
       time with the git short SHA (see
       ``.github/workflows/crusaderbot-cd.yml``).
    2. ``FLY_IMAGE_REF`` — Fly's documented machine runtime variable
       (``https://fly.io/docs/machines/runtime-environment/``). The
       deployment ULID portion is extracted and surfaced as
       ``fly-<ulid>`` so consumers can distinguish it from a git SHA at
       a glance. Provides a stable identifier when ``APP_VERSION`` is
       missing because the deploy went through manual ``flyctl deploy``
       rather than the CD workflow.
    3. ``"unknown"`` — neither variable is set (local dev, broken deploy).

    Defense-in-depth: the rollback runbook step ``flyctl deploy --image
    <previous-image>`` does NOT inherit the CD workflow's git-SHA
    stamping, so the ``FLY_IMAGE_REF`` fallback ensures the runbook's
    ``/health .version`` differs across releases even when the rolled-back
    Docker image is bit-identical to the prior known-good — the new Fly
    release entry gets a fresh deployment ULID.
    """
    app_version = (get_settings().APP_VERSION or "").strip()
    if app_version:
        return app_version
    fly_image_id = _extract_fly_image_id(os.environ.get("FLY_IMAGE_REF", ""))
    if fly_image_id:
        return f"fly-{fly_image_id}"
    return "unknown"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
    # Demo-readiness fields layered on top of the R12b deep-deps result.
    # Order is preserved so manual JSON inspection sees the operational
    # summary first.
    return {
        "status": result["status"],
        "uptime_seconds": _uptime_seconds(),
        "version": _resolve_version(),
        "mode": _resolve_mode(),
        "timestamp": _now_iso(),
        "service": result["service"],
        "checks": result["checks"],
        "ready": result["ready"],
    }


@router.get("/ready")
async def ready(response: Response):
    result = await run_health_checks()
    response.status_code = 200 if result["ready"] else 503
    return {"ready": result["ready"], "checks": result["checks"]}
