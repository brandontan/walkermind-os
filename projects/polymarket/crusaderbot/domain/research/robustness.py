"""Module robustness classification + LIVE-eligibility gate (Phase-2c §12.2).

Reads each strategy module's realized PnL distribution from closed ``positions``,
runs the Monte Carlo simulator, and classifies the module:

* **ROBUST** — positive EV, ruin probability negligible, P95 drawdown within the
  8% circuit-breaker.
* **FRAGILE** — positive EV but P95 drawdown approaches the halt or losing-streak
  risk is high → size down / restrict.
* **UNTRADEABLE** — non-positive EV or unacceptable ruin probability → paper-only.
* **INSUFFICIENT_DATA** — sample below the minimum; verdict withheld (never blocks).

``live_eligible`` is the gate the activation layer can consult: an UNTRADEABLE
module is not eligible for live capital; everything else (including unclassified /
insufficient) is allowed so the gate can never silently disable an existing flow.
Pure analytics — no execution, no risk authority. Fail-soft on every DB touch.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import structlog

from ...database import get_pool
from ..risk.constants import MAX_DRAWDOWN_HALT, PROFILES
from .monte_carlo import MCResult, simulate

logger = structlog.get_logger(__name__)

# Classification thresholds (blueprint §12.2; tunable as data accrues).
MIN_SAMPLE_SIZE: int = 30        # below → INSUFFICIENT_DATA (no verdict)
RUIN_PROB_MAX: float = 0.05      # ruin prob above this → UNTRADEABLE
FRAGILE_STREAK: int = 8          # P95 losing streak at/above this → FRAGILE


class Classification(str, Enum):
    ROBUST = "ROBUST"
    FRAGILE = "FRAGILE"
    UNTRADEABLE = "UNTRADEABLE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True)
class ModuleRobustness:
    module: str
    risk_profile: str
    classification: Classification
    sample_size: int
    ev_per_trade: float
    ruin_probability: float
    p95_max_drawdown: float
    p95_losing_streak: int
    mode: str


def classify(
    mc: MCResult,
    *,
    drawdown_halt: float = MAX_DRAWDOWN_HALT,
    min_sample: int = MIN_SAMPLE_SIZE,
) -> Classification:
    """Map a Monte Carlo result to a robustness class."""
    if mc.sample_size < min_sample:
        return Classification.INSUFFICIENT_DATA
    if mc.ev_per_trade <= 0.0 or mc.ruin_probability > RUIN_PROB_MAX:
        return Classification.UNTRADEABLE
    if mc.p95_max_drawdown >= drawdown_halt or mc.p95_losing_streak >= FRAGILE_STREAK:
        return Classification.FRAGILE
    return Classification.ROBUST


def _bet_fraction(risk_profile: str) -> float:
    """Per-trade equity fraction for a profile (its max-position cap)."""
    profile = PROFILES.get(risk_profile) or PROFILES["balanced"]
    return float(profile["max_pos_pct"])


async def classify_modules(
    *,
    risk_profile: str = "balanced",
    mode: str = "paper",
    persist: bool = True,
    seed: int | None = None,
    pool: object | None = None,
) -> list[ModuleRobustness]:
    """Classify every module that has closed positions in ``mode``.

    Groups closed positions by module (PLAYBOOK uses the per-module
    ``strategy_metadata.selected_module``, others fall back to ``strategy_type``),
    derives each trade's realized return fraction (``pnl_usdc / size_usdc``), runs
    the simulator at the profile's sizing, and classifies. Persists the latest
    verdict per (module, profile, mode) unless ``persist=False``. Fail-soft: on a
    read error returns an empty list (the scan/gate path is never broken).
    """
    try:
        pool = pool or get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT COALESCE(
                         NULLIF(strategy_metadata->>'selected_module', ''),
                         strategy_type, 'unknown'
                       ) AS module,
                       pnl_usdc, size_usdc
                  FROM positions
                 WHERE status = 'closed'
                   AND pnl_usdc IS NOT NULL
                   AND size_usdc > 0
                   AND ($1::text IS NULL OR mode = $1)
                """,
                mode,
            )
    except Exception as exc:  # noqa: BLE001 — fail-soft analytics read
        logger.warning("robustness_classify_read_failed", error=str(exc))
        return []

    grouped: dict[str, list[float]] = {}
    for r in rows:
        size = float(r["size_usdc"] or 0.0)
        if size <= 0.0:
            continue
        grouped.setdefault(str(r["module"]), []).append(float(r["pnl_usdc"] or 0.0) / size)

    bet = _bet_fraction(risk_profile)
    results = [
        ModuleRobustness(
            module=module,
            risk_profile=risk_profile,
            classification=classify(mc := simulate(returns, bet_fraction=bet, seed=seed)),
            sample_size=mc.sample_size,
            ev_per_trade=mc.ev_per_trade,
            ruin_probability=mc.ruin_probability,
            p95_max_drawdown=mc.p95_max_drawdown,
            p95_losing_streak=mc.p95_losing_streak,
            mode=mode,
        )
        for module, returns in sorted(grouped.items())
    ]
    if persist and results:
        await _persist(pool, results)
    return results


async def _persist(pool: object, results: list[ModuleRobustness]) -> None:
    """Upsert the latest verdict per (module, risk_profile, mode). Fail-soft."""
    try:
        async with pool.acquire() as conn:  # type: ignore[attr-defined]
            await conn.executemany(
                """
                INSERT INTO module_robustness
                    (module, risk_profile, classification, sample_size, ev_per_trade,
                     ruin_probability, p95_max_drawdown, p95_losing_streak, mode, computed_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
                ON CONFLICT (module, risk_profile, mode) DO UPDATE SET
                    classification    = EXCLUDED.classification,
                    sample_size       = EXCLUDED.sample_size,
                    ev_per_trade      = EXCLUDED.ev_per_trade,
                    ruin_probability  = EXCLUDED.ruin_probability,
                    p95_max_drawdown  = EXCLUDED.p95_max_drawdown,
                    p95_losing_streak = EXCLUDED.p95_losing_streak,
                    computed_at       = NOW()
                """,
                [
                    (
                        r.module, r.risk_profile, r.classification.value, r.sample_size,
                        r.ev_per_trade, r.ruin_probability, r.p95_max_drawdown,
                        r.p95_losing_streak, r.mode or "all",  # mode NOT NULL; None = all modes
                    )
                    for r in results
                ],
            )
    except Exception as exc:  # noqa: BLE001 — fail-soft; classification still returned
        logger.warning("robustness_persist_failed", error=str(exc))


async def live_eligible(
    module: str,
    *,
    risk_profile: str = "balanced",
    mode: str = "paper",
    pool: object | None = None,
) -> tuple[bool, str]:
    """LIVE-eligibility gate for a module.

    Returns ``(eligible, reason)``. Only an **UNTRADEABLE** verdict withholds live
    capital; ROBUST / FRAGILE / INSUFFICIENT_DATA / unclassified all return
    eligible (so the gate can never silently disable an existing live flow — it
    only blocks a module proven unsafe). Fail-soft: a read error allows.

    ``mode`` selects which sample's classification to honour (default ``paper`` —
    paper history is the meaningful sample for a not-yet-live module). The table
    is unique per (module, risk_profile, mode), so the filter keeps the verdict
    deterministic rather than depending on which job ran last.
    """
    try:
        pool = pool or get_pool()
        async with pool.acquire() as conn:  # type: ignore[attr-defined]
            row = await conn.fetchrow(
                """
                SELECT classification FROM module_robustness
                 WHERE module = $1 AND risk_profile = $2 AND mode = $3
                 ORDER BY computed_at DESC
                 LIMIT 1
                """,
                module, risk_profile, mode,
            )
    except Exception as exc:  # noqa: BLE001 — never block live on a read error
        logger.warning("robustness_gate_read_failed", module=module, error=str(exc))
        return True, "gate_read_failed_allow"

    if row is None:
        return True, "unclassified_allow"
    cls = str(row["classification"])
    if cls == Classification.UNTRADEABLE.value:
        return False, "untradeable_paper_only"
    return True, cls.lower()


ROBUSTNESS_JOB_ID = "robustness_classify"
_JOB_PROFILES: tuple[str, ...] = ("conservative", "balanced", "aggressive")


async def run_job() -> None:
    """Scheduled refresh — recompute + persist robustness verdicts for the
    standard risk profiles from paper trade history. Fail-soft: ``classify_modules``
    swallows its own DB errors (→ empty); the per-profile guard is belt-and-braces
    so one profile's failure never aborts the rest. Registered in the scheduler
    only when ``ROBUSTNESS_CLASSIFY_ENABLED`` is on.
    """
    for profile in _JOB_PROFILES:
        try:
            results = await classify_modules(risk_profile=profile, mode="paper")
            logger.info(
                "robustness_classified",
                profile=profile,
                modules=len(results),
                untradeable=sum(
                    1 for r in results if r.classification == Classification.UNTRADEABLE
                ),
            )
        except Exception as exc:  # noqa: BLE001 — never let one profile abort the job
            logger.warning("robustness_job_failed", profile=profile, error=str(exc))


__all__ = [
    "Classification",
    "ModuleRobustness",
    "classify",
    "classify_modules",
    "live_eligible",
    "run_job",
    "ROBUSTNESS_JOB_ID",
    "MIN_SAMPLE_SIZE",
    "RUIN_PROB_MAX",
    "FRAGILE_STREAK",
]
