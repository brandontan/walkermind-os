"""Walk-forward replay engine (Phase-2c-3, blueprint §12.1).

The validation half of the backtest harness: replays the historical market state
captured in ``market_snapshots`` (Phase-2c-2) through a strategy's *real* decision
logic and scores the resulting trades out-of-sample. No parallel simulation logic
— the caller passes the same ``evaluate``-style callable the live scan uses, so
there is no sim/live drift.

Three concerns, each a small pure (testable) unit:

* **Metrics** (``compute_metrics``) — win rate, EV/trade, Sharpe, Sortino, profit
  factor, max drawdown, average holding duration.
* **Walk-forward** (``walk_forward_split``) — expanding train→validate folds over
  time, so parameters are only ever evaluated on data after the window they were
  (notionally) fit on.
* **Bias detection** — ``has_leakage`` (no post-resolution data feeds an entry) and
  ``overfit_degradation`` (in-sample vs out-of-sample EV gap).

``replay`` orchestrates them over ``market_snapshots``; it is **inert until that
table accrues data** (``SCAN_SNAPSHOT_ENABLED`` + time) — with an empty table it
returns ``{}``. Pure read; fail-soft on every DB touch.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from statistics import mean, pstdev

import structlog

from ...database import get_pool

logger = structlog.get_logger(__name__)

# An entry's out-of-sample degradation beyond this EV gap flags overfitting.
OVERFIT_EV_GAP: float = 0.02
# Minimum trades in a fold before its metrics are trusted.
MIN_FOLD_TRADES: int = 20


@dataclass(frozen=True)
class ReplayTrade:
    """One replayed decision: entry state + realized settlement."""

    module: str
    category: str                  # league / market category
    side: str                      # "YES" | "NO"
    entry_ts: datetime
    resolution_ts: datetime | None
    entry_price: float             # mid at decision time, in (0, 1)
    exit_price: float              # settlement (1.0/0.0) or final observed mid


@dataclass(frozen=True)
class ReplayMetrics:
    n_trades: int
    win_rate: float
    ev_per_trade: float
    sharpe: float
    sortino: float
    profit_factor: float
    max_drawdown: float
    avg_holding_sec: float


def trade_return(t: ReplayTrade) -> float:
    """Signed return fraction of one trade for its side.

    A YES position bought at ``entry_price`` settling at ``exit_price`` returns
    ``(exit-entry)/entry``; a NO position is symmetric on ``1-price``. Degenerate
    prices (≤0 or ≥1 on the denominator) return 0.0 (no position sizeable there).
    """
    e, x = t.entry_price, t.exit_price
    if t.side.upper() == "NO":
        denom = 1.0 - e
        return ((1.0 - x) - (1.0 - e)) / denom if denom > 0 else 0.0
    return (x - e) / e if e > 0 else 0.0


def _max_drawdown(returns: list[float]) -> float:
    """Peak-to-trough drawdown fraction over the cumulative (additive) equity."""
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for r in returns:
        equity += r
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def compute_metrics(returns: list[float], durations: list[float] | None = None) -> ReplayMetrics:
    """§12.1 metrics over per-trade return fractions. Empty → zeroed."""
    n = len(returns)
    if n == 0:
        return ReplayMetrics(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    ev = mean(returns)
    sd = pstdev(returns) if n > 1 else 0.0
    # Sortino downside deviation = RMS of negative returns vs the 0.0 target
    # (NOT pstdev, which subtracts the clipped mean and understates large losses).
    downside = mean([min(0.0, r) ** 2 for r in returns]) ** 0.5
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    return ReplayMetrics(
        n_trades=n,
        win_rate=len(wins) / n,
        ev_per_trade=ev,
        sharpe=(ev / sd) if sd > 0 else 0.0,
        sortino=(ev / downside) if downside > 0 else 0.0,
        profit_factor=(gross_win / gross_loss) if gross_loss > 0 else 0.0,
        max_drawdown=_max_drawdown(returns),
        avg_holding_sec=mean(durations) if durations else 0.0,
    )


def walk_forward_split(
    trades: list[ReplayTrade], n_splits: int = 4
) -> list[tuple[list[ReplayTrade], list[ReplayTrade]]]:
    """Expanding-window train→validate folds, ordered by ``entry_ts``.

    Fold *i* trains on everything up to boundary *i* and validates on the next
    block — parameters are only ever scored on trades *after* the data they were
    fit on (no look-ahead). Fewer than ``n_splits+1`` trades → no folds.
    """
    if n_splits < 1 or len(trades) < n_splits + 1:
        return []
    ordered = sorted(trades, key=lambda t: t.entry_ts)
    # Float step so the remainder isn't dropped (integer division would discard up
    # to n_splits of the most-recent trades when len isn't evenly divisible).
    step = len(ordered) / (n_splits + 1)
    out: list[tuple[list[ReplayTrade], list[ReplayTrade]]] = []
    for i in range(1, n_splits + 1):
        train = ordered[: int(i * step)]
        validate = ordered[int(i * step): int((i + 1) * step)]
        if validate:
            out.append((train, validate))
    return out


def has_leakage(t: ReplayTrade) -> bool:
    """True if the entry used data at/after resolution (look-ahead leakage)."""
    return t.resolution_ts is not None and t.entry_ts >= t.resolution_ts


def overfit_degradation(in_sample: ReplayMetrics, out_sample: ReplayMetrics) -> float:
    """In-sample minus out-of-sample EV. Positive + large ⇒ overfit."""
    return in_sample.ev_per_trade - out_sample.ev_per_trade


def is_overfit(in_sample: ReplayMetrics, out_sample: ReplayMetrics,
               gap: float = OVERFIT_EV_GAP) -> bool:
    return overfit_degradation(in_sample, out_sample) > gap


async def replay(
    decide,
    *,
    lookback_hours: int = 720,
    mode: str = "paper",
    pool: object | None = None,
) -> dict[str, ReplayMetrics]:
    """Replay ``market_snapshots`` through ``decide`` and score per module/league.

    ``decide(snapshot_row) -> (module, side) | None`` is the caller's real decision
    logic (e.g. a thin wrapper over a strategy's ``evaluate_snapshot``); returning
    None means "no trade". For each market we take the earliest snapshot as the
    entry and the latest as the settlement proxy, build a ``ReplayTrade``, drop any
    with look-ahead leakage, and compute metrics per ``module``.

    **Inert until ``market_snapshots`` has data** — returns ``{}`` on empty/error.
    Fail-soft: any DB error logs and returns ``{}``.
    """
    try:
        pool = pool or get_pool()
        async with pool.acquire() as conn:  # type: ignore[attr-defined]
            rows = await conn.fetch(
                """
                SELECT market_id, category, best_bid, best_ask, mid_price,
                       liquidity_usdc, raw, scanned_at
                  FROM market_snapshots
                 WHERE scanned_at > NOW() - make_interval(hours => $1)
                   AND mid_price IS NOT NULL
                 ORDER BY market_id, scanned_at
                """,
                lookback_hours,
            )
    except Exception as exc:  # noqa: BLE001 — fail-soft analytics read
        logger.warning("replay_snapshot_read_failed", error=str(exc))
        return {}

    by_market: dict[str, list] = defaultdict(list)
    for r in rows:
        by_market[str(r["market_id"])].append(r)

    grouped: dict[str, list[float]] = defaultdict(list)
    durations: dict[str, list[float]] = defaultdict(list)
    for market_id, snaps in by_market.items():
        if len(snaps) < 2:
            continue  # need an entry + a settlement observation
        entry, exit_ = snaps[0], snaps[-1]
        try:
            # The full entry row is passed so a real decision wrapper has the
            # book (best_bid/ask), liquidity, and the raw Gamma payload (event
            # timing etc.) it needs to reconstruct a snapshot — not just mid.
            decision = decide(entry)
        except Exception as exc:  # noqa: BLE001 — one market's decision never aborts the run
            logger.warning("replay_decide_failed", market_id=market_id, error=str(exc))
            continue
        if not decision:
            continue
        module, side = decision
        trade = ReplayTrade(
            module=str(module),
            category=str(entry["category"] or ""),
            side=str(side),
            entry_ts=entry["scanned_at"],
            resolution_ts=exit_["scanned_at"],
            entry_price=float(entry["mid_price"]),
            exit_price=float(exit_["mid_price"]),
        )
        if has_leakage(trade):
            continue
        grouped[trade.module].append(trade_return(trade))
        durations[trade.module].append(
            (trade.resolution_ts - trade.entry_ts).total_seconds()
            if trade.resolution_ts else 0.0
        )

    return {
        module: compute_metrics(rets, durations[module])
        for module, rets in grouped.items()
    }


__all__ = [
    "ReplayTrade",
    "ReplayMetrics",
    "trade_return",
    "compute_metrics",
    "walk_forward_split",
    "has_leakage",
    "overfit_degradation",
    "is_overfit",
    "replay",
    "OVERFIT_EV_GAP",
    "MIN_FOLD_TRADES",
]
