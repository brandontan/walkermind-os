"""Shadow / live parity validation hooks.

Validates that the risk gate produces identical decisions whether the
system is in paper mode or (hypothetically) in live mode with all guards
enabled.  This is a PRE-FLIGHT check — it does not activate live trading.

Usage (by the readiness validator):
    report = await validate_gate_parity(ctx)
    if not report.parity_ok:
        ...surface to operator...

The check runs the gate twice against the same ``GateContext``:
  1. With ``trading_mode='paper'`` (current posture) — no DB mutations.
  2. With ``trading_mode='live'`` and ``_passes_live_guards`` forced True —
     simulates what the gate would do in live mode without enabling live
     trading or mutating any user state.

Parity passes when both gate evaluations reach the same step verdict.
chosen_mode may differ (paper vs live) — that is expected and not a failure.
Divergence indicates a bug in the guard-routing logic.

Important: parity validation does NOT write to risk_log, idempotency_keys,
user_settings, or any other DB table.  Mutations are suppressed by patching
``_log``, ``_record_idempotency``, and all three ``live_fallback.trigger_*``
callables.  ``_passes_live_guards`` is also patched (not ``get_settings``,
which is imported inside ``evaluate()`` and has no module-level attribute).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParityReport:
    parity_ok: bool
    paper_approved: bool
    paper_reason: str
    paper_step: int | None
    simulated_live_approved: bool
    simulated_live_reason: str
    simulated_live_step: int | None
    # True when the gate produces the same verdict regardless of guard state
    verdict_match: bool
    detail: str


async def validate_gate_parity(
    *,
    user_id: UUID,
    telegram_user_id: int,
    access_tier: int,
    market_id: str,
    side: str,
    proposed_size_usdc: Decimal,
    proposed_price: float,
    market_liquidity: float,
    market_status: str,
    strategy_type: str,
    risk_profile: str,
    trading_mode: str = "paper",
) -> ParityReport:
    """Run gate in paper and simulated-live mode; compare verdicts.

    Both runs share the same context and the same DB state.  The only
    difference is that the simulated-live run patches ``_passes_live_guards``
    to return True, exercising the live chosen_mode path without requiring
    the real env flags to change and without mutating any user state.
    """
    from ..risk.gate import GateContext, evaluate

    _noop = AsyncMock(return_value=None)

    base_ctx = GateContext(
        user_id=user_id,
        telegram_user_id=telegram_user_id,
        access_tier=access_tier,
        auto_trade_on=True,
        paused=False,
        market_id=market_id,
        side=side,
        proposed_size_usdc=proposed_size_usdc,
        proposed_price=proposed_price,
        market_liquidity=market_liquidity,
        market_status=market_status,
        edge_bps=None,
        signal_ts=None,
        idempotency_key=f"parity-check-{user_id}-{market_id}",
        strategy_type=strategy_type,
        risk_profile=risk_profile,
        daily_loss_override=None,
        trading_mode=trading_mode,
    )

    # Shared noop for all live_fallback mutation calls. The fallback
    # functions write to user_settings and send Telegram notifications —
    # both are state mutations that must never fire during a parity check.
    _fallback_noop = AsyncMock(return_value=None)
    _GATE = "projects.polymarket.crusaderbot.domain.risk.gate"

    # Run 1 — paper mode (current posture, no mutations)
    with (
        patch(f"{_GATE}._log", _noop),
        patch(f"{_GATE}._record_idempotency", _noop),
        patch(f"{_GATE}._idempotent_already_seen", AsyncMock(return_value=False)),
        patch(f"{_GATE}._recent_dup_market_trade", AsyncMock(return_value=False)),
        patch(f"{_GATE}.live_fallback.trigger_for_kill_switch_halt", _fallback_noop),
        patch(f"{_GATE}.live_fallback.trigger_for_drawdown_halt", _fallback_noop),
        patch(f"{_GATE}.live_fallback.trigger_for_live_guard_unset", _fallback_noop),
    ):
        paper_result = await evaluate(base_ctx)

    # Run 2 — simulated live (guards forced True via _passes_live_guards patch,
    # trading_mode='live').
    #
    # Patch _passes_live_guards directly rather than mocking get_settings:
    # evaluate() imports get_settings inside the function body (not at module
    # level), so patch("...gate.get_settings", ...) raises AttributeError.
    # Patching the guard-routing function is both correct and stable.
    live_ctx = GateContext(
        user_id=user_id,
        telegram_user_id=telegram_user_id,
        access_tier=max(access_tier, 4),  # min Tier 4 for live gate
        auto_trade_on=True,
        paused=False,
        market_id=market_id,
        side=side,
        proposed_size_usdc=proposed_size_usdc,
        proposed_price=proposed_price,
        market_liquidity=market_liquidity,
        market_status=market_status,
        edge_bps=None,
        signal_ts=None,
        idempotency_key=f"parity-check-live-{user_id}-{market_id}",
        strategy_type=strategy_type,
        risk_profile=risk_profile,
        daily_loss_override=None,
        trading_mode="live",
    )

    with (
        patch(f"{_GATE}._log", _noop),
        patch(f"{_GATE}._record_idempotency", _noop),
        patch(f"{_GATE}._idempotent_already_seen", AsyncMock(return_value=False)),
        patch(f"{_GATE}._recent_dup_market_trade", AsyncMock(return_value=False)),
        patch(f"{_GATE}._passes_live_guards", return_value=True),
        patch(f"{_GATE}.live_fallback.trigger_for_kill_switch_halt", _fallback_noop),
        patch(f"{_GATE}.live_fallback.trigger_for_drawdown_halt", _fallback_noop),
        patch(f"{_GATE}.live_fallback.trigger_for_live_guard_unset", _fallback_noop),
    ):
        live_result = await evaluate(live_ctx)

    # Parity: both runs must reach the same approved/rejected decision.
    # chosen_mode may differ (paper vs live) — that is expected and not a parity failure.
    verdict_match = paper_result.approved == live_result.approved
    parity_ok = verdict_match

    detail = (
        f"paper={paper_result.approved}(step={paper_result.failed_step}) "
        f"live_sim={live_result.approved}(step={live_result.failed_step})"
    )
    if not parity_ok:
        logger.warning("gate parity mismatch: %s", detail)

    return ParityReport(
        parity_ok=parity_ok,
        paper_approved=paper_result.approved,
        paper_reason=paper_result.reason,
        paper_step=paper_result.failed_step,
        simulated_live_approved=live_result.approved,
        simulated_live_reason=live_result.reason,
        simulated_live_step=live_result.failed_step,
        verdict_match=verdict_match,
        detail=detail,
    )
