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


async def fetch_sharp_flows(
    condition_ids: list[str],
    *,
    lookback_hours: int = SHARP_LOOKBACK_HOURS,
    min_win_rate: float = SHARP_MIN_WIN_RATE,
    min_total_pnl: float = SHARP_MIN_TOTAL_PNL,
) -> dict[str, tuple[float, float]]:
    """Return ``{condition_id: (sharp_signed_usdc, total_flow_usdc)}`` for the
    given markets, restricted to top-tier sharp wallets over the lookback.

    One batched, indexed aggregate query for the whole scan's market set (not
    per-market) to keep scan-loop cost flat. Markets with no sharp flow are
    simply absent from the result (caller defaults them to 0.0/0.0). Fail-soft:
    on any error returns an empty mapping.

    Signed convention: a trade is YES-accumulation (``+size_usdc``) when its
    side normalises to yes/buy/long, NO-accumulation (``-size_usdc``) when
    no/sell/short; anything else contributes magnitude only.
    """
    if not condition_ids:
        return {}
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT t.condition_id,
                       SUM(
                         CASE
                           WHEN lower(t.side) IN ('yes', 'buy', 'long')  THEN  t.size_usdc
                           WHEN lower(t.side) IN ('no', 'sell', 'short') THEN -t.size_usdc
                           ELSE 0
                         END
                       ) AS signed_usdc,
                       SUM(COALESCE(t.size_usdc, 0)) AS total_usdc
                  FROM heisenberg_realtime_trades t
                  JOIN leaderboard_stats l ON l.wallet = t.wallet
                 WHERE t.condition_id = ANY($1::text[])
                   AND t.trade_time > NOW() - make_interval(hours => $2)
                   AND l.win_rate >= $3
                   AND l.total_pnl > $4
                 GROUP BY t.condition_id
                """,
                condition_ids, lookback_hours, min_win_rate, min_total_pnl,
            )
    except Exception as exc:  # noqa: BLE001 — fail-soft, never break the scan loop
        logger.warning("playbook_sharp_flow_fetch_failed", error=str(exc))
        return {}

    out: dict[str, tuple[float, float]] = {}
    for r in rows:
        cid = str(r["condition_id"] or "")
        if not cid:
            continue
        signed = float(r["signed_usdc"] or 0.0)
        total = float(r["total_usdc"] or 0.0)
        if total <= 0.0:
            continue
        out[cid] = (signed, total)
    return out


__all__ = [
    "fetch_sharp_flows",
    "SHARP_MIN_WIN_RATE",
    "SHARP_MIN_TOTAL_PNL",
    "SHARP_LOOKBACK_HOURS",
]
