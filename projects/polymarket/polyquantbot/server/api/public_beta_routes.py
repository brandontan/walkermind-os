"""Public paper beta control routes used by Telegram control shell."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from projects.polymarket.polyquantbot.server.core.public_beta_state import STATE
from projects.polymarket.polyquantbot.server.integrations.falcon_gateway import FalconGateway


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
            "positions": len(STATE.positions),
            "pnl": STATE.pnl,
            "risk": {
                "drawdown": STATE.drawdown,
                "exposure": STATE.exposure,
                "last_reason": STATE.last_risk_reason,
            },
        }

    @router.post("/mode")
    async def set_mode(payload: ModeRequest) -> dict[str, object]:
        mode = payload.mode.strip().lower()
        if mode not in {"paper", "live"}:
            return {"ok": False, "detail": "mode must be paper or live"}
        STATE.mode = mode
        return {"ok": True, "mode": STATE.mode}

    @router.post("/autotrade")
    async def set_autotrade(payload: ToggleRequest) -> dict[str, object]:
        STATE.autotrade_enabled = bool(payload.enabled)
        return {"ok": True, "autotrade": STATE.autotrade_enabled}

    @router.post("/kill")
    async def kill() -> dict[str, object]:
        STATE.kill_switch = True
        STATE.autotrade_enabled = False
        return {"ok": True, "kill_switch": True}

    @router.get("/positions")
    async def positions() -> dict[str, object]:
        return {"items": [p.__dict__ for p in STATE.positions]}

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
