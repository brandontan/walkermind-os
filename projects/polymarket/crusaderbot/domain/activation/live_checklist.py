"""R12 Live Opt-In Checklist — pre-activation gate.

Eight gates that all must pass before a user is permitted to flip
auto-trade ON in live mode. The checklist NEVER itself sets any
activation flag — it only reports readiness. Operator action remains
the sole way to set ``EXECUTION_PATH_VALIDATED`` / ``CAPITAL_MODE_CONFIRMED``
/ ``ENABLE_LIVE_TRADING`` and to grant Tier 4.

Gate order is fixed (1→8) and surfaced in the result so the Telegram
handler can render a numbered fix-list. Every evaluation writes one
``audit.log`` row with the full pass/fail snapshot for forensic replay.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

from ... import audit
from ...config import get_settings
from ...database import get_pool

logger = logging.getLogger(__name__)


# ---------------- Gate identifiers ------------------------------------------

GATE_EXECUTION_PATH_VALIDATED = "EXECUTION_PATH_VALIDATED"
GATE_CAPITAL_MODE_CONFIRMED = "CAPITAL_MODE_CONFIRMED"
GATE_ENABLE_LIVE_TRADING = "ENABLE_LIVE_TRADING"
GATE_ACTIVE_SUBACCOUNT = "active_subaccount_with_deposit"
GATE_STRATEGY_CONFIGURED = "strategy_configured"
GATE_RISK_PROFILE_CONFIGURED = "risk_profile_configured"
GATE_TWO_FACTOR_SETUP = "two_factor_setup_complete"
GATE_OPERATOR_ALLOWLIST = "operator_allowlist_approved"

GATE_ORDER: tuple[str, ...] = (
    GATE_EXECUTION_PATH_VALIDATED,
    GATE_CAPITAL_MODE_CONFIRMED,
    GATE_ENABLE_LIVE_TRADING,
    GATE_ACTIVE_SUBACCOUNT,
    GATE_STRATEGY_CONFIGURED,
    GATE_RISK_PROFILE_CONFIGURED,
    GATE_TWO_FACTOR_SETUP,
    GATE_OPERATOR_ALLOWLIST,
)

# Operator-facing fix instructions surfaced to the user when a gate fails.
# These are intentionally short — the Telegram handler concatenates them
# into a numbered list, and Markdown rendering breaks on long lines.
GATE_FIX_HINTS: dict[str, str] = {
    GATE_EXECUTION_PATH_VALIDATED:
        "Operator must set EXECUTION_PATH_VALIDATED=true after a paper→live "
        "execution-path validation pass.",
    GATE_CAPITAL_MODE_CONFIRMED:
        "Operator must set CAPITAL_MODE_CONFIRMED=true after capital sizing "
        "review.",
    GATE_ENABLE_LIVE_TRADING:
        "Operator must set ENABLE_LIVE_TRADING=true after final go-live sign-off.",
    GATE_ACTIVE_SUBACCOUNT:
        "Deposit at least one confirmed USDC transfer to your sub-account "
        "via /wallet → Deposit before enabling live trading.",
    GATE_STRATEGY_CONFIGURED:
        "Pick at least one strategy via /setup → Strategy.",
    GATE_RISK_PROFILE_CONFIGURED:
        "Pick a risk profile via /setup → Risk Profile.",
    GATE_TWO_FACTOR_SETUP:
        "Complete 2FA setup before live trading is permitted. Contact the "
        "operator until self-serve 2FA ships.",
    GATE_OPERATOR_ALLOWLIST:
        "Live trading requires operator approval (Tier 4). Request access "
        "from the operator and wait for /allowlist tier_4 approval.",
}


@dataclass
class GateOutcome:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class ChecklistResult:
    passed: bool
    failed_gates: list[str]
    ready_for_live: bool
    outcomes: list[GateOutcome] = field(default_factory=list)

    def to_audit_payload(self) -> dict:
        return {
            "passed": self.passed,
            "ready_for_live": self.ready_for_live,
            "failed_gates": list(self.failed_gates),
            "outcomes": [
                {"name": o.name, "ok": o.ok, "detail": o.detail}
                for o in self.outcomes
            ],
        }


# ---------------- Per-gate primitives ---------------------------------------


async def _gate_active_subaccount(user_id: UUID) -> GateOutcome:
    """[4] User has an active sub-account with at least one confirmed deposit."""
    pool = get_pool()
    async with pool.acquire() as conn:
        wallet = await conn.fetchrow(
            "SELECT 1 FROM wallets WHERE user_id=$1", user_id,
        )
        if wallet is None:
            return GateOutcome(GATE_ACTIVE_SUBACCOUNT, False, "no wallet")
        deposit = await conn.fetchval(
            "SELECT COUNT(*) FROM deposits "
            "WHERE user_id=$1 AND confirmed_at IS NOT NULL",
            user_id,
        )
    if int(deposit or 0) <= 0:
        return GateOutcome(
            GATE_ACTIVE_SUBACCOUNT, False, "no confirmed deposits",
        )
    return GateOutcome(GATE_ACTIVE_SUBACCOUNT, True, f"deposits={int(deposit)}")


async def _gate_strategy(user_id: UUID) -> GateOutcome:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT strategy_types FROM user_settings WHERE user_id=$1", user_id,
        )
    if row is None:
        return GateOutcome(GATE_STRATEGY_CONFIGURED, False, "no settings row")
    types = row["strategy_types"] or []
    if not list(types):
        return GateOutcome(GATE_STRATEGY_CONFIGURED, False, "empty strategy_types")
    return GateOutcome(
        GATE_STRATEGY_CONFIGURED, True, f"types={list(types)}",
    )


async def _gate_risk_profile(user_id: UUID) -> GateOutcome:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT risk_profile FROM user_settings WHERE user_id=$1", user_id,
        )
    if row is None:
        return GateOutcome(
            GATE_RISK_PROFILE_CONFIGURED, False, "no settings row",
        )
    profile = (row["risk_profile"] or "").strip()
    if not profile:
        return GateOutcome(
            GATE_RISK_PROFILE_CONFIGURED, False, "risk_profile empty",
        )
    return GateOutcome(
        GATE_RISK_PROFILE_CONFIGURED, True, f"profile={profile}",
    )


async def _gate_two_factor(user_id: UUID) -> GateOutcome:
    """[7] 2FA setup complete.

    Self-serve 2FA infrastructure does not yet exist. Until it lands, the
    gate reads ``system_settings`` for ``2fa_enabled:{user_id}`` so the
    operator can manually flip an account through after an out-of-band
    setup. Default is FALSE — the gate fails closed so live trading is
    not silently unlocked when the 2FA module ships.
    """
    pool = get_pool()
    key = f"2fa_enabled:{user_id}"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value FROM system_settings WHERE key=$1", key,
        )
    if row is None:
        return GateOutcome(GATE_TWO_FACTOR_SETUP, False, "2fa not enabled")
    raw = (row["value"] or "").strip().lower()
    if raw in {"true", "1", "yes", "on"}:
        return GateOutcome(GATE_TWO_FACTOR_SETUP, True, "2fa enabled")
    return GateOutcome(GATE_TWO_FACTOR_SETUP, False, f"2fa flag={raw!r}")


async def _gate_operator_allowlist(user_id: UUID) -> GateOutcome:
    """[8] Operator allowlist approved → users.access_tier >= 4 (Tier 4)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        tier = await conn.fetchval(
            "SELECT access_tier FROM users WHERE id=$1", user_id,
        )
    if tier is None:
        return GateOutcome(GATE_OPERATOR_ALLOWLIST, False, "user not found")
    if int(tier) >= 4:
        return GateOutcome(GATE_OPERATOR_ALLOWLIST, True, f"tier={int(tier)}")
    return GateOutcome(
        GATE_OPERATOR_ALLOWLIST, False, f"tier={int(tier)}<4",
    )


# ---------------- Public entry ----------------------------------------------


async def evaluate(user_id: UUID) -> ChecklistResult:
    """Run all eight gates in fixed order, audit the result, return it.

    Failing one gate does NOT short-circuit later gates — the user gets a
    full numbered list back and can fix everything in one pass. The gate
    routines do their own DB reads; they never share a transaction.
    """
    settings = get_settings()
    outcomes: list[GateOutcome] = []

    outcomes.append(GateOutcome(
        GATE_EXECUTION_PATH_VALIDATED,
        bool(settings.EXECUTION_PATH_VALIDATED),
        f"flag={settings.EXECUTION_PATH_VALIDATED}",
    ))
    outcomes.append(GateOutcome(
        GATE_CAPITAL_MODE_CONFIRMED,
        bool(settings.CAPITAL_MODE_CONFIRMED),
        f"flag={settings.CAPITAL_MODE_CONFIRMED}",
    ))
    outcomes.append(GateOutcome(
        GATE_ENABLE_LIVE_TRADING,
        bool(settings.ENABLE_LIVE_TRADING),
        f"flag={settings.ENABLE_LIVE_TRADING}",
    ))

    outcomes.append(await _gate_active_subaccount(user_id))
    outcomes.append(await _gate_strategy(user_id))
    outcomes.append(await _gate_risk_profile(user_id))
    outcomes.append(await _gate_two_factor(user_id))
    outcomes.append(await _gate_operator_allowlist(user_id))

    # Preserve canonical ordering when the dispatch above is reorganized.
    by_name = {o.name: o for o in outcomes}
    ordered = [by_name[name] for name in GATE_ORDER if name in by_name]
    failed = [o.name for o in ordered if not o.ok]
    passed = not failed
    result = ChecklistResult(
        passed=passed,
        failed_gates=failed,
        ready_for_live=passed,
        outcomes=ordered,
    )

    try:
        await audit.write(
            actor_role="bot",
            action="live_checklist_evaluated",
            user_id=user_id,
            payload=result.to_audit_payload(),
        )
    except Exception as exc:  # noqa: BLE001 — audit failures must not break flow
        logger.error(
            "live_checklist audit write failed user=%s err=%s", user_id, exc,
        )

    return result


def render_telegram(result: ChecklistResult) -> str:
    """Format a ``ChecklistResult`` into a Markdown-safe Telegram message."""
    if result.passed:
        return (
            "✅ *Live trading ready.*\n\n"
            "All eight activation gates passed. Toggle auto-trade in "
            "/dashboard to activate. You will be asked to type *CONFIRM* "
            "before live mode flips on."
        )
    lines: list[str] = [
        "🔒 *Live trading not yet ready.*",
        "",
        "Failed gates (must all pass before live activation):",
    ]
    failed_set = set(result.failed_gates)
    n = 0
    for outcome in result.outcomes:
        if outcome.name not in failed_set:
            continue
        n += 1
        hint = GATE_FIX_HINTS.get(outcome.name, "")
        # Wrap the gate identifier in backticks (code style) rather than
        # asterisks (bold). Gate names contain underscores, and legacy
        # Telegram Markdown reads `*name_with_underscore*` as a botched
        # italic span and rejects the whole message. Code spans treat
        # the content as a literal so the underscores survive intact.
        lines.append(f"{n}. `{outcome.name}` — {hint}")
    lines.append("")
    lines.append("Run /live_checklist again after fixing each item.")
    return "\n".join(lines)


def gate_fix_hint(name: str) -> Optional[str]:
    """Public lookup for a gate's fix hint — used by Telegram handlers."""
    return GATE_FIX_HINTS.get(name)
