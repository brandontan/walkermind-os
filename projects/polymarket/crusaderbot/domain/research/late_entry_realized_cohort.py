"""Late-Entry V3 realized-cohort calibration export (#1815 — read-only).

Owner directive: produce an evidence-based verdict (APPROVE MICRO-LIVE / NEEDS
MORE DATA / DO NOT SCALE) without modifying live behaviour. This export is the
research substrate that supports the verdict: it queries the realized PAPER
cohort of closed ``late_entry_v3`` positions, splits them by active preset and
side, and reports sample size, win-rate, mean realized P&L, and a transparent
EV-after-cost simulation on the existing prices (round-trip cost model = tick +
slippage per side, same shape as ``domain/research/late_entry_oos.CostModel``).

It is READ-ONLY by design:
  * SELECT-only against ``positions``;
  * no CLOB / Bridge / Relayer / Gamma calls of any kind;
  * no ledger / wallet / order intent / live-guard read or flip;
  * no DataFrame/pandas — stdlib only — so CI is hermetic.

Insufficient buckets (``n < MIN_OOS_TRADES``) are flagged ``UNPROVEN_THIN`` per
the existing ``late_entry_oos.MIN_OOS_TRADES`` floor (=20). Buckets meeting the
floor are tagged ``REALIZED`` — meaning the bucket has enough realized history
to *describe*, NOT that the strategy has a proven OOS edge in that bucket; the
OOS verdict still requires ``late_entry_oos.measure_oos`` to run against
populated ``market_snapshots`` (currently sparse / feature-flagged OFF).
"""
from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any, Iterable, Optional

import asyncpg

from ...database import get_pool
from .late_entry_oos import MIN_OOS_TRADES, PRESETS, CostModel

DEFAULT_PRESET = "candle_auto"
_RECOGNISED_PRESETS = set(PRESETS) | {DEFAULT_PRESET}


@dataclass(frozen=True)
class _RawTrade:
    """A closed late_entry_v3 paper trade — only columns we need for cohort math."""

    preset: str
    side: str
    entry_price: float
    size_usdc: float
    pnl_usdc: float
    exit_reason: Optional[str]


@dataclass
class BucketStats:
    """One (preset, side) cohort summary. ``UNPROVEN_THIN`` means n < 20."""

    preset: str
    side: str
    n_trades: int = 0
    wins: int = 0
    losses: int = 0
    breakeven: int = 0
    realized_pnl_usdc: float = 0.0
    realized_mean_pnl_per_trade: float = 0.0
    win_rate: Optional[float] = None
    mean_entry_price: Optional[float] = None
    mean_size_usdc: Optional[float] = None
    sim_net_ev_per_trade: Optional[float] = None
    sim_net_ev_bps: Optional[float] = None
    sim_cost_bps_per_trade: Optional[float] = None
    exit_reason_counts: dict[str, int] = field(default_factory=dict)
    status: str = "UNPROVEN_THIN"

    @property
    def ready_for_verdict(self) -> bool:
        return self.status == "REALIZED"


@dataclass
class CalibrationReport:
    """Top-level evidence matrix consumed by the WARP•R00T report writer."""

    total_trades: int
    universe: str
    cost_model: dict[str, float]
    min_oos_trades: int
    buckets: list[BucketStats]

    @property
    def has_any_realized_bucket(self) -> bool:
        return any(b.ready_for_verdict for b in self.buckets)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True, default=str)


def _norm_preset(value: Any) -> str:
    """Map an active_preset column value into a recognised cohort label.

    ``candle_auto`` is the router pseudo-preset (per ``signal_scan_job``) — it
    delegates to ``late_entry_v3``, so we keep it as its own cohort to surface
    routing behaviour distinctly. Anything else (legacy / NULL) is bucketed as
    ``unknown`` so it cannot silently merge with a real preset bucket.
    """
    raw = str(value or "").strip().lower()
    if raw in _RECOGNISED_PRESETS:
        return raw
    return "unknown"


def _norm_side(value: Any) -> str:
    return "YES" if str(value or "").upper().startswith("Y") else "NO"


def _entry_notional(entry_price: float, side: str) -> float:
    """Side notional = the price paid for one share of the entered token."""
    if side == "YES":
        return max(entry_price, 1e-6)
    return max(1.0 - entry_price, 1e-6)


def _classify(pnl: float) -> str:
    if pnl > 0:
        return "win"
    if pnl < 0:
        return "loss"
    return "breakeven"


def _coerce_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


async def _load_realized_cohort(conn: asyncpg.Connection) -> list[_RawTrade]:
    """Closed PAPER ``late_entry_v3`` positions with a realized P&L.

    Excludes:
      * live positions (out of scope for this calibration);
      * ``paper_archived`` rows (PAPER->LIVE switch cleanup, not a realized fill);
      * positions whose exit was a forced close / horizon-exceeded / market-expired
        (not a strategy-driven outcome — the strategy didn't get its scheduled exit).
    """
    rows = await conn.fetch(
        """
        SELECT active_preset, side, entry_price, size_usdc, pnl_usdc, exit_reason
          FROM positions
         WHERE mode = 'paper'
           AND status = 'closed'
           AND strategy_type = 'late_entry_v3'
           AND pnl_usdc IS NOT NULL
           AND exit_reason NOT IN ('force_close', 'horizon_exceeded', 'market_expired',
                                   'paper_to_live_switch', 'already_closed')
        """,
    )
    out: list[_RawTrade] = []
    for r in rows:
        out.append(_RawTrade(
            preset=_norm_preset(r["active_preset"]),
            side=_norm_side(r["side"]),
            entry_price=_coerce_float(r["entry_price"]),
            size_usdc=_coerce_float(r["size_usdc"]),
            pnl_usdc=_coerce_float(r["pnl_usdc"]),
            exit_reason=r["exit_reason"],
        ))
    return out


def _aggregate(
    trades: Iterable[_RawTrade], cost: CostModel,
) -> list[BucketStats]:
    by_key: dict[tuple[str, str], list[_RawTrade]] = {}
    for t in trades:
        by_key.setdefault((t.preset, t.side), []).append(t)

    out: list[BucketStats] = []
    for (preset, side), bucket in sorted(by_key.items()):
        n = len(bucket)
        wins = sum(1 for t in bucket if t.pnl_usdc > 0)
        losses = sum(1 for t in bucket if t.pnl_usdc < 0)
        breakeven = n - wins - losses
        realized_pnl = sum(t.pnl_usdc for t in bucket)

        exit_counts: dict[str, int] = {}
        for t in bucket:
            key = t.exit_reason or "unknown"
            exit_counts[key] = exit_counts.get(key, 0) + 1

        # Simulated NET EV per trade: realized GROSS return on the actual
        # entry_price, minus the explicit transaction cost model. The realized
        # ``pnl_usdc`` IS already net of nothing else (paper fills assume zero
        # cost), so subtracting the cost model gives a defensible "would have
        # earned net" estimate without touching CLOB.
        sim_net_per_trade: Optional[float] = None
        sim_cost_bps: Optional[float] = None
        if n > 0:
            cost_fracs: list[float] = []
            net_per_trade: list[float] = []
            for t in bucket:
                notional = _entry_notional(t.entry_price, t.side)
                cost_frac = cost.round_trip_cost_fraction(notional)
                cost_fracs.append(cost_frac)
                # pnl_usdc is in USDC; convert to per-share return using size_usdc
                # ≈ shares * entry_price for the entered side. Avoid div-by-zero
                # on degenerate rows; treat as 0 contribution.
                size = max(t.size_usdc, 1e-6)
                gross_return = t.pnl_usdc / size
                net_per_trade.append(gross_return - cost_frac)
            sim_net_per_trade = sum(net_per_trade) / n
            sim_cost_bps = (sum(cost_fracs) / n) * 10_000.0

        sim_net_ev_bps = (
            sim_net_per_trade * 10_000.0 if sim_net_per_trade is not None else None
        )

        bs = BucketStats(
            preset=preset,
            side=side,
            n_trades=n,
            wins=wins,
            losses=losses,
            breakeven=breakeven,
            realized_pnl_usdc=round(realized_pnl, 4),
            realized_mean_pnl_per_trade=round(realized_pnl / n, 6) if n else 0.0,
            win_rate=round(wins / n, 4) if n else None,
            mean_entry_price=(
                round(sum(t.entry_price for t in bucket) / n, 4) if n else None
            ),
            mean_size_usdc=(
                round(sum(t.size_usdc for t in bucket) / n, 4) if n else None
            ),
            sim_net_ev_per_trade=(
                round(sim_net_per_trade, 6) if sim_net_per_trade is not None else None
            ),
            sim_net_ev_bps=(
                round(sim_net_ev_bps, 1) if sim_net_ev_bps is not None else None
            ),
            sim_cost_bps_per_trade=(
                round(sim_cost_bps, 1) if sim_cost_bps is not None else None
            ),
            exit_reason_counts=exit_counts,
            status="REALIZED" if n >= MIN_OOS_TRADES else "UNPROVEN_THIN",
        )
        out.append(bs)
    return out


async def build_report(*, cost: CostModel | None = None) -> CalibrationReport:
    """Async entry point: query the realized cohort and aggregate it.

    READ-ONLY. SELECT-only against ``positions``. No CLOB, Bridge, Relayer or
    Gamma call. The DB pool is the one already used by the bot — tests inject a
    fake by patching ``get_pool``.
    """
    cost = cost or CostModel()
    pool = get_pool()
    async with pool.acquire() as conn:
        trades = await _load_realized_cohort(conn)
    buckets = _aggregate(trades, cost)
    return CalibrationReport(
        total_trades=len(trades),
        universe="BTC/ETH 5m/15m (Smart Strike; SOL OFF)",
        cost_model={
            "tick_size": cost.tick_size,
            "slip_ticks_per_side": cost.slip_ticks_per_side,
            "fee_bps": cost.fee_bps,
        },
        min_oos_trades=MIN_OOS_TRADES,
        buckets=buckets,
    )


def render_markdown(report: CalibrationReport) -> str:
    """Markdown matrix for the R00T report appendix."""
    lines: list[str] = []
    lines.append(
        f"Universe: {report.universe} — total realized late_entry_v3 paper trades: "
        f"{report.total_trades}. UNPROVEN_THIN threshold: n < {report.min_oos_trades}."
    )
    lines.append("")
    lines.append(
        "Cost model (round-trip taker): tick "
        f"{report.cost_model['tick_size']}, slip "
        f"{report.cost_model['slip_ticks_per_side']} tick/side, fee "
        f"{report.cost_model['fee_bps']} bps."
    )
    lines.append("")
    lines.append(
        "| Preset | Side | n | Win rate | Mean entry | Realized P&L | "
        "Mean P&L/trade | Sim cost (bps) | Sim net EV (bps) | Status |"
    )
    lines.append(
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|"
    )
    if not report.buckets:
        lines.append("| — | — | 0 | — | — | — | — | — | — | NO DATA |")
    for b in report.buckets:
        wr = f"{b.win_rate * 100:.1f}%" if b.win_rate is not None else "—"
        me = f"{b.mean_entry_price:.3f}" if b.mean_entry_price is not None else "—"
        mp = f"{b.realized_mean_pnl_per_trade:+.4f}"
        cb = f"{b.sim_cost_bps_per_trade:+.0f}" if b.sim_cost_bps_per_trade is not None else "—"
        ne = f"{b.sim_net_ev_bps:+.0f}" if b.sim_net_ev_bps is not None else "—"
        lines.append(
            f"| {b.preset} | {b.side} | {b.n_trades} | {wr} | {me} | "
            f"{b.realized_pnl_usdc:+.2f} | {mp} | {cb} | {ne} | {b.status} |"
        )
    return "\n".join(lines)


async def _main() -> int:
    """CLI entry: print the matrix as Markdown + JSON. Read-only."""
    report = await build_report()
    print(render_markdown(report))
    print()
    print("```json")
    print(report.to_json())
    print("```")
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI convenience only
    sys.exit(asyncio.run(_main()))
