"""Portfolio API routes — Priority 5 Portfolio Management Logic.

Exposes portfolio summary, positions, PnL history, exposure, and
guardrail state via FastAPI routes.

All routes read from app.state.portfolio_service injected at startup.
Unauthenticated access returns 503 when service is not wired.
"""
from __future__ import annotations

import os
from typing import Any

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

log = structlog.get_logger(__name__)


def build_portfolio_router() -> APIRouter:
    """Build and return the portfolio API router."""
    router = APIRouter(prefix="/portfolio", tags=["portfolio"])

    def _get_service(request: Request) -> Any:
        return getattr(request.app.state, "portfolio_service", None)

    def _get_beta_state(request: Request) -> Any:
        return getattr(request.app.state, "crusader_runtime", None)

    # ── GET /portfolio/summary ────────────────────────────────────────────────

    @router.get("/summary")
    async def portfolio_summary(request: Request) -> JSONResponse:
        """Return current portfolio summary for the paper user."""
        svc = _get_service(request)
        if svc is None:
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "reason": "portfolio_service_not_wired"},
            )
        try:
            runtime = _get_beta_state(request)
            beta_state = getattr(runtime, "public_beta_state", None) if runtime else None

            cash_usd = float(getattr(beta_state, "wallet_cash", 0.0)) if beta_state else 0.0
            locked_usd = float(getattr(beta_state, "wallet_locked", 0.0)) if beta_state else 0.0
            equity_usd = float(getattr(beta_state, "wallet_equity", 0.0)) if beta_state else 0.0
            drawdown = float(getattr(beta_state, "drawdown", 0.0)) if beta_state else 0.0

            result = await svc.compute_summary(
                tenant_id="system",
                user_id="paper_user",
                wallet_id="paper_wallet",
                cash_usd=cash_usd,
                locked_usd=locked_usd,
                equity_usd=equity_usd,
                peak_equity=equity_usd / max(1.0 - drawdown, 0.001) if drawdown < 1.0 else equity_usd,
            )

            if result.outcome != "ok" or result.summary is None:
                return JSONResponse(
                    status_code=503,
                    content={"status": "error", "reason": result.reason},
                )

            s = result.summary
            return JSONResponse(
                content={
                    "status": "ok",
                    "summary": {
                        "user_id": s.user_id,
                        "wallet_id": s.wallet_id,
                        "cash_usd": s.cash_usd,
                        "locked_usd": s.locked_usd,
                        "equity_usd": s.equity_usd,
                        "realized_pnl": s.realized_pnl,
                        "unrealized_pnl": s.unrealized_pnl,
                        "net_pnl": s.net_pnl,
                        "drawdown": s.drawdown,
                        "exposure_pct": s.exposure_pct,
                        "position_count": s.position_count,
                        "computed_at": s.computed_at.isoformat(),
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001
            log.error("portfolio_summary_route_error", error=str(exc))
            return JSONResponse(
                status_code=500,
                content={"status": "error", "reason": "internal_error"},
            )

    # ── GET /portfolio/positions ──────────────────────────────────────────────

    @router.get("/positions")
    async def portfolio_positions(request: Request) -> JSONResponse:
        """Return open portfolio positions."""
        svc = _get_service(request)
        if svc is None:
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "reason": "portfolio_service_not_wired"},
            )
        try:
            result = await svc.compute_summary(
                tenant_id="system",
                user_id="paper_user",
                wallet_id="paper_wallet",
            )
            if result.outcome != "ok" or result.summary is None:
                return JSONResponse(
                    status_code=503,
                    content={"status": "error", "reason": result.reason},
                )
            positions = [
                {
                    "market_id": p.market_id,
                    "side": p.side,
                    "size_usd": p.size_usd,
                    "entry_price": p.entry_price,
                    "current_price": p.current_price,
                    "unrealized_pnl": p.unrealized_pnl,
                    "opened_at": p.opened_at,
                }
                for p in result.summary.positions
            ]
            return JSONResponse(
                content={
                    "status": "ok",
                    "position_count": len(positions),
                    "positions": positions,
                }
            )
        except Exception as exc:  # noqa: BLE001
            log.error("portfolio_positions_route_error", error=str(exc))
            return JSONResponse(
                status_code=500,
                content={"status": "error", "reason": "internal_error"},
            )

    # ── GET /portfolio/pnl ────────────────────────────────────────────────────

    @router.get("/pnl")
    async def portfolio_pnl(request: Request) -> JSONResponse:
        """Return PnL summary and snapshot history."""
        svc = _get_service(request)
        if svc is None:
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "reason": "portfolio_service_not_wired"},
            )
        try:
            history = await svc.get_pnl_history(
                tenant_id="system",
                user_id="paper_user",
                wallet_id="",
                limit=30,
            )
            return JSONResponse(
                content={
                    "status": "ok",
                    "snapshot_count": len(history),
                    "history": [
                        {
                            "snapshot_id": s.snapshot_id,
                            "realized_pnl": s.realized_pnl,
                            "unrealized_pnl": s.unrealized_pnl,
                            "net_pnl": s.net_pnl,
                            "equity_usd": s.equity_usd,
                            "drawdown": s.drawdown,
                            "mode": s.mode,
                            "recorded_at": s.recorded_at.isoformat(),
                        }
                        for s in history
                    ],
                }
            )
        except Exception as exc:  # noqa: BLE001
            log.error("portfolio_pnl_route_error", error=str(exc))
            return JSONResponse(
                status_code=500,
                content={"status": "error", "reason": "internal_error"},
            )

    # ── GET /portfolio/exposure ───────────────────────────────────────────────

    @router.get("/exposure")
    async def portfolio_exposure(request: Request) -> JSONResponse:
        """Return aggregated exposure report."""
        svc = _get_service(request)
        if svc is None:
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "reason": "portfolio_service_not_wired"},
            )
        try:
            runtime = _get_beta_state(request)
            beta_state = getattr(runtime, "public_beta_state", None) if runtime else None
            equity_usd = float(getattr(beta_state, "wallet_equity", 0.0)) if beta_state else 0.0

            report = await svc.aggregate_exposure(
                tenant_id="system",
                user_id="paper_user",
                equity_usd=equity_usd,
            )
            return JSONResponse(
                content={
                    "status": "ok",
                    "exposure": {
                        "total_exposure_usd": report.total_exposure_usd,
                        "exposure_pct": report.exposure_pct,
                        "market_count": report.market_count,
                        "per_market": report.per_market,
                        "computed_at": report.computed_at.isoformat(),
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001
            log.error("portfolio_exposure_route_error", error=str(exc))
            return JSONResponse(
                status_code=500,
                content={"status": "error", "reason": "internal_error"},
            )

    # ── GET /portfolio/guardrails ─────────────────────────────────────────────

    @router.get("/guardrails")
    async def portfolio_guardrails(request: Request) -> JSONResponse:
        """Return live guardrail check result."""
        svc = _get_service(request)
        if svc is None:
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "reason": "portfolio_service_not_wired"},
            )
        try:
            runtime = _get_beta_state(request)
            beta_state = getattr(runtime, "public_beta_state", None) if runtime else None

            drawdown = float(getattr(beta_state, "drawdown", 0.0)) if beta_state else 0.0
            exposure_pct = float(getattr(beta_state, "exposure", 0.0)) if beta_state else 0.0
            equity_usd = float(getattr(beta_state, "wallet_equity", 0.0)) if beta_state else 0.0
            kill_switch = bool(getattr(beta_state, "kill_switch", False)) if beta_state else False

            exposure_store = await svc._store.get_exposure_per_market(user_id="paper_user")

            check = svc.check_guardrails(
                drawdown=drawdown,
                exposure_pct=exposure_pct,
                per_market_exposure=exposure_store,
                equity_usd=equity_usd,
                kill_switch_active=kill_switch,
            )
            return JSONResponse(
                content={
                    "status": "ok",
                    "guardrails": {
                        "allowed": check.allowed,
                        "violations": list(check.violations),
                        "drawdown": check.drawdown,
                        "exposure_pct": check.exposure_pct,
                        "max_single_market_pct": check.max_single_market_pct,
                        "kill_switch_active": check.kill_switch_active,
                        "checked_at": check.checked_at.isoformat(),
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001
            log.error("portfolio_guardrails_route_error", error=str(exc))
            return JSONResponse(
                status_code=500,
                content={"status": "error", "reason": "internal_error"},
            )

    # ── GET /portfolio/admin ──────────────────────────────────────────────────

    @router.get("/admin")
    async def portfolio_admin(request: Request) -> JSONResponse:
        """Admin surface — full portfolio state snapshot. Requires PORTFOLIO_ADMIN_TOKEN."""
        admin_token = os.environ.get("PORTFOLIO_ADMIN_TOKEN", "")
        request_token = request.headers.get("X-Portfolio-Admin-Token", "")
        if not admin_token or request_token != admin_token:
            return JSONResponse(
                status_code=403,
                content={"status": "forbidden", "reason": "invalid_or_missing_admin_token"},
            )
        svc = _get_service(request)
        if svc is None:
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "reason": "portfolio_service_not_wired"},
            )
        try:
            runtime = _get_beta_state(request)
            beta_state = getattr(runtime, "public_beta_state", None) if runtime else None

            cash_usd = float(getattr(beta_state, "wallet_cash", 0.0)) if beta_state else 0.0
            locked_usd = float(getattr(beta_state, "wallet_locked", 0.0)) if beta_state else 0.0
            equity_usd = float(getattr(beta_state, "wallet_equity", 0.0)) if beta_state else 0.0
            drawdown = float(getattr(beta_state, "drawdown", 0.0)) if beta_state else 0.0
            kill_switch = bool(getattr(beta_state, "kill_switch", False)) if beta_state else False
            mode = str(getattr(beta_state, "mode", "paper")) if beta_state else "paper"

            result = await svc.compute_summary(
                tenant_id="system",
                user_id="paper_user",
                wallet_id="paper_wallet",
                cash_usd=cash_usd,
                locked_usd=locked_usd,
                equity_usd=equity_usd,
            )

            latest_snapshot = await svc.get_latest_snapshot(
                tenant_id="system",
                user_id="paper_user",
            )

            return JSONResponse(
                content={
                    "status": "ok",
                    "mode": mode,
                    "kill_switch": kill_switch,
                    "summary": {
                        "equity_usd": equity_usd,
                        "cash_usd": cash_usd,
                        "locked_usd": locked_usd,
                        "drawdown": drawdown,
                        "net_pnl": result.summary.net_pnl if result.summary else None,
                        "realized_pnl": result.summary.realized_pnl if result.summary else None,
                        "unrealized_pnl": result.summary.unrealized_pnl if result.summary else None,
                        "position_count": result.summary.position_count if result.summary else 0,
                    },
                    "last_snapshot": {
                        "snapshot_id": latest_snapshot.snapshot_id if latest_snapshot else None,
                        "recorded_at": latest_snapshot.recorded_at.isoformat() if latest_snapshot else None,
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001
            log.error("portfolio_admin_route_error", error=str(exc))
            return JSONResponse(
                status_code=500,
                content={"status": "error", "reason": "internal_error"},
            )

    return router
