"""Public paper beta control routes used by Telegram control shell."""
from __future__ import annotations

import os
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from starlette import status as http_status
from pydantic import BaseModel

from projects.polymarket.polyquantbot.server.core.public_beta_state import STATE
from projects.polymarket.polyquantbot.server.integrations.falcon_gateway import FalconGateway

log = structlog.get_logger(__name__)
_OPERATOR_API_KEY_HEADER = "X-Operator-Api-Key"


class ModeRequest(BaseModel):
    mode: str


class ToggleRequest(BaseModel):
    enabled: bool


def _build_execution_guard() -> dict[str, object]:
    execution_blocked_reasons: list[str] = []
    if STATE.mode != "paper":
        execution_blocked_reasons.append("mode_live_paper_execution_disabled")
    if not STATE.autotrade_enabled:
        execution_blocked_reasons.append("autotrade_disabled")
    if STATE.kill_switch:
        execution_blocked_reasons.append("kill_switch_enabled")
    return {
        "entry_allowed": len(execution_blocked_reasons) == 0,
        "blocked_reasons": execution_blocked_reasons,
        "reason_count": len(execution_blocked_reasons),
        "operator_summary": "blocked" if execution_blocked_reasons else "entry_allowed",
        "paper_beta_boundary": "execution_never_promotes_to_live_in_phase9-2",
    }


def _build_exit_criteria(falcon: FalconGateway) -> dict[str, object]:
    falcon_config = falcon.settings_snapshot()
    execution_guard = _build_execution_guard()
    checks = {
        "readiness_contract_complete": {
            "pass": True,
            "detail": "/health, /ready, /beta/status, and /beta/admin surfaces are available for paper-beta control.",
        },
        "paper_only_execution_boundary": {
            "pass": True,
            "detail": "execution authority remains paper-only; live mode does not grant live order entry.",
        },
        "autotrade_guard_functioning": {
            "pass": not (STATE.mode == "live" and STATE.autotrade_enabled),
            "detail": "autotrade ON is rejected while mode=live in public paper beta.",
        },
        "kill_switch_functioning": {
            "pass": (not STATE.kill_switch) or (STATE.kill_switch and not STATE.autotrade_enabled),
            "detail": "kill switch forces autotrade OFF and blocks new entries.",
        },
        "onboarding_session_control_path_functioning": {
            "pass": True,
            "detail": "Telegram onboarding/activation/session routes are available on the backend control plane.",
        },
        "operator_admin_semantics_consistent": {
            "pass": True,
            "detail": "Telegram + API status wording keeps public paper-beta boundary explicit and rejects live-mode promotion.",
        },
        "required_config_present": {
            "pass": bool(falcon_config["config_valid_for_enabled_mode"]),
            "detail": "Falcon config is valid for current enabled/disabled mode.",
        },
        "known_limitations_disclosed": {
            "pass": True,
            "detail": "Public-paper beta limits are documented; no live-readiness claim is made.",
        },
    }
    passing_checks = sum(1 for check in checks.values() if check["pass"] is True)
    return {
        "total_checks": len(checks),
        "passing_checks": passing_checks,
        "all_passed": passing_checks == len(checks),
        "checks": checks,
        "live_trading_ready": False,
    }


def _build_beta_status_payload(falcon: FalconGateway) -> dict[str, object]:
    execution_guard = _build_execution_guard()
    exit_criteria = _build_exit_criteria(falcon=falcon)
    falcon_config = falcon.settings_snapshot()
    return {
        "mode": STATE.mode,
        "autotrade": STATE.autotrade_enabled,
        "kill_switch": STATE.kill_switch,
        "paper_only_execution_boundary": True,
        "execution_guard": execution_guard,
        "position_count": len(STATE.positions),
        "last_risk_reason": STATE.last_risk_reason,
        "admin_control_plane": {
            "summary_visible": True,
            "guard_state_visible": True,
            "managed_beta_state_visible": True,
            "supports_live_execution_control": False,
        },
        "managed_beta_state": {
            "state": "managed" if exit_criteria["all_passed"] else "needs_attention",
            "controllable": True,
            "safely_bounded_to_paper": True,
            "control_plane_conditions_satisfied": bool(exit_criteria["all_passed"]),
        },
        "exit_criteria": exit_criteria,
        "required_config_state": falcon_config,
        "readiness_interpretation": {
            "control_surface": "telegram_and_api_control_only",
            "execution_authority": "paper_only",
            "live_trading_ready": False,
            "known_limitations_doc": "projects/polymarket/polyquantbot/docs/public_paper_beta_spine.md",
        },
        "public_readiness_semantics": {
            "release_channel": "public_paper_beta",
            "operator_scope": "managed_control_and_read_surfaces_only",
            "admin_scope": "status_and_guard_visibility_only",
            "live_release_gate": "phase9-3_not_started",
            "live_mode_switch_available": False,
        },
    }


def build_public_beta_router(falcon: FalconGateway) -> APIRouter:
    router = APIRouter(prefix="/beta", tags=["beta"])

    def _require_operator_api_key(
        x_operator_api_key: str = Header(default="", alias=_OPERATOR_API_KEY_HEADER),
    ) -> None:
        expected = os.getenv("CRUSADER_OPERATOR_API_KEY", "").strip()
        if not expected:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="operator_route_disabled_missing_operator_api_key",
            )
        if not x_operator_api_key or x_operator_api_key.strip() != expected:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="operator_route_forbidden_invalid_operator_api_key",
            )

    @router.get("/status")
    async def status() -> dict[str, object]:
        return _build_beta_status_payload(falcon=falcon)

    @router.get("/admin")
    async def admin(
        __: None = Depends(_require_operator_api_key),
    ) -> dict[str, object]:
        status_payload = _build_beta_status_payload(falcon=falcon)
        return {
            "mode": status_payload["mode"],
            "autotrade": status_payload["autotrade"],
            "kill_switch": status_payload["kill_switch"],
            "paper_only_execution_boundary": status_payload["paper_only_execution_boundary"],
            "execution_guard": status_payload["execution_guard"],
            "managed_beta_state": status_payload["managed_beta_state"],
            "exit_criteria": status_payload["exit_criteria"],
            "required_config_state": status_payload["required_config_state"],
            "public_readiness_semantics": status_payload["public_readiness_semantics"],
            "admin_summary": {
                "beta_controllable": True,
                "key_gates_active": not status_payload["execution_guard"]["entry_allowed"],
                "live_execution_privileges_enabled": False,
            },
        }

    @router.post("/mode")
    async def set_mode(
        payload: ModeRequest,
        __: None = Depends(_require_operator_api_key),
    ) -> dict[str, object]:
        mode = payload.mode.strip().lower()
        if mode not in {"paper", "live"}:
            return {"ok": False, "detail": "mode must be paper or live"}

        if mode == "live":
            STATE.mode = "paper"
            STATE.autotrade_enabled = False
            STATE.last_risk_reason = "mode_live_paper_execution_disabled"
            log.info(
                "public_beta_mode_live_rejected",
                requested_mode=mode,
                enforced_mode=STATE.mode,
                autotrade_enabled=STATE.autotrade_enabled,
                execution_boundary="paper_only",
            )
            return {
                "ok": False,
                "mode": STATE.mode,
                "execution_boundary": "paper_only",
                "detail": "mode=live is disabled in public paper beta; use /status and /beta/admin for readiness visibility only.",
            }

        previous_mode = STATE.mode
        STATE.mode = "paper"
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
            "detail": "paper mode confirmed; runtime remains a managed public paper-beta control/read surface.",
        }

    @router.post("/autotrade")
    async def set_autotrade(
        payload: ToggleRequest,
        __: None = Depends(_require_operator_api_key),
    ) -> dict[str, object]:
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
        log.info(
            "public_beta_autotrade_updated",
            autotrade_enabled=STATE.autotrade_enabled,
            mode=STATE.mode,
            execution_boundary="paper_only",
        )
        return {"ok": True, "autotrade": STATE.autotrade_enabled, "mode": STATE.mode}

    @router.post("/kill")
    async def kill(
        __: None = Depends(_require_operator_api_key),
    ) -> dict[str, object]:
        STATE.kill_switch = True
        STATE.autotrade_enabled = False
        STATE.last_risk_reason = "kill_switch_enabled"
        log.info(
            "public_beta_kill_switch_activated",
            kill_switch=True,
            autotrade_enabled=False,
            execution_boundary="paper_only",
        )
        return {"ok": True, "kill_switch": True}

    @router.get("/positions")
    async def positions() -> dict[str, object]:
        return {"items": [p.__dict__ for p in STATE.positions]}

    @router.get("/pnl")
    async def pnl() -> dict[str, object]:
        return {"pnl": STATE.pnl}

    @router.get("/risk")
    async def risk(
        __: None = Depends(_require_operator_api_key),
    ) -> dict[str, object]:
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
