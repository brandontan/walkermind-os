"""Strategy scan observability (WARP-80 sub-lane 1a).

Per-scan-tick near-miss instrumentation for the two opportunistic strategies
(``weather`` + ``playbook``) that book zero entries by design. For every market
that reaches a binding edge filter the strategy records HOW FAR it was from
passing (``distance_to_threshold``) and whether it WOULD pass at relaxed
thresholds (``would_pass_at_threshold`` at -10% / -25% / -50%), plus the
``module_state`` (live vs dark/null-feed). The rows land in
``strategy_scan_observations`` so the threshold-tuning analysis (sub-lane 1b)
can be done from the DB without Fly DEBUG-log access.

Design contract — observability only, zero trading effect:

* Strategies push observations via :func:`record_observation`, which is a no-op
  unless the scan job has opened a sink for the current tick (:func:`begin_sink`).
  The sink is a :class:`contextvars.ContextVar` list, so it is async-safe and
  visible to child tasks spawned by ``asyncio.gather`` (weather fans out per
  city) without threading any new parameter through ``BaseStrategy.scan``.
* Every public function is fail-soft — a recording or write error is swallowed
  and never propagates into the scan/selection path.
* The scan job drains the sink once per tick and persists it alongside
  ``_finish_scan_run`` (one batched, append-only INSERT).
"""
from __future__ import annotations

import json
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any

import structlog

from ...database import get_pool

logger = structlog.get_logger(__name__)

# Threshold-relaxation levels reported per observation. A market that fails a
# gate today is checked against the same gate relaxed by each fraction so 1b can
# count hypothetical entries at each level straight from the DB.
RELAX_LEVELS: tuple[float, ...] = (0.10, 0.25, 0.50)

# Per-tick observation sink. None = no sink open → record_observation is a no-op.
_SINK: ContextVar[list["ScanObservation"] | None] = ContextVar(
    "strategy_scan_observation_sink", default=None
)


@dataclass
class ScanObservation:
    """One near-miss / abstain reading for a single market in a scan tick."""

    strategy: str
    market_id: str
    zero_reason: str | None = None
    binding_filter: str | None = None
    metric_value: float | None = None
    threshold: float | None = None
    distance_to_threshold: float | None = None
    would_pass_at_threshold: dict[str, bool] = field(default_factory=dict)
    module_state: str | None = None


def threshold_pass_map(
    metric_value: float,
    threshold: float,
    *,
    direction: str = "min",
) -> dict[str, bool]:
    """Would ``metric_value`` pass ``threshold`` relaxed by each RELAX_LEVELS step?

    ``direction='min'`` — a floor gate (pass iff value >= threshold); relaxing
    lowers the floor (key ``"-10%"`` etc.).
    ``direction='max'`` — a ceiling gate (pass iff value <= threshold); relaxing
    raises the ceiling (key ``"+10%"`` etc.).
    """
    out: dict[str, bool] = {}
    for lv in RELAX_LEVELS:
        pct = int(round(lv * 100))
        if direction == "max":
            out[f"+{pct}%"] = metric_value <= threshold * (1.0 + lv)
        else:
            out[f"-{pct}%"] = metric_value >= threshold * (1.0 - lv)
    return out


def signed_distance(
    metric_value: float,
    threshold: float,
    *,
    direction: str = "min",
) -> float:
    """Signed gap toward passing: >= 0 passes, < 0 fails by that magnitude.

    For a floor gate (``min``) this is ``value - threshold``; for a ceiling gate
    (``max``) it is ``threshold - value``.
    """
    return (threshold - metric_value) if direction == "max" else (metric_value - threshold)


def begin_sink() -> Token | None:
    """Open a fresh observation sink for the current tick; return its reset token.

    Fail-soft: returns ``None`` if a sink cannot be opened (the strategies then
    simply record nothing). Always installs a NEW list so a prior tick that
    crashed before draining cannot accumulate rows here.
    """
    try:
        return _SINK.set([])
    except Exception:  # noqa: BLE001 — observability must never break the scan loop
        return None


def record_observation(obs: "ScanObservation") -> None:
    """Append ``obs`` to the active sink, or no-op if none is open. Fail-soft."""
    try:
        sink = _SINK.get()
        if sink is not None:
            sink.append(obs)
    except Exception:  # noqa: BLE001 — never propagate into the strategy scan path
        pass


def drain_sink(token: Token | None) -> list["ScanObservation"]:
    """Return the collected observations and reset the sink to its prior state."""
    try:
        sink = _SINK.get() or []
    except Exception:  # noqa: BLE001
        sink = []
    try:
        if token is not None:
            _SINK.reset(token)
        else:
            _SINK.set(None)
    except Exception:  # noqa: BLE001
        pass
    return list(sink)


def _row(scan_run_id: str | None, obs: "ScanObservation") -> tuple | None:
    """Map one observation to an INSERT row tuple, or None if unusable."""
    if not obs.market_id or not obs.strategy:
        return None
    return (
        scan_run_id,
        str(obs.strategy)[:32],
        str(obs.market_id)[:100],
        (str(obs.zero_reason)[:48] if obs.zero_reason else None),
        (str(obs.binding_filter)[:32] if obs.binding_filter else None),
        (float(obs.metric_value) if obs.metric_value is not None else None),
        (float(obs.threshold) if obs.threshold is not None else None),
        (float(obs.distance_to_threshold) if obs.distance_to_threshold is not None else None),
        json.dumps(obs.would_pass_at_threshold or {}, default=str),
        (str(obs.module_state)[:16] if obs.module_state else None),
    )


async def record_scan_observations(
    scan_run_id: str | None,
    observations: list["ScanObservation"],
    *,
    pool: Any | None = None,
) -> int:
    """Persist a row per observation for this scan tick. Returns rows written.

    Fail-soft: any error logs and returns 0 — the scan loop is never broken.
    """
    if not observations:
        return 0
    rows = [r for r in (_row(scan_run_id, o) for o in observations) if r]
    if not rows:
        return 0
    try:
        pool = pool or get_pool()
        async with pool.acquire() as conn:  # type: ignore[attr-defined]
            await conn.executemany(
                """
                INSERT INTO strategy_scan_observations
                    (scan_run_id, strategy, market_id, zero_reason, binding_filter,
                     metric_value, threshold, distance_to_threshold,
                     would_pass_at_threshold, module_state, observed_at)
                VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, NOW())
                """,
                rows,
            )
    except Exception as exc:  # noqa: BLE001 — fail-soft, never break the scan loop
        logger.warning("strategy_scan_observation_write_failed", error=str(exc))
        return 0
    return len(rows)


__all__ = [
    "ScanObservation",
    "RELAX_LEVELS",
    "threshold_pass_map",
    "signed_distance",
    "begin_sink",
    "record_observation",
    "drain_sink",
    "record_scan_observations",
]
