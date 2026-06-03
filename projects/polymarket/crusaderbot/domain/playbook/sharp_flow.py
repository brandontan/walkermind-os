"""PLAYBOOK Phase-2b — native sharp-money flow source.

Promotes the ``sharp_signed_usdc`` input of ``signals.sharp_money_reading`` from
a Phase-1 zero-stub to a live, **DB-backed** signal — no new external network
calls in the scan loop. Reuses the copy-trade infrastructure exactly as the
blueprint (§2.2, §Phase-2b) specifies:

* **Sharp-wallet set** — top-tier wallets from ``leaderboard_stats`` (synced by
  ``copy_trade.leaderboard_sync``): ``win_rate >= θ_wr`` AND ``total_pnl > 0``.
* **Per-market flow** — their recent trades from ``heisenberg_realtime_trades``
  (synced by ``jobs.heisenberg_realtime_sync``), summed as *signed* USDC:
  YES-accumulation positive, NO-accumulation negative.

For one market the *imbalance* ``sharp_signed_usdc / total_flow_usdc`` feeds the
existing ``sharp_money_reading`` formula; a persistent one-sided lean by
profitable wallets is the informed-flow edge ``SharpMoneyModule`` trades.

Fail-soft: any DB error returns empty flow (0.0, 0.0) so the scan loop never
breaks and the module simply does not claim. Pure read — no writes.
"""
from __future__ import annotations

import structlog

from ...database import get_pool

logger = structlog.get_logger(__name__)

# Top-tier "sharp" wallet thresholds (leaderboard_stats). Mirrors the
# leaderboard_sync "elite/strong" badge floor (win_rate>=0.65 & positive PnL):
# fewer, higher-conviction wallets — matches Sharp Money's low-frequency profile.
SHARP_MIN_WIN_RATE: float = 0.65
SHARP_MIN_TOTAL_PNL: float = 0.0

# Accumulation lookback — Sharp Money trades TTL>24h markets, so it reads
# multi-hour one-sided buildup rather than a single print.
SHARP_LOOKBACK_HOURS: int = 24

_BUY_ACTIONS: frozenset[str] = frozenset({"buy", "long", "bid"})
_SELL_ACTIONS: frozenset[str] = frozenset({"sell", "short", "ask"})
_OUTCOMES: frozenset[str] = frozenset({"yes", "no"})


def yes_accumulation_signed(tokens: list[str], size_usdc: float) -> float:
    """Signed YES-accumulation USDC for one trade.

    ``+size`` when the wallet BUYS YES or SELLS NO (bullish YES); ``-size`` when
    it BUYS NO or SELLS YES (bearish YES). Sign = outcome_sign × action_sign.

    The upstream trade fields are inconsistent — the stored ``side`` column is
    ``side or direction or outcome``, and the raw payload can carry the outcome
    in ``side`` while the action lives in ``direction`` (or vice-versa). So
    rather than positionally trusting any one field, every candidate token is
    classified **by value**: the first token that is an outcome (yes/no) sets the
    outcome, the first that is an action (buy/sell/…) sets the action. This
    prevents an outcome-valued ``side`` from shadowing a real ``direction``
    action (Codex P2) and a BUY-of-NO from being counted as YES (Codex P1).

    A trade whose outcome AND action cannot both be determined returns ``0.0`` —
    it still counts toward *total* flow (magnitude) but never the signed sum, so
    a directionally-unknown book can never flip the side.
    """
    norm = [str(t or "").strip().lower() for t in tokens]
    outcome = next((t for t in norm if t in _OUTCOMES), "")
    action = next((t for t in norm if t in _BUY_ACTIONS or t in _SELL_ACTIONS), "")
    if not outcome or not action:
        return 0.0
    outcome_sign = 1.0 if outcome == "yes" else -1.0
    action_sign = 1.0 if action in _BUY_ACTIONS else -1.0
    return outcome_sign * action_sign * size_usdc


async def fetch_sharp_flows(
    condition_ids: list[str],
    *,
    lookback_hours: int = SHARP_LOOKBACK_HOURS,
    min_win_rate: float = SHARP_MIN_WIN_RATE,
    min_total_pnl: float = SHARP_MIN_TOTAL_PNL,
) -> dict[str, tuple[float, float]]:
    """Return ``{condition_id: (sharp_signed_usdc, total_flow_usdc)}`` for the
    given markets, restricted to top-tier sharp wallets over the lookback.

    One batched query for the whole scan's market set; the per-trade rows are
    summed in Python via ``yes_accumulation_signed`` (so the directional logic is
    unit-tested, not buried in SQL). The row count is small and bounded — the
    sharp set is the ≤50-wallet top-tier leaderboard, the far band is ≤20 markets,
    over a 24h window. Markets with no flow are absent from the result (caller
    defaults them to 0.0/0.0). Fail-soft: on any error returns an empty mapping.
    """
    if not condition_ids:
        return {}
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT t.condition_id          AS condition_id,
                       t.raw->>'outcome'       AS raw_outcome,
                       t.raw->>'side'          AS raw_side,
                       t.raw->>'direction'     AS raw_direction,
                       t.side                  AS side_col,
                       COALESCE(t.size_usdc, 0) AS size_usdc
                  FROM heisenberg_realtime_trades t
                  JOIN leaderboard_stats l ON l.wallet = t.wallet
                 WHERE t.condition_id = ANY($1::text[])
                   AND t.trade_time > NOW() - make_interval(hours => $2)
                   AND l.win_rate >= $3
                   AND l.total_pnl > $4
                """,
                condition_ids, lookback_hours, min_win_rate, min_total_pnl,
            )
    except Exception as exc:  # noqa: BLE001 — fail-soft, never break the scan loop
        logger.warning("playbook_sharp_flow_fetch_failed", error=str(exc))
        return {}

    agg: dict[str, list[float]] = {}  # cid -> [signed, total]
    for r in rows:
        cid = str(r["condition_id"] or "")
        size = float(r["size_usdc"] or 0.0)
        if not cid or size <= 0.0:
            continue
        # Classify by value — outcome and action may live in any of these fields.
        signed = yes_accumulation_signed(
            [r["raw_outcome"], r["raw_side"], r["raw_direction"], r["side_col"]],
            size,
        )
        bucket = agg.setdefault(cid, [0.0, 0.0])
        bucket[0] += signed
        bucket[1] += size
    return {cid: (sg, tot) for cid, (sg, tot) in agg.items() if tot > 0.0}


__all__ = [
    "fetch_sharp_flows",
    "yes_accumulation_signed",
    "SHARP_MIN_WIN_RATE",
    "SHARP_MIN_TOTAL_PNL",
    "SHARP_LOOKBACK_HOURS",
]
