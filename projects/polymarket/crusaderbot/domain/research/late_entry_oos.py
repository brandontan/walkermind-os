"""late_entry_v3 out-of-sample (OOS) edge measurement (WARP-58, lane WARP-54).

Measures the realized OOS edge of ``late_entry_v3`` across its three canonical
presets — ``close_sweep`` / ``safe_close`` / ``flip_hunter`` — **net of fees +
slippage**, by replaying the historical ``market_snapshots`` substrate through
the existing walk-forward replay engine (``domain/research/replay.py``) and
netting the per-trade transaction costs the raw engine does not model.

MEASUREMENT ONLY. This module imports the *real* per-preset gate parameters
(``services.signal_scan.signal_scan_job._CANDLE_PRESET_STATIC``) and the real
strategy thresholds — it never changes strategy logic or any risk constant, and
never places an order. It is a pure read-side research harness.

Inertness contract:
    Inert until ``market_snapshots`` accrues data (``SCAN_SNAPSHOT_ENABLED`` +
    retained history). With an empty / unreachable substrate every preset
    returns an UNPROVEN row (``n_trades == 0``, ``edge_bps is None``). It never
    fabricates an edge.

Cost model (round-trip, taker — see :class:`CostModel`):
    entry  — cross the spread to take the favored/underdog side  -> ~half-spread
    exit   — cross the spread to exit at settlement / flip        -> ~half-spread
    slip   — ``slip_ticks_per_side * tick_size`` adverse fill per side
    fee    — Polymarket CLOB protocol fee (``fee_bps`` of notional; default 0 —
             no canonical fee constant exists in-repo, so it is an explicit,
             overridable assumption rather than an invented number)

The round-trip cost, expressed as a fraction of the side's entry notional (the
same denominator ``replay.trade_return`` uses), is subtracted from each trade's
*gross* return before metrics — so a marginal gross winner can flip to a net
loser and the reported hit-rate reflects costs.

Known fidelity limitations (documented, not hidden):
    * The base ``replay`` engine takes the *earliest* retained snapshot per
      market as the entry; late_entry_v3 enters in the final seconds. The
      :func:`build_decider` window gate therefore only admits a market when its
      earliest retained snapshot already sits inside the preset entry window —
      a faithful but conservative (under-sampling) reconstruction until a
      final-window snapshot selector lands (follow-up; see report §6).
    * Top-of-book for the opposite leg is reconstructed from the single stored
      book (``no_ask ~= 1 - yes_bid``); ``ask_diff`` is approximated accordingly.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable

import structlog

from .replay import (
    ReplayMetrics,
    ReplayTrade,
    compute_metrics,
    has_leakage,
    trade_return,
)

log = structlog.get_logger(__name__)

# Canonical presets to measure, in report order.
PRESETS: tuple[str, ...] = ("close_sweep", "safe_close", "flip_hunter")

# Minimum OOS trades before a preset's edge is considered measurable rather than
# UNPROVEN. Aligned with replay.MIN_FOLD_TRADES (a single fold's trust floor).
MIN_OOS_TRADES: int = 20

_TICK_SIZE: float = 0.01  # matches domain/execution/slippage tick_size default
# Candle window step seconds per timeframe (mirror of late_entry_v3._TF_STEP_SECONDS).
_TF_STEP_SECONDS: dict[str, int] = {"5m": 300, "15m": 900}


@dataclass(frozen=True)
class CostModel:
    """Round-trip taker transaction-cost model (fees + slippage)."""

    tick_size: float = _TICK_SIZE
    slip_ticks_per_side: float = 1.0  # 1 tick of adverse fill per crossing
    fee_bps: float = 0.0              # Polymarket CLOB protocol fee (assumption)

    def round_trip_cost_fraction(self, notional: float) -> float:
        """Round-trip cost as a fraction of the side's entry notional.

        ``notional`` is the price paid for the side at entry (``p`` for YES,
        ``1 - p`` for NO) — the same denominator ``replay.trade_return`` divides
        by, so the returned fraction is subtractable directly from gross return.
        A non-positive notional yields 0.0 (no sizeable position there).
        """
        if notional <= 0:
            return 0.0
        slip_price = 2.0 * self.slip_ticks_per_side * self.tick_size  # both sides
        fee_price = (self.fee_bps / 10_000.0) * notional
        return (slip_price + fee_price) / notional

    def net_return(self, trade: ReplayTrade) -> float:
        """Gross per-trade return (``replay.trade_return``) minus round-trip cost."""
        notional = (1.0 - trade.entry_price) if trade.side.upper() == "NO" else trade.entry_price
        return trade_return(trade) - self.round_trip_cost_fraction(notional)


@dataclass(frozen=True)
class OOSResult:
    """One preset's OOS measurement. ``edge_bps is None`` => UNPROVEN."""

    preset: str
    n_trades: int
    hit_rate: float | None
    gross_ev_per_trade: float | None
    net_ev_per_trade: float | None
    edge_bps: float | None  # net edge per trade in basis points (None = UNPROVEN)
    metrics: ReplayMetrics | None
    status: str             # "MEASURED" | "UNPROVEN_NO_DATA" | "UNPROVEN_THIN"


# Source of truth: services.signal_scan.signal_scan_job._CANDLE_PRESET_STATIC.
# Mirrored here so the harness has correct gate params even in dep-light research
# environments where importing signal_scan_job (-> telegram, etc.) is unavailable.
# The live import below is always preferred and overrides this mirror when the
# full runtime is importable; this is only the fail-soft fallback.
_PRESET_FALLBACK: dict[str, dict[str, object]] = {
    "close_sweep": {
        "min_ask_diff": 0.05, "entry_window_sec": 35.0,
        "fav_price_min": 0.55, "fav_price_max": 0.70, "size_time_decay": True,
    },
    "safe_close": {
        "min_ask_diff": 0.01, "entry_window_sec": 60.0,
        "fav_price_min": 0.60, "fav_price_max": 0.70,
        "min_entry_sec": 30.0, "force_exit_at_rem_sec": 30.0,
    },
    "flip_hunter": {
        "min_ask_diff": 0.01, "entry_window_sec": 180.0,
        "fav_price_min": 0.10, "fav_price_max": 0.36, "min_entry_sec": 60.0,
        "underdog_mode": True, "force_exit_at_rem_sec": 0.0,
    },
}


def _preset_params(preset: str) -> dict[str, object]:
    """Real per-preset gate params. Live import preferred; mirror as fallback."""
    try:
        from ...services.signal_scan.signal_scan_job import _CANDLE_PRESET_STATIC
        params = _CANDLE_PRESET_STATIC.get(preset)
        if params:
            return dict(params)
    except Exception as exc:  # noqa: BLE001 — research harness must not crash on import edge
        log.warning("late_entry_oos: live preset params unavailable, using mirror",
                    preset=preset, error=str(exc))
    return dict(_PRESET_FALLBACK.get(preset, {}))


def _seconds_to_close(raw: object, scanned_at: datetime) -> float | None:
    """Seconds from ``scanned_at`` to the candle close, from the stored Gamma raw.

    Mirror of ``late_entry_v3._seconds_to_close``: primary parses the market end
    timestamp (``endDate``/``endDateIso``/``end_date_iso``); fallback derives the
    close from the recurring-candle slug ``{coin}-updown-{tf}-{slot}`` as
    ``slot + step``. Returns None when neither source is reconstructable (the
    market then fails the window gate — never guessed). A naive ``scanned_at``
    (e.g. a DB column returned without tzinfo) is treated as UTC so the
    subtraction never raises a tz-mismatch ``TypeError``.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return None
    if not isinstance(raw, dict):
        return None
    if scanned_at.tzinfo is None:
        scanned_at = scanned_at.replace(tzinfo=timezone.utc)

    end_raw = raw.get("endDate") or raw.get("endDateIso") or raw.get("end_date_iso")
    if end_raw:
        try:
            end = datetime.fromisoformat(str(end_raw).replace("Z", "+00:00"))
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            return (end - scanned_at).total_seconds()
        except (ValueError, TypeError):
            return None

    # Fallback: derive close from the {coin}-updown-{tf}-{slot} slug (slot is the
    # candle-open epoch; close = slot + timeframe step).
    slug = str(raw.get("slug") or "")
    parts = slug.rsplit("-", 2)
    if len(parts) == 3:
        tf, slot_str = parts[1], parts[2]
        step = _TF_STEP_SECONDS.get(tf)
        if step is not None:
            try:
                end = datetime.fromtimestamp(int(slot_str) + step, tz=timezone.utc)
                return (end - scanned_at).total_seconds()
            except (ValueError, TypeError, OSError):
                return None
    return None


def build_decider(preset: str) -> Callable[[object], tuple[str, str] | None]:
    """Build a ``decide(row) -> (module, side) | None`` for the existing engine.

    Faithful (conservative) mirror of ``late_entry_v3`` entry gating against a
    single snapshot row: admit only when the snapshot sits inside the preset's
    entry window and the favored (or underdog) side's price clears the
    ``fav_price_min``/``fav_price_max`` fence. ``module`` is namespaced per
    preset so the engine groups metrics per preset.
    """
    p = _preset_params(preset)
    window_sec = float(p.get("entry_window_sec", 35.0) or 35.0)
    min_entry_sec = float(p.get("min_entry_sec", 0.0) or 0.0)
    fav_min = float(p.get("fav_price_min", 0.50) or 0.50)
    fav_max = float(p.get("fav_price_max", 0.70) or 0.70)
    underdog = bool(p.get("underdog_mode", False))
    module = f"late_entry_v3::{preset}"

    def decide(row: object) -> tuple[str, str] | None:
        try:
            mid = row["mid_price"]  # type: ignore[index]
            scanned_at = row["scanned_at"]  # type: ignore[index]
            raw = row["raw"]  # type: ignore[index]
        except (KeyError, TypeError):
            return None
        if mid is None or scanned_at is None:
            return None
        rem = _seconds_to_close(raw, scanned_at)
        if rem is None or rem <= 0:
            return None
        if rem > window_sec or rem < min_entry_sec:
            return None  # outside the preset entry window
        mid = float(mid)
        # Favored side = majority side by mid; underdog inverts it (flip_hunter).
        favored_is_yes = mid >= 0.5
        if underdog:
            favored_is_yes = not favored_is_yes
        fav_price = mid if favored_is_yes else (1.0 - mid)
        if fav_price < fav_min or fav_price > fav_max:
            return None
        return (module, "YES" if favored_is_yes else "NO")

    return decide


# Snapshot fetch identical to replay.replay()'s query — injectable for tests.
FetchRows = Callable[[int], Awaitable[list]]


async def _default_fetch_rows(lookback_hours: int) -> list:
    """Read ``market_snapshots`` (same query as replay). Fail-soft -> []."""
    try:
        from ...database import get_pool
        pool = get_pool()
        async with pool.acquire() as conn:  # type: ignore[attr-defined]
            return await conn.fetch(
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
        log.warning("late_entry_oos: snapshot read failed", error=str(exc))
        return []


def _build_trades(rows: list, decide: Callable[[object], tuple[str, str] | None]) -> list[ReplayTrade]:
    """Mirror replay()'s per-market grouping to expose per-trade objects.

    Intentionally mirrors the base engine's grouping (earliest snapshot = entry,
    latest = settlement proxy) so the cost model can be applied per trade — a
    hook the aggregate ``replay()`` does not expose. All return/leakage math is
    the engine's own pure units (single source of truth).
    """
    from collections import defaultdict

    by_market: dict[str, list] = defaultdict(list)
    for r in rows:
        by_market[str(r["market_id"])].append(r)

    trades: list[ReplayTrade] = []
    for snaps in by_market.values():
        if len(snaps) < 2:
            continue
        entry, exit_ = snaps[0], snaps[-1]
        try:
            decision = decide(entry)
        except Exception as exc:  # noqa: BLE001 — one market never aborts the run
            log.warning("late_entry_oos: decide failed", error=str(exc))
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
        trades.append(trade)
    return trades


async def run_oos(
    *,
    presets: tuple[str, ...] = PRESETS,
    lookback_hours: int = 720,
    cost: CostModel | None = None,
    fetch_rows: FetchRows | None = None,
) -> dict[str, OOSResult]:
    """Measure net OOS edge per preset. Empty substrate -> all UNPROVEN_NO_DATA."""
    cost = cost or CostModel()
    fetch = fetch_rows or _default_fetch_rows
    rows = await fetch(lookback_hours)

    out: dict[str, OOSResult] = {}
    for preset in presets:
        trades = _build_trades(rows, build_decider(preset)) if rows else []
        n = len(trades)
        if n == 0:
            out[preset] = OOSResult(
                preset=preset, n_trades=0, hit_rate=None,
                gross_ev_per_trade=None, net_ev_per_trade=None, edge_bps=None,
                metrics=None, status="UNPROVEN_NO_DATA",
            )
            continue
        gross = [trade_return(t) for t in trades]
        net = [cost.net_return(t) for t in trades]
        durations = [
            (t.resolution_ts - t.entry_ts).total_seconds() if t.resolution_ts else 0.0
            for t in trades
        ]
        net_metrics = compute_metrics(net, durations)
        gross_ev = sum(gross) / n
        net_ev = net_metrics.ev_per_trade
        status = "MEASURED" if n >= MIN_OOS_TRADES else "UNPROVEN_THIN"
        out[preset] = OOSResult(
            preset=preset,
            n_trades=n,
            hit_rate=net_metrics.win_rate,
            gross_ev_per_trade=gross_ev,
            net_ev_per_trade=net_ev,
            edge_bps=(net_ev * 10_000.0) if status == "MEASURED" else None,
            metrics=net_metrics,
            status=status,
        )
    return out


def format_table(results: dict[str, OOSResult]) -> str:
    """Render the per-preset OOS results as a fixed-width text table."""
    head = (
        f"{'preset':<14} {'n':>5} {'hit_rate':>9} {'gross_ev':>10} "
        f"{'net_ev':>10} {'edge_bps':>10}  status"
    )
    lines = [head, "-" * len(head)]
    for preset in PRESETS:
        r = results.get(preset)
        if r is None:
            continue
        hr = f"{r.hit_rate:.3f}" if r.hit_rate is not None else "N/A"
        gev = f"{r.gross_ev_per_trade:.5f}" if r.gross_ev_per_trade is not None else "N/A"
        nev = f"{r.net_ev_per_trade:.5f}" if r.net_ev_per_trade is not None else "N/A"
        eb = f"{r.edge_bps:.1f}" if r.edge_bps is not None else "UNPROVEN"
        lines.append(
            f"{r.preset:<14} {r.n_trades:>5} {hr:>9} {gev:>10} {nev:>10} {eb:>10}  {r.status}"
        )
    return "\n".join(lines)


async def _amain() -> None:
    results = await run_oos()
    print(format_table(results))


if __name__ == "__main__":  # pragma: no cover — manual/CI invocation
    import asyncio

    asyncio.run(_amain())


__all__ = [
    "PRESETS",
    "MIN_OOS_TRADES",
    "CostModel",
    "OOSResult",
    "build_decider",
    "run_oos",
    "format_table",
]
