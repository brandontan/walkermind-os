"""Rolling short-window price-momentum / repricing signal for candle candidates.

WARP-72 Phase 1 (WARP•R00T, SHADOW-only). The audit (WARP-71) found momentum is
NOT measured: ``ask_diff`` is an *instantaneous* lean threshold, not a momentum
signal. This module provides a real, tested, short-window **repricing velocity**:
how fast the favored-probability (YES mid) is moving per second over a rolling
window, sampled across successive scan ticks.

Boundary contract (identical to the oracle advisory):
    * pure / I-O-free math (``compute_momentum``) — unit-testable with no state;
    * the tracker is in-process telemetry state only;
    * NOTHING here selects, sizes, gates, or blocks a trade. It only produces a
      scorable input + a logged dataset for the Phase-2 scorer.

Concurrency: asyncio-only runtime — both scan loops (``run_once`` 180s and
``run_close_sweep_fast`` ~15s) run as tasks on the SAME event loop, so the
module-level tracker is touched from one loop at a time. No threading, no locks.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Iterable, Optional

import structlog

log = structlog.get_logger(__name__)

# Short-window default. The fast candle loop (~15s) samples an in-window market a
# handful of times across its entry window; 60s captures a 2-4 point velocity for
# the wider windows (flip_hunter 180s / safe_close 60s) and a 2-point velocity for
# close_sweep's narrow 35s window. Tunable by the caller / future scorer.
DEFAULT_WINDOW_SEC: float = 60.0
# Per-market ring cap (bounds memory regardless of scan cadence).
DEFAULT_MAX_SAMPLES: int = 64
# De-dup intra-tick: candle_auto scans EACH rule for the same market in one tick,
# which would otherwise record 3 near-identical samples at ~the same wall-clock.
MIN_RECORD_GAP_SEC: float = 1.0
# Retain a little beyond the window so a late sample can still find an anchor.
_RETENTION_FACTOR: float = 3.0
# Hard cap on tracked markets (candle slugs churn one-per-slot); evict idle keys.
DEFAULT_MAX_KEYS: int = 512


@dataclass(frozen=True)
class PriceSample:
    """A single (wall-clock seconds, price) observation."""

    ts: float
    price: float


@dataclass(frozen=True)
class MomentumReading:
    """Result of a rolling-window momentum computation.

    ``velocity`` is signed price-units per second (the repricing rate);
    ``delta`` is the raw price change across the window span. Positive =
    the tracked probability (YES mid) is rising over the window.
    """

    velocity: float
    delta: float
    span_sec: float
    samples: int
    newest_price: float
    oldest_price: float


def compute_momentum(
    samples: Iterable[PriceSample],
    *,
    window_sec: float,
    now: float,
) -> Optional[MomentumReading]:
    """Pure rolling-window momentum. Returns ``None`` when not measurable.

    Considers only samples within ``[now - window_sec, now]``. Needs >= 2 points
    spanning a positive time interval; otherwise momentum is undefined (``None``)
    — the honest "not enough history yet" case, never a fabricated zero.
    """
    if window_sec <= 0:
        return None
    lo = now - window_sec
    window = [s for s in samples if lo <= s.ts <= now and math.isfinite(s.price)]
    if len(window) < 2:
        return None
    window.sort(key=lambda s: s.ts)
    oldest, newest = window[0], window[-1]
    span = newest.ts - oldest.ts
    if span <= 0.0:
        return None
    delta = newest.price - oldest.price
    return MomentumReading(
        velocity=delta / span,
        delta=delta,
        span_sec=span,
        samples=len(window),
        newest_price=newest.price,
        oldest_price=oldest.price,
    )


def compute_realized_vol(
    samples: Iterable[PriceSample],
    *,
    window_sec: float,
    now: float,
) -> Optional[float]:
    """Pure rolling-window realized volatility (per sqrt-second). ``None`` if undefined.

    WARP-78 Phase 1: a REAL volatility measure to replace the dead per-asset
    constant ``volatility_sigma`` (Phase-0 found it collapses to weight 0). Over the
    consecutive log-returns in ``[now - window_sec, now]`` this returns the
    realized-variance estimator ``sigma = sqrt( sum(r_i^2) / sum(dt_i) )`` where
    ``r_i = ln(p_i / p_{i-1})`` and ``dt_i`` is the inter-sample seconds — units are
    per-sqrt-second, directly comparable to the config ``volatility_sigma``.

    Needs >= 3 in-window samples (>= 2 returns) spanning positive time; otherwise
    ``None`` (the honest "not enough history" case, never a fabricated zero). A
    flat (non-moving) series yields exactly ``0.0`` — that IS the measurement.
    """
    if window_sec <= 0:
        return None
    lo = now - window_sec
    window = [
        s for s in samples
        if lo <= s.ts <= now and math.isfinite(s.price) and s.price > 0.0
    ]
    if len(window) < 3:
        return None
    window.sort(key=lambda s: s.ts)
    sum_r2 = 0.0
    sum_dt = 0.0
    for prev, cur in zip(window, window[1:]):
        dt = cur.ts - prev.ts
        if dt <= 0.0:
            continue
        r = math.log(cur.price / prev.price)
        if not math.isfinite(r):
            continue
        sum_r2 += r * r
        sum_dt += dt
    if sum_dt <= 0.0:
        return None
    sigma = math.sqrt(sum_r2 / sum_dt)
    return sigma if math.isfinite(sigma) else None


class MomentumTracker:
    """In-process rolling price history per market, with momentum readout.

    Telemetry state only. ``record`` is idempotent within ``min_gap_sec`` so the
    candle_auto multi-rule scan of one market in a single tick adds one sample,
    not three. Memory is bounded by the per-key ring (``max_samples``), a window
    retention prune, and an idle-key eviction cap (``max_keys``).
    """

    def __init__(
        self,
        *,
        window_sec: float = DEFAULT_WINDOW_SEC,
        max_samples: int = DEFAULT_MAX_SAMPLES,
        min_gap_sec: float = MIN_RECORD_GAP_SEC,
        max_keys: int = DEFAULT_MAX_KEYS,
    ) -> None:
        self.window_sec = float(window_sec)
        self._max_samples = int(max_samples)
        self._min_gap_sec = float(min_gap_sec)
        self._max_keys = int(max_keys)
        self._retention_sec = self.window_sec * _RETENTION_FACTOR
        self._hist: Dict[str, Deque[PriceSample]] = {}

    def record(self, key: str, price: Optional[float], *, now: float) -> None:
        """Append a price sample for ``key`` (fail-soft; never raises)."""
        try:
            if not key or price is None:
                return
            p = float(price)
            if not math.isfinite(p) or p <= 0.0:
                return
            dq = self._hist.get(key)
            if dq is None:
                if len(self._hist) >= self._max_keys:
                    self._evict_idle(now)
                dq = deque(maxlen=self._max_samples)
                self._hist[key] = dq
            # Intra-tick de-dup: skip a sample taken within min_gap of the last.
            if dq and (now - dq[-1].ts) < self._min_gap_sec:
                return
            dq.append(PriceSample(ts=float(now), price=p))
            cutoff = now - self._retention_sec
            while dq and dq[0].ts < cutoff:
                dq.popleft()
        except Exception as exc:  # telemetry must never break a scan
            log.debug("momentum record failed (telemetry, non-blocking)", err=str(exc))

    def momentum(
        self,
        key: str,
        *,
        now: float,
        window_sec: Optional[float] = None,
    ) -> Optional[MomentumReading]:
        """Rolling momentum for ``key`` over ``window_sec`` (defaults to tracker)."""
        dq = self._hist.get(key)
        if not dq:
            return None
        return compute_momentum(
            list(dq), window_sec=window_sec or self.window_sec, now=now
        )

    def realized_vol(
        self,
        key: str,
        *,
        now: float,
        window_sec: Optional[float] = None,
    ) -> Optional[float]:
        """Rolling realized volatility (per sqrt-sec) for ``key``; ``None`` if undefined.

        Reads the SAME per-market price ring as :meth:`momentum` (WARP-78 Phase 1).
        """
        dq = self._hist.get(key)
        if not dq:
            return None
        return compute_realized_vol(
            list(dq), window_sec=window_sec or self.window_sec, now=now
        )

    def _evict_idle(self, now: float) -> None:
        """Drop idle keys; strictly enforce the hard key cap.

        First removes keys whose newest sample is older than the retention
        window. If high active churn leaves the map still at/above capacity (no
        idle keys to drop), defensively evict the single oldest-updated key so
        ``_hist`` can never grow unboundedly.
        """
        cutoff = now - self._retention_sec
        stale = [k for k, dq in self._hist.items() if not dq or dq[-1].ts < cutoff]
        for k in stale:
            self._hist.pop(k, None)
        if len(self._hist) >= self._max_keys:
            oldest = min(
                self._hist,
                key=lambda k: self._hist[k][-1].ts if self._hist[k] else 0.0,
            )
            self._hist.pop(oldest, None)

    def reset(self) -> None:
        """Clear all history (tests / cold restart)."""
        self._hist.clear()

    @property
    def tracked_keys(self) -> int:
        return len(self._hist)


# Module-level singleton reused across scan ticks (start-once, like the oracle).
_TRACKER: Optional[MomentumTracker] = None


def get_tracker() -> MomentumTracker:
    """Return the process-wide momentum tracker (lazy, reused across scans)."""
    global _TRACKER
    if _TRACKER is None:
        _TRACKER = MomentumTracker()
    return _TRACKER


__all__ = [
    "PriceSample",
    "MomentumReading",
    "compute_momentum",
    "compute_realized_vol",
    "MomentumTracker",
    "get_tracker",
    "DEFAULT_WINDOW_SEC",
]
