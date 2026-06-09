"""Slippage replay engine (WARP-83 Sub-Lane B).

Re-runs the last N days of *settled paper_real* trades through a slippage model
and reports the **slippage-adjusted P&L** per trade, aggregated per cell
(``asset/timeframe`` e.g. ``BTC/5m``). This quantifies how much of the paper
P&L survives a realistic execution cost before any LIVE viability claim is made.

DECOUPLING — dependency injection
---------------------------------
Sub-Lane A ships the production slippage estimator at
``domain/research/slippage_estimator.py`` on a *parallel* branch, so that module
does NOT exist here yet. This engine never hard-depends on it:

* It defines a small typed :class:`SlippageModel` Protocol — any callable taking
  :class:`SlippageInputs` and returning slippage in basis points satisfies it.
* It ships a self-contained :class:`DefaultSlippageModel` reference implementation
  so the script runs standalone today.
* :func:`resolve_slippage_model` tries to import the Sub-Lane A estimator and
  falls back to the built-in default on ImportError — the fallback is **logged**
  (``slippage_estimator_fallback``), never silently swallowed — so the engine
  auto-upgrades once Sub-Lane A merges. Final wiring to the Sub-Lane A estimator
  is a CMD-gated follow-up after both lanes merge.

THE >50% GATE (CATASTROPHIC)
----------------------------
If, on a real-data replay, modeled slippage erases more than
:data:`SLIPPAGE_PNL_GATE_FRAC` (50%) of the gross paper P&L, that is CATASTROPHIC
for LIVE viability. This engine **flags** that condition prominently; it does NOT
decide — escalation to CMD is required.

Inputs (``--from-db``)
----------------------
``positions`` (mode='paper', status='closed', pnl_usdc NOT NULL) JOINed to
``factor_vectors`` (data_source='paper_real', settled=TRUE) by ``market_id`` and
a ``opened_at`` ↔ factor-vector capture-window match. DB output is treated as
UNTRUSTED: every numeric is coerced + NULL-guarded, every row failure is logged
and skipped, never aborts the run.

Read-only. No writes. No order placement. PAPER data only — this engine never
touches ``ENABLE_LIVE_TRADING`` and never executes a trade.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Protocol, Sequence, runtime_checkable

import structlog

# Make the project root importable when run as a bare script (mirrors the other
# scripts in this directory). Safe under package import too — runs once.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# CATASTROPHIC LIVE-viability gate: slippage eroding more than this fraction of
# gross paper P&L must be escalated to CMD before any LIVE consideration.
SLIPPAGE_PNL_GATE_FRAC: float = 0.50

# Default join window: a position's ``opened_at`` must fall between the factor
# vector's first capture and a bounded margin past its settlement.
DEFAULT_JOIN_PRE_MIN: int = 10
DEFAULT_JOIN_POST_MIN: int = 60

# Provenance regime this engine reads (factor_vectors.data_source). Paper-real is
# the only regime with the orderbook factors slippage modeling needs.
DATA_SOURCE_PAPER_REAL: str = "paper_real"

# Default reference-model coefficients (basis points). Conservative, transparent,
# and superseded by the Sub-Lane A estimator once it merges.
_DEFAULT_BASE_BPS: float = 5.0          # fixed crossing/fee floor
_DEFAULT_SPREAD_WEIGHT: float = 0.5     # half-spread paid on a market cross
_DEFAULT_IMPACT_WEIGHT_BPS: float = 80.0  # impact at order_size == available depth
_DEFAULT_VOL_WEIGHT_BPS: float = 50.0   # widening with realized volatility sigma
_DEFAULT_MAX_BPS: float = 1000.0        # hard cap (10%) — model never returns more


# ---------------------------------------------------------------------------
# Typed I/O
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SlippageInputs:
    """Per-trade features a slippage model consumes. All prices in (0, 1).

    Mirrors the columns available on a ``positions`` × ``factor_vectors`` join so
    the same shape works for the built-in default and the Sub-Lane A estimator.
    """

    side: str                      # "YES" | "NO"
    entry_price: float             # fill price the paper trade recorded, in (0, 1)
    size_usdc: float               # notional of the position
    liquidity_usdc: float          # market liquidity at capture
    spread: float                  # bid/ask spread (price units, in (0, 1))
    volatility_sigma: float        # realized vol sigma at capture
    orderbook_depth_usdc: float    # depth available on the entry side


@runtime_checkable
class SlippageModel(Protocol):
    """A callable mapping :class:`SlippageInputs` to slippage in basis points.

    The injection seam: the built-in :class:`DefaultSlippageModel`, the Sub-Lane A
    estimator, and any test stub all satisfy this Protocol. Implementations MUST
    return a finite, non-negative bps value.
    """

    def __call__(self, x: SlippageInputs) -> float: ...


@dataclass(frozen=True)
class ReplayTradeRecord:
    """One replayed paper trade with its slippage-adjusted P&L."""

    market_id: str
    cell: str                      # normalized "BTC/5m"
    side: str
    size_usdc: float
    entry_price: float
    paper_pnl_usdc: float          # realized paper P&L (slippage-free)
    slippage_bps: float            # modeled slippage applied on entry
    slippage_cost_usdc: float      # USDC cost of that slippage on this notional
    adjusted_pnl_usdc: float       # paper_pnl - slippage_cost


@dataclass(frozen=True)
class CellAggregate:
    """Per-cell roll-up of replayed trades."""

    cell: str
    n_trades: int
    gross_paper_pnl_usdc: float
    total_slippage_usdc: float
    adjusted_pnl_usdc: float
    slippage_fraction: float       # total_slippage / |gross_paper_pnl| (gate input)
    gate_breached: bool            # slippage_fraction > SLIPPAGE_PNL_GATE_FRAC


# ---------------------------------------------------------------------------
# Built-in reference slippage model (self-contained default)
# ---------------------------------------------------------------------------


class DefaultSlippageModel:
    """Transparent reference slippage model — used until Sub-Lane A merges.

    bps = base + spread_weight * spread_bps
              + impact_weight * (size / depth)
              + vol_weight * volatility_sigma

    Each term is non-negative; the total is clamped to ``[0, max_bps]``. This is a
    conservative placeholder, NOT a calibrated estimator — the Sub-Lane A model
    supersedes it via :func:`resolve_slippage_model`.
    """

    def __init__(
        self,
        *,
        base_bps: float = _DEFAULT_BASE_BPS,
        spread_weight: float = _DEFAULT_SPREAD_WEIGHT,
        impact_weight_bps: float = _DEFAULT_IMPACT_WEIGHT_BPS,
        vol_weight_bps: float = _DEFAULT_VOL_WEIGHT_BPS,
        max_bps: float = _DEFAULT_MAX_BPS,
    ) -> None:
        self.base_bps = base_bps
        self.spread_weight = spread_weight
        self.impact_weight_bps = impact_weight_bps
        self.vol_weight_bps = vol_weight_bps
        self.max_bps = max_bps

    def __call__(self, x: SlippageInputs) -> float:
        # Half-spread paid on a cross, expressed in bps of the entry price.
        spread_bps = 0.0
        if x.entry_price > 0 and x.spread > 0:
            spread_bps = (x.spread / x.entry_price) * 10_000.0
        spread_term = self.spread_weight * spread_bps

        # Market-impact term: order size relative to available depth. Use depth if
        # present, else fall back to total liquidity; if neither is usable the
        # impact term is 0 (no basis to estimate — never invent depth).
        depth = x.orderbook_depth_usdc if x.orderbook_depth_usdc > 0 else x.liquidity_usdc
        impact_term = 0.0
        if depth > 0 and x.size_usdc > 0:
            impact_term = self.impact_weight_bps * (x.size_usdc / depth)

        vol_term = self.vol_weight_bps * max(0.0, x.volatility_sigma)

        total = self.base_bps + spread_term + impact_term + vol_term
        if total < 0.0:
            total = 0.0
        if total > self.max_bps:
            total = self.max_bps
        return total


class CalibratedSlippageModel:
    """Adapter wrapping the Sub-Lane A calibrated estimator as a :class:`SlippageModel`.

    The merged ``domain/research/slippage_estimator.py`` exposes a pure function
    ``estimate_slippage_bps(**kwargs) -> SlippageEstimate`` — a keyword-only factor
    API that does NOT match this engine's ``SlippageModel`` Protocol
    (``__call__(SlippageInputs) -> float``) directly. This thin, typed adapter
    reconciles the two: it maps the engine's per-trade :class:`SlippageInputs` onto
    the estimator's kwargs and returns ``SlippageEstimate.total_bps``.

    Input mapping (engine -> estimator)::

        size_usdc            -> stake_usdc
        orderbook_depth_usdc -> orderbook_depth_usdc
        spread               -> spread
        entry_price          -> entry_price
        (no live price)      -> current_price = entry_price

    The engine's :class:`SlippageInputs` surface carries no live ``current_price``
    (the replay reconstructs entry-time factors only), so ``current_price`` is set
    equal to ``entry_price``. That yields a zero ``adverse_move_bps`` component by
    construction — the replay charges spread + impact, not realized post-entry
    drift, which it has no data for. This is explicit, not a silent default.
    """

    def __init__(self, estimate_fn: Any) -> None:
        self._estimate_fn = estimate_fn

    def __call__(self, x: SlippageInputs) -> float:
        estimate = self._estimate_fn(
            stake_usdc=x.size_usdc,
            orderbook_depth_usdc=x.orderbook_depth_usdc,
            spread=x.spread,
            entry_price=x.entry_price,
            current_price=x.entry_price,
        )
        return float(estimate.total_bps)


def resolve_slippage_model() -> SlippageModel:
    """Return the Sub-Lane A calibrated estimator if importable, else the default.

    Sub-Lane A merged ``estimate_slippage_bps`` (a keyword-only factor function,
    NOT a ``build_slippage_model`` factory), so this wraps it in
    :class:`CalibratedSlippageModel` to satisfy the engine's Protocol. The fallback
    is LOGGED (``slippage_estimator_fallback``) — never silently swallowed — so a
    missing module is visible in the run output. Any unexpected import error is
    also logged and degrades to the default rather than aborting the replay.
    """
    estimate_fn = _import_estimate_slippage_bps()
    if estimate_fn is None:
        return DefaultSlippageModel()

    try:
        model: SlippageModel = CalibratedSlippageModel(estimate_fn)
    except Exception as exc:  # noqa: BLE001 — bad adapter degrades, not aborts
        logger.warning(
            "slippage_estimator_build_failed",
            error=str(exc),
            action="degraded to DefaultSlippageModel",
        )
        return DefaultSlippageModel()

    logger.info("slippage_estimator_loaded", source="domain.research.slippage_estimator")
    return model


def _import_estimate_slippage_bps() -> Optional[Any]:
    """Resolve Sub-Lane A's ``estimate_slippage_bps`` across both import roots.

    The repo runs under two import roots: pytest uses the repo root (package
    ``projects.polymarket.crusaderbot.*``) while the bot/scripts insert the
    crusaderbot dir as root (top-level ``domain`` / ``database``). The
    ``domain.research`` package ``__init__`` eagerly imports ``robustness``,
    whose ``from ...database import`` only resolves under the repo root — so the
    plain ``from domain.research.slippage_estimator import ...`` raises
    ImportError under the script's own runtime root, even though the estimator
    leaf module itself has no intra-package imports.

    Strategy (each step LOGGED, never silently swallowed):
      1. Normal package import (works under the repo/pytest root).
      2. Direct file load of the leaf module via importlib, bypassing the
         ``domain/research/__init__`` chain (works under the crusaderbot root).
      3. Return ``None`` -> caller degrades to ``DefaultSlippageModel``.
    """
    try:
        from domain.research.slippage_estimator import (  # type: ignore  # noqa: E402
            estimate_slippage_bps,
        )

        return estimate_slippage_bps
    except ImportError as exc:
        logger.info(
            "slippage_estimator_package_import_failed",
            reason="domain.research.__init__ chain not importable under this "
            "runtime root — trying direct leaf-module load",
            error=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 — any __init__-chain error must still
        # degrade to the direct leaf load, never crash the replay.
        logger.warning(
            "slippage_estimator_package_import_error",
            error=str(exc),
            action="trying direct leaf-module load",
        )

    leaf = _PROJECT_ROOT / "domain" / "research" / "slippage_estimator.py"
    if not leaf.is_file():
        logger.info(
            "slippage_estimator_fallback",
            reason="estimator leaf module not found (Sub-Lane A not merged yet) "
            "— using DefaultSlippageModel",
            path=str(leaf),
        )
        return None

    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_slippage_estimator_leaf", leaf
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"could not build import spec for {leaf}")
        module = importlib.util.module_from_spec(spec)
        # Register before exec so dataclass / typing resolution can find the
        # module by name during its own import side effects.
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            # Don't leave a half-initialised module in the registry — pop it so a
            # later retry / other code sees a clean sys.modules.
            sys.modules.pop(spec.name, None)
            raise
        logger.info(
            "slippage_estimator_loaded_direct",
            source=str(leaf),
            note="bypassed domain.research.__init__ chain",
        )
        return module.estimate_slippage_bps
    except Exception as exc:  # noqa: BLE001 — never abort the replay on a bad import
        logger.warning(
            "slippage_estimator_direct_load_failed",
            error=str(exc),
            action="degraded to DefaultSlippageModel",
        )
        return None


# ---------------------------------------------------------------------------
# Cell helpers
# ---------------------------------------------------------------------------


def normalize_cell(asset: str, timeframe: str) -> str:
    """``("btc", "5m") -> "BTC/5m"`` — canonical UPPER-asset / lower-timeframe."""
    return f"{asset.strip().upper()}/{timeframe.strip().lower()}"


def parse_cells(spec: str) -> tuple[str, ...]:
    """Parse ``"BTC/5m,ETH/5m"`` into a normalized tuple. Empty entries dropped."""
    out: list[str] = []
    for raw in spec.split(","):
        token = raw.strip()
        if not token or "/" not in token:
            continue
        asset, _, timeframe = token.partition("/")
        if asset.strip() and timeframe.strip():
            out.append(normalize_cell(asset, timeframe))
    return tuple(dict.fromkeys(out))  # dedupe, preserve order


# ---------------------------------------------------------------------------
# Core replay math (pure, unit-testable)
# ---------------------------------------------------------------------------


def replay_trade(
    *,
    market_id: str,
    cell: str,
    inputs: SlippageInputs,
    paper_pnl_usdc: float,
    model: SlippageModel,
) -> ReplayTradeRecord:
    """Apply ``model`` to one trade and return its slippage-adjusted record.

    Slippage is charged once on entry as a cost on the position notional:
    ``cost = size_usdc * bps / 10_000``. Adjusted P&L = paper P&L − that cost.
    Slippage is a strictly non-negative cost (a worse fill), so it can only
    reduce P&L.
    """
    bps = float(model(inputs))
    if bps < 0.0:
        # A model must not return negative slippage; clamp + log rather than
        # silently crediting the trade.
        logger.warning("negative_slippage_clamped", market_id=market_id, bps=bps)
        bps = 0.0
    cost = inputs.size_usdc * (bps / 10_000.0)
    return ReplayTradeRecord(
        market_id=market_id,
        cell=cell,
        side=inputs.side,
        size_usdc=inputs.size_usdc,
        entry_price=inputs.entry_price,
        paper_pnl_usdc=paper_pnl_usdc,
        slippage_bps=bps,
        slippage_cost_usdc=cost,
        adjusted_pnl_usdc=paper_pnl_usdc - cost,
    )


def aggregate_by_cell(records: Sequence[ReplayTradeRecord]) -> dict[str, CellAggregate]:
    """Roll trade records up per cell, computing the >50% slippage gate per cell.

    ``slippage_fraction`` divides total slippage by the ABSOLUTE gross paper P&L,
    so the gate is meaningful for losing cells too (slippage relative to the
    magnitude of P&L at stake). A zero-gross-P&L cell has fraction 0.0 and never
    breaches (no P&L base to erode).
    """
    by_cell: dict[str, list[ReplayTradeRecord]] = {}
    for rec in records:
        by_cell.setdefault(rec.cell, []).append(rec)

    out: dict[str, CellAggregate] = {}
    for cell, recs in by_cell.items():
        gross = sum(r.paper_pnl_usdc for r in recs)
        slip = sum(r.slippage_cost_usdc for r in recs)
        adjusted = sum(r.adjusted_pnl_usdc for r in recs)
        base = abs(gross)
        frac = (slip / base) if base > 0 else 0.0
        out[cell] = CellAggregate(
            cell=cell,
            n_trades=len(recs),
            gross_paper_pnl_usdc=gross,
            total_slippage_usdc=slip,
            adjusted_pnl_usdc=adjusted,
            slippage_fraction=frac,
            gate_breached=frac > SLIPPAGE_PNL_GATE_FRAC,
        )
    return out


def overall_gate(aggregates: dict[str, CellAggregate]) -> tuple[float, bool]:
    """Return ``(overall_slippage_fraction, breached)`` across all cells.

    Aggregates total slippage against the summed ABSOLUTE per-cell gross P&L so
    cells with opposite-signed P&L don't cancel and mask an erosion problem.
    """
    total_slip = sum(a.total_slippage_usdc for a in aggregates.values())
    total_base = sum(abs(a.gross_paper_pnl_usdc) for a in aggregates.values())
    frac = (total_slip / total_base) if total_base > 0 else 0.0
    return frac, frac > SLIPPAGE_PNL_GATE_FRAC


# ---------------------------------------------------------------------------
# Untrusted-DB coercion
# ---------------------------------------------------------------------------


def _coerce_float(value: Any, default: float = 0.0) -> float:
    """Best-effort float coercion for untrusted DB values. NULL/garbage -> default."""
    if value is None:
        return default
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if out != out or out in (float("inf"), float("-inf")):  # NaN / inf guard
        return default
    return out


def _record_from_row(row: Any, model: SlippageModel) -> Optional[ReplayTradeRecord]:
    """Build one :class:`ReplayTradeRecord` from an untrusted DB row, or None.

    Every field is coerced + guarded; a malformed row returns None (caller skips
    + logs) rather than corrupting the aggregate or raising.
    """
    try:
        market_id = str(row["market_id"]) if row["market_id"] is not None else ""
        asset = str(row["asset"]) if row["asset"] is not None else ""
        timeframe = str(row["timeframe"]) if row["timeframe"] is not None else ""
        if not market_id or not asset or not timeframe:
            return None
        cell = normalize_cell(asset, timeframe)
        side = str(row["side"]).strip().upper() if row["side"] is not None else ""
        inputs = SlippageInputs(
            side=side,
            entry_price=_coerce_float(row["entry_price"]),
            size_usdc=_coerce_float(row["size_usdc"]),
            liquidity_usdc=_coerce_float(row["liquidity_usdc"]),
            spread=_coerce_float(row["spread"]),
            volatility_sigma=_coerce_float(row["volatility_sigma"]),
            orderbook_depth_usdc=_coerce_float(row["orderbook_depth_usdc"]),
        )
        paper_pnl = _coerce_float(row["pnl_usdc"])
        return replay_trade(
            market_id=market_id,
            cell=cell,
            inputs=inputs,
            paper_pnl_usdc=paper_pnl,
            model=model,
        )
    except Exception as exc:  # noqa: BLE001 — one bad row never aborts the replay
        logger.warning("replay_row_skipped", error=str(exc))
        return None


# ---------------------------------------------------------------------------
# DB loader (--from-db)
# ---------------------------------------------------------------------------


_FETCH_SQL = """
SELECT p.market_id        AS market_id,
       p.side             AS side,
       p.size_usdc        AS size_usdc,
       p.entry_price      AS entry_price,
       p.pnl_usdc         AS pnl_usdc,
       f.asset            AS asset,
       f.timeframe        AS timeframe,
       f.liquidity_usdc   AS liquidity_usdc,
       f.spread           AS spread,
       f.volatility_sigma AS volatility_sigma,
       f.orderbook_depth_usdc AS orderbook_depth_usdc
  FROM positions p
  JOIN LATERAL (
        SELECT fv.*
          FROM factor_vectors fv
         WHERE fv.market_id = p.market_id
           AND fv.data_source = $1
           AND fv.settled = TRUE
           AND p.opened_at >= fv.first_seen_at - make_interval(mins => $2)
           AND p.opened_at <= COALESCE(fv.settled_at, fv.first_seen_at)
                              + make_interval(mins => $3)
         ORDER BY ABS(EXTRACT(EPOCH FROM (p.opened_at - fv.first_seen_at)))
         LIMIT 1
       ) f ON TRUE
 WHERE p.mode = 'paper'
   AND p.status = 'closed'
   AND p.pnl_usdc IS NOT NULL
   AND p.opened_at > NOW() - make_interval(days => $4)
"""


async def load_paper_real_trades(
    *,
    days: int,
    cells: tuple[str, ...],
    model: SlippageModel,
    data_source: str = DATA_SOURCE_PAPER_REAL,
    join_pre_min: int = DEFAULT_JOIN_PRE_MIN,
    join_post_min: int = DEFAULT_JOIN_POST_MIN,
    pool: object | None = None,
) -> list[ReplayTradeRecord]:
    """Load + replay settled paper_real trades from the last ``days`` days.

    Joins ``positions`` to its nearest matching ``factor_vectors`` capture by
    ``market_id`` + ``opened_at`` window, filters to the requested ``cells``, and
    replays each through ``model``. Read-only and fail-soft: a DB error logs and
    returns ``[]``; per-row failures are skipped (see :func:`_record_from_row`).
    """
    from database import init_pool  # noqa: E402 — deferred so import never needs DB

    try:
        # init_pool() is idempotent (returns the existing pool if already
        # initialised); get_pool() would raise when run standalone via --from-db
        # because nothing initialises the pool first.
        pool = pool or await init_pool()
        async with pool.acquire() as conn:  # type: ignore[attr-defined]
            rows = await conn.fetch(
                _FETCH_SQL, data_source, join_pre_min, join_post_min, days
            )
    except Exception as exc:  # noqa: BLE001 — fail-soft analytics read
        logger.warning("replay_db_read_failed", error=str(exc))
        return []

    wanted = set(cells) if cells else None
    records: list[ReplayTradeRecord] = []
    for row in rows:
        rec = _record_from_row(row, model)
        if rec is None:
            continue
        if wanted is not None and rec.cell not in wanted:
            continue
        records.append(rec)
    logger.info(
        "replay_loaded",
        rows=len(rows),
        kept=len(records),
        cells=sorted(wanted) if wanted else "all",
        days=days,
    )
    return records


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def render_report(
    aggregates: dict[str, CellAggregate],
    *,
    days: int,
    n_trades: int,
) -> str:
    """Render a plain-text per-cell report + the catastrophic-gate verdict."""
    lines: list[str] = []
    lines.append("SLIPPAGE REPLAY — paper_real settled trades")
    lines.append(f"window: last {days}d   trades replayed: {n_trades}")
    lines.append("")
    header = (
        f"{'cell':<10} {'n':>4} {'paper_pnl':>12} {'slippage':>12} "
        f"{'adj_pnl':>12} {'slip_frac':>10} gate"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for cell in sorted(aggregates):
        a = aggregates[cell]
        flag = "BREACH" if a.gate_breached else "ok"
        lines.append(
            f"{a.cell:<10} {a.n_trades:>4} {a.gross_paper_pnl_usdc:>12.2f} "
            f"{a.total_slippage_usdc:>12.2f} {a.adjusted_pnl_usdc:>12.2f} "
            f"{a.slippage_fraction:>10.2%} {flag}"
        )
    frac, breached = overall_gate(aggregates)
    lines.append("-" * len(header))
    lines.append(f"OVERALL slippage fraction: {frac:.2%}")
    if breached:
        lines.append("")
        lines.append(
            "*** CATASTROPHIC GATE BREACHED: modeled slippage erases > "
            f"{SLIPPAGE_PNL_GATE_FRAC:.0%} of gross paper P&L. ***"
        )
        lines.append(
            "*** LIVE viability is NOT established. Escalate to WARP-CMD; do NOT "
            "decide. ***"
        )
    else:
        lines.append(
            f"gate ok: slippage within the {SLIPPAGE_PNL_GATE_FRAC:.0%} threshold."
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    import asyncio
    import logging

    parser = argparse.ArgumentParser(
        prog="replay_with_slippage", description=__doc__
    )
    parser.add_argument(
        "--days", type=int, default=7,
        help="Replay trades opened within the last N days (default 7).",
    )
    parser.add_argument(
        "--cells", default="BTC/5m,ETH/5m",
        help="Comma-separated cells to include (default BTC/5m,ETH/5m). "
             "Empty -> all cells.",
    )
    parser.add_argument(
        "--from-db", action="store_true",
        help="Read settled paper_real trades from the canonical DB (required to "
             "produce a real replay; without it nothing is read).",
    )
    parser.add_argument(
        "--data-source", default=DATA_SOURCE_PAPER_REAL,
        help="factor_vectors provenance filter (default paper_real).",
    )
    args = parser.parse_args(argv)

    if args.days <= 0:
        parser.error("--days must be a positive integer.")

    # Configure structlog AFTER arg validation so a bad-args exit never mutates
    # the process-wide logging config (mirrors the sibling scripts).
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO)
    )

    cells = parse_cells(args.cells)
    model = resolve_slippage_model()

    if not args.from_db:
        print(
            "No data source selected. Pass --from-db to replay settled paper_real "
            "trades from the DB.",
            file=sys.stderr,
        )
        return 2

    records = asyncio.run(
        load_paper_real_trades(
            days=args.days,
            cells=cells,
            model=model,
            data_source=args.data_source,
        )
    )
    if not records:
        print(
            "No settled paper_real trades joined for the requested window/cells.",
            file=sys.stderr,
        )
        return 2

    aggregates = aggregate_by_cell(records)
    print(render_report(aggregates, days=args.days, n_trades=len(records)))

    _, breached = overall_gate(aggregates)
    # Non-zero exit on a gate breach so a CI/operator wrapper can detect the
    # catastrophic condition without parsing stdout.
    return 3 if breached else 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "SlippageInputs",
    "SlippageModel",
    "DefaultSlippageModel",
    "ReplayTradeRecord",
    "CellAggregate",
    "resolve_slippage_model",
    "normalize_cell",
    "parse_cells",
    "replay_trade",
    "aggregate_by_cell",
    "overall_gate",
    "load_paper_real_trades",
    "render_report",
    "main",
    "SLIPPAGE_PNL_GATE_FRAC",
    "DATA_SOURCE_PAPER_REAL",
]
