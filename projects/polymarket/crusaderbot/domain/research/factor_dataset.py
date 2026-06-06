"""Durable factor-vector dataset sink (WARP-72 Phase 2 prep, WARP•R00T).

Persists the SMART STRIKE 7-factor vector into ``factor_vectors`` so the Phase-2
scorer can derive weights from a real, settled-outcome dataset (Phase 1 only emits
ephemeral logs + candidate metadata). Pure shadow telemetry — never selects, sizes,
gates, or blocks a trade; every write is fail-soft and gated by the caller.

GRAIN: ONE row per candle, keyed by ``condition_id`` (each candle slot is a distinct
Polymarket market). The recorder UPSERTs latest-wins so the many scans of a single
candle collapse to one labeled example — never one row per scan tick.

LABEL lifecycle:
  * ``record_factor_vector`` writes the entry-decision snapshot with the PROVISIONAL
    outcome (open->now), ``settled=FALSE``.
  * ``backfill_factor_settlement`` resolves the realized open->close outcome from the
    oracle ring once the candle has closed, sets ``outcome_source='open_to_close'``
    + ``settled=TRUE``. Phase 2 trains on settled ``open_to_close`` rows only.

A settled row is immutable to the recorder (the UPSERT's ``WHERE settled = FALSE``
guard), so a late scan can never clobber a resolved label.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Optional

import structlog

from ...database import get_pool
from ..signal.factors import FactorVector, realized_candle_outcome

logger = structlog.get_logger(__name__)

# Write-churn throttle: the factor vector is market-level (identical across users),
# so without this every candle-preset user would re-UPSERT the same candle row each
# scan tick. Keyed by condition_id; the PK UPSERT already guarantees one ROW, this
# just bounds write volume. 5s is far below the 5m/15m candle horizon, so the final
# pre-close snapshot still lands within seconds of the entry decision.
DEFAULT_MIN_WRITE_GAP_SEC: float = 5.0
_MAX_THROTTLE_KEYS: int = 2048
_THROTTLE_PRUNE_SEC: float = 3600.0
_last_write: dict[str, float] = {}

# How long after candle close the oracle ring still holds the open tick
# (ORACLE_HISTORY_WINDOW_SEC default 1800s). Past this the open is unrecoverable —
# stop retrying and mark the row 'unresolved' so the backfill loop stays bounded.
DEFAULT_RING_WINDOW_SEC: float = 1800.0

# WARP-78 label fix: safe_close force-exits ~30s BEFORE candle close (the strategy's
# safe_close force_exit_at_rem_sec; see late_entry_v3 / exit_watcher). So its realized
# label is the underlying direction open→(close − 30s), NOT open→close. We record that
# horizon's outcome alongside the open→close label so the EV trainer/A/B can judge
# safe_close at its real exit (and so it stops sharing close_sweep's identical label).
# close_sweep (~8s ≈ close) and flip_hunter (hold-to-settlement) keep open→close.
# NOTE: mirrors the strategy's 30s; centralizing this constant is a follow-up.
SAFE_CLOSE_EXIT_LEAD_SEC: float = 30.0


# INSERT column order — the value tuple in ``_row`` MUST stay aligned with this.
_COLS: tuple[str, ...] = (
    "condition_id", "market_id", "slug", "asset", "timeframe", "evaluated_rule",
    "router_selected_rule", "selected_by_router",
    "momentum", "momentum_delta", "momentum_span_sec", "momentum_samples",
    "volatility_sigma", "realized_vol", "liquidity_usdc", "spread", "orderbook_depth_usdc",
    "ttl_sec", "oracle_edge", "oracle_edge_status", "oracle_would_pass", "oracle_delta",
    "fav_side", "entry_side", "fav_price", "entry_price", "ask_diff",
    "complete_set_edge", "underdog_mode",
    "realized_outcome", "realized_delta", "outcome_source", "outcome_observed_rem_sec",
    "candle_open_epoch", "candle_close_epoch",
)

# Provenance tag (WARP-77 Phase 1.4): the data regime a row was captured under.
# Supplied at write time from runtime config (NOT a FactorVector field) and
# appended after the fv-derived columns in the INSERT.
DATA_SOURCE_PAPER_SYNTHETIC: str = "paper_synthetic"
DATA_SOURCE_PAPER_REAL: str = "paper_real"
DATA_SOURCE_LIVE_REAL: str = "live_real"
_PROVENANCE_COL: str = "data_source"

# Full INSERT column order = fv-derived columns + the provenance tag. The value
# tuple in ``_row`` covers ``_COLS``; the provenance value is appended explicitly.
_INSERT_COLS: tuple[str, ...] = _COLS + (_PROVENANCE_COL,)

# Snapshot columns refreshed on a latest-wins UPSERT (everything except the PK,
# first_seen_at, the settlement columns, and the two merge-special columns handled
# explicitly in the SET clause below). ``data_source`` IS refreshed so a row
# re-seen after a data-regime change reflects the current regime.
_UPDATE_COLS: tuple[str, ...] = tuple(
    c for c in _INSERT_COLS if c not in ("condition_id", "router_selected_rule", "selected_by_router")
)


def resolve_data_source(settings: Any) -> str:
    """Provenance tag for a ``factor_vectors`` row from the runtime data regime.

    * ``live_real``       — the bot is actually in LIVE mode, i.e. ALL THREE
      activation guards are open (``ENABLE_LIVE_TRADING`` +
      ``EXECUTION_PATH_VALIDATED`` + ``CAPITAL_MODE_CONFIRMED``). This reuses the
      canonical ``config.resolve_trading_mode`` so the provenance label can never
      diverge from the real paper/live posture: ``ENABLE_LIVE_TRADING`` alone, with
      the other guards unvalidated, is still PAPER and must NOT be tagged live.
    * ``paper_real``      — paper sizing on the real CLOB v2 backend (``USE_PYSDK_CLOB``).
    * ``paper_synthetic`` — default: paper sizing on the legacy/synthetic data path
      (matches every historical row, and the column DEFAULT).

    Fail-soft to ``paper_synthetic`` on any read error — provenance must never
    break or block a write.
    """
    try:
        from ...config import resolve_trading_mode

        if resolve_trading_mode(settings) == "live":
            return DATA_SOURCE_LIVE_REAL
        if bool(getattr(settings, "USE_PYSDK_CLOB", False)):
            return DATA_SOURCE_PAPER_REAL
    except Exception:  # noqa: BLE001 — provenance never breaks the write
        return DATA_SOURCE_PAPER_SYNTHETIC
    return DATA_SOURCE_PAPER_SYNTHETIC


def _placeholders(n: int) -> str:
    return ", ".join(f"${i}" for i in range(1, n + 1))


def _row(fv: FactorVector) -> tuple:
    """Value tuple aligned to ``_COLS`` (selected_by_router coerced to bool)."""
    out = []
    for c in _COLS:
        v = getattr(fv, c, None)
        if c == "selected_by_router":
            v = bool(v)
        out.append(v)
    return tuple(out)


_UPSERT_SQL = f"""
INSERT INTO factor_vectors ({", ".join(_INSERT_COLS)})
VALUES ({_placeholders(len(_INSERT_COLS))})
ON CONFLICT (condition_id) DO UPDATE SET
    {", ".join(f"{c} = EXCLUDED.{c}" for c in _UPDATE_COLS)},
    router_selected_rule = COALESCE(EXCLUDED.router_selected_rule, factor_vectors.router_selected_rule),
    selected_by_router = factor_vectors.selected_by_router OR EXCLUDED.selected_by_router,
    updated_at = NOW()
WHERE factor_vectors.settled = FALSE
"""


def _throttled(condition_id: str, now: float, min_gap_sec: float) -> bool:
    """Return True if a write for this candle happened within ``min_gap_sec``."""
    last = _last_write.get(condition_id)
    if last is not None and (now - last) < min_gap_sec:
        return True
    _last_write[condition_id] = now
    if len(_last_write) > _MAX_THROTTLE_KEYS:
        cutoff = now - _THROTTLE_PRUNE_SEC
        for k in [k for k, ts in _last_write.items() if ts < cutoff]:
            _last_write.pop(k, None)
    return False


async def record_factor_vector(
    fv: FactorVector,
    *,
    pool: object | None = None,
    now: float | None = None,
    min_write_gap_sec: float = DEFAULT_MIN_WRITE_GAP_SEC,
    data_source: str | None = None,
) -> bool:
    """UPSERT one candle's factor vector (latest-wins). Returns True on write.

    Fail-soft: any error logs and returns False — the scan loop is never broken.
    Throttled per condition_id to bound write churn; a settled row is left
    untouched by the ON CONFLICT guard.
    """
    try:
        if not fv.condition_id:
            return False
        now = time.time() if now is None else now
        # Reserve the throttle slot synchronously (prevents a concurrent scan of
        # the same candle from double-writing across the awaited DB call)...
        if _throttled(fv.condition_id, now, min_write_gap_sec):
            return False
        if data_source is None:
            try:
                from ...config import get_settings

                data_source = resolve_data_source(get_settings())
            except Exception:  # noqa: BLE001 — fail-soft to the historical default
                data_source = DATA_SOURCE_PAPER_SYNTHETIC
        pool = pool or get_pool()
        try:
            async with pool.acquire() as conn:  # type: ignore[attr-defined]
                await conn.execute(_UPSERT_SQL, *_row(fv), data_source)
        except Exception:
            # ...but RELEASE it on failure so the next scan retries promptly and a
            # transient DB error can't drop a candle's final pre-close snapshot.
            _last_write.pop(fv.condition_id, None)
            raise
        return True
    except Exception as exc:  # noqa: BLE001 — fail-soft, never break the scan loop
        logger.warning("factor_vector_persist_failed", error=str(exc))
        return False


async def mark_router_selection_row(
    condition_id: str,
    rule: str | None,
    *,
    pool: object | None = None,
) -> bool:
    """Stamp the router-selected rule onto an unsettled candle row. Fail-soft.

    Advisory only — records which rule the precedence router actually picked
    (the recorder writes the snapshot before selection is known). Never touches a
    settled row.
    """
    try:
        if not condition_id:
            return False
        pool = pool or get_pool()
        async with pool.acquire() as conn:  # type: ignore[attr-defined]
            await conn.execute(
                """
                UPDATE factor_vectors
                   SET router_selected_rule = $2,
                       selected_by_router = TRUE,
                       updated_at = NOW()
                 WHERE condition_id = $1 AND settled = FALSE
                """,
                condition_id, rule,
            )
        return True
    except Exception as exc:  # noqa: BLE001 — fail-soft
        logger.warning("factor_vector_router_mark_failed", error=str(exc))
        return False


async def backfill_factor_settlement(
    price_at: Callable[[str, float], Optional[float]],
    *,
    now: float | None = None,
    ring_window_sec: float = DEFAULT_RING_WINDOW_SEC,
    limit: int = 500,
    pool: object | None = None,
) -> int:
    """Resolve realized open->close outcomes for closed, unsettled candles.

    For each unsettled row whose candle has closed, read the underlying price at
    the candle open and close from the oracle ring (``price_at(symbol, epoch)``)
    and write the settled label (``outcome_source='open_to_close'``). Rows whose
    open tick has aged out of the ring are marked ``unresolved`` so the loop stays
    bounded. Returns the number of rows settled this pass. Fail-soft.
    """
    now = time.time() if now is None else now
    try:
        pool = pool or get_pool()
        async with pool.acquire() as conn:  # type: ignore[attr-defined]
            rows = await conn.fetch(
                """
                SELECT condition_id, asset, candle_open_epoch, candle_close_epoch
                  FROM factor_vectors
                 WHERE settled = FALSE
                   AND candle_close_epoch IS NOT NULL
                   AND candle_close_epoch <= $1
                 ORDER BY candle_close_epoch ASC
                 LIMIT $2
                """,
                now, limit,
            )
    except Exception as exc:  # noqa: BLE001 — fail-soft
        logger.warning("factor_settlement_select_failed", error=str(exc))
        return 0

    settled = 0
    for r in rows:
        try:
            cid = r["condition_id"]
            asset = r["asset"]
            open_epoch = r["candle_open_epoch"]
            close_epoch = r["candle_close_epoch"]
            symbol = f"{asset}/usd" if asset else None
            open_p = close_p = None
            if symbol and open_epoch is not None and close_epoch is not None:
                open_p = price_at(symbol, float(open_epoch))
                close_p = price_at(symbol, float(close_epoch))
            if open_p is not None and close_p is not None:
                outcome, delta = realized_candle_outcome(float(open_p), float(close_p))
                # WARP-78 label fix: also resolve the safe_close horizon outcome at
                # open→(close − SAFE_CLOSE_EXIT_LEAD_SEC) from the same ring. NULL when
                # that tick isn't in the ring — honest, like the open→close label.
                sc_outcome: str | None = None
                sc_delta: float | None = None
                sc_p = price_at(symbol, float(close_epoch) - SAFE_CLOSE_EXIT_LEAD_SEC)
                if sc_p is not None:
                    sc_outcome, sc_delta = realized_candle_outcome(
                        float(open_p), float(sc_p)
                    )
                await _write_settled(
                    pool, cid, outcome, delta, float(open_p), float(close_p),
                    "open_to_close", sc_outcome, sc_delta,
                )
                settled += 1
            elif close_epoch is not None and (now - float(close_epoch)) > ring_window_sec:
                # Open tick aged out of the ring — unrecoverable; stop retrying.
                await _write_settled(pool, cid, None, None, None, None, "unresolved")
        except Exception as exc:  # noqa: BLE001 — one row's failure never aborts the pass
            logger.warning("factor_settlement_row_failed", error=str(exc))
    return settled


async def _write_settled(
    pool: object,
    condition_id: str,
    outcome: str | None,
    delta: float | None,
    open_price: float | None,
    close_price: float | None,
    source: str,
    sc_outcome: str | None = None,
    sc_delta: float | None = None,
) -> None:
    """Mark a candle row settled with its resolved (or unresolved) label.

    ``sc_outcome`` / ``sc_delta`` are the WARP-78 safe_close-horizon label
    (open→close−30s); COALESCE-guarded so the unresolved path (which passes None)
    never clobbers an existing value.
    """
    async with pool.acquire() as conn:  # type: ignore[attr-defined]
        await conn.execute(
            """
            UPDATE factor_vectors
               SET realized_outcome = COALESCE($2, realized_outcome),
                   realized_delta = COALESCE($3, realized_delta),
                   open_price = $4,
                   close_price = $5,
                   outcome_source = $6,
                   realized_outcome_safe_close = COALESCE($7, realized_outcome_safe_close),
                   realized_delta_safe_close = COALESCE($8, realized_delta_safe_close),
                   settled = TRUE,
                   settled_at = NOW(),
                   updated_at = NOW()
             WHERE condition_id = $1 AND settled = FALSE
            """,
            condition_id, outcome, delta, open_price, close_price, source,
            sc_outcome, sc_delta,
        )


__all__ = [
    "record_factor_vector",
    "mark_router_selection_row",
    "backfill_factor_settlement",
    "resolve_data_source",
    "DATA_SOURCE_PAPER_SYNTHETIC",
    "DATA_SOURCE_PAPER_REAL",
    "DATA_SOURCE_LIVE_REAL",
    "DEFAULT_MIN_WRITE_GAP_SEC",
    "DEFAULT_RING_WINDOW_SEC",
]
