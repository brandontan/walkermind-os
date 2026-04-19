"""Public paper beta control routes used by Telegram control shell."""
from __future__ import annotations

import structlog
from fastapi import APIRouter
from pydantic import BaseModel

from projects.polymarket.polyquantbot.server.core.public_beta_state import STATE
from projects.polymarket.polyquantbot.server.integrations.falcon_gateway import FalconGateway

log = structlog.get_logger(__name__)


class ModeRequest(BaseModel):
    mode: str


class ToggleRequest(BaseModel):
    enabled: bool


def build_public_beta_router(falcon: FalconGateway) -> APIRouter:
    router = APIRouter(prefix="/beta", tags=["beta"])

    @router.get("/status")
    async def status() -> dict[str, object]:
        return {
            "mode": STATE.mode,
            "autotrade": STATE.autotrade_enabled,
            "kill_switch": STATE.kill_switch,
            "position_count": len(STATE.positions),
            "last_risk_reason": STATE.last_risk_reason,
        }

    @router.post("/mode")
    async def set_mode(payload: ModeRequest) -> dict[str, object]:
        mode = payload.mode.strip().lower()
        if mode not in {"paper", "live"}:
            return {"ok": False, "detail": "mode must be paper or live"}
        previous_mode = STATE.mode
        STATE.mode = mode
        if mode == "live":
            STATE.autotrade_enabled = False
            STATE.last_risk_reason = "mode_live_paper_execution_disabled"
        log.info(
            "public_beta_mode_changed",
            previous_mode=previous_mode,
            mode=STATE.mode,
            autotrade_enabled=STATE.autotrade_enabled,
            execution_boundary="paper_only",
        )
        return {
            "ok": True,
            "mode": STATE.mode,
            "execution_boundary": "paper_only",
            "detail": "live mode is control-plane state only in this phase; execution remains paper-only.",
        }

    @router.post("/autotrade")
    async def set_autotrade(payload: ToggleRequest) -> dict[str, object]:
        if STATE.mode == "live" and payload.enabled:
            STATE.last_risk_reason = "mode_live_paper_execution_disabled"
            log.info(
                "public_beta_autotrade_rejected",
                mode=STATE.mode,
                requested_enabled=True,
                reason="mode_live_paper_execution_disabled",
            )
            return {
                "ok": False,
                "autotrade": False,
                "detail": "autotrade cannot be enabled while mode=live in paper-beta runtime.",
            }
        STATE.autotrade_enabled = bool(payload.enabled)
        log.info("public_beta_autotrade_updated", autotrade_enabled=STATE.autotrade_enabled, mode=STATE.mode)
        return {"ok": True, "autotrade": STATE.autotrade_enabled}

    @router.post("/kill")
    async def kill() -> dict[str, object]:
        STATE.kill_switch = True
        STATE.autotrade_enabled = False
        STATE.last_risk_reason = "kill_switch_enabled"
        log.info("public_beta_kill_switch_activated", kill_switch=True, autotrade_enabled=False)
        return {"ok": True, "kill_switch": True}

    @router.get("/positions")
    async def positions() -> dict[str, object]:
        return {"items": [p.__dict__ for p in STATE.positions]}

    @router.get("/pnl")
    async def pnl() -> dict[str, object]:
        return {"pnl": STATE.pnl}

    @router.get("/risk")
    async def risk() -> dict[str, object]:
        return {
            "drawdown": STATE.drawdown,
            "exposure": STATE.exposure,
            "last_reason": STATE.last_risk_reason,
            "kill_switch": STATE.kill_switch,
            "autotrade_enabled": STATE.autotrade_enabled,
        }

    @router.get("/markets")
    async def markets(query: str = "") -> dict[str, object]:
        return {"items": await falcon.list_markets(query=query)}

    @router.get("/market360/{condition_id}")
    async def market360(condition_id: str) -> dict[str, object]:
        return await falcon.market_360(condition_id=condition_id)

    @router.get("/social")
    async def social(topic: str) -> dict[str, object]:
        return await falcon.social(topic=topic)

    return router
