"""Leaderboard sync — pulls H-Score leaderboard from Falcon API and upserts into DB.

Public surface:
    sync_leaderboard(pool)  — fetch + upsert one cycle
    run_job()               — scheduler wrapper (no-arg, calls get_pool() internally)

Schedule: run once at startup (after DB pool ready) + APScheduler every 30 minutes.
Never raises — logs warning on any error and returns.
"""
from __future__ import annotations

import logging
import math
import os
import time
from typing import Any

import aiohttp

from ...database import get_pool

log = logging.getLogger(__name__)

_FALCON_URL = "https://narrative.agent.heisenberg.so/api/v2/semantic/retrieve/parameterized"
_TIMEOUT = aiohttp.ClientTimeout(total=30)

_TIER_BADGE: dict[str, str] = {
    "Elite": "Whale",
    "Pro": "Hot Streak",
    "Advanced": "Conservative",
}


def _badge_from_tier(tier: str | None, win_rate: float | None, total_pnl: float | None) -> str | None:
    if tier and tier in _TIER_BADGE:
        return _TIER_BADGE[tier]
    # fallback logic
    wr = win_rate or 0.0
    pnl = total_pnl or 0.0
    if wr >= 0.75 and pnl > 5000:
        return "Whale"
    if wr >= 0.80:
        return "Hot Streak"
    if 0.65 <= wr < 0.80 and pnl > 0:
        return "Conservative"
    return None


def _safe_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _clamp(val: float | None, lo: float, hi: float) -> float | None:
    if val is None:
        return None
    return max(lo, min(hi, val))


async def sync_leaderboard(pool: Any) -> None:
    api_key = os.environ.get("HEISENBERG_API_TOKEN", "")
    if not api_key:
        log.warning("leaderboard sync: HEISENBERG_API_TOKEN not set — skipping")
        return

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "agent_id": 584,
        "params": {
            "min_win_rate_15d": "0.45",
            "max_win_rate_15d": "0.92",
            "min_roi_15d": "0",
            "min_total_trades_15d": "30",
            "max_total_trades_15d": "5000",
            "min_pnl_15d": "500",
            "sort_by": "h_score",
        },
        "pagination": {"limit": 50, "offset": 0},
        "formatter_config": {"format_type": "raw"},
    }

    t0 = time.monotonic()
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.post(_FALCON_URL, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    log.warning(
                        "leaderboard sync: Falcon API status=%d body=%s", resp.status, body[:200]
                    )
                    return
                data = await resp.json()
    except (aiohttp.ClientError, TimeoutError) as exc:
        log.warning("leaderboard sync: Falcon API request failed: %s", exc)
        return
    except Exception:
        log.exception("leaderboard sync: unexpected error fetching Falcon API")
        return

    results: list[dict] = data.get("data", {}).get("results", [])
    if not results:
        log.warning("leaderboard sync: empty results from Falcon API")
        return

    rows: list[tuple] = []
    for r in results:
        wallet = r.get("wallet")
        if not wallet:
            continue
        win_rate = _safe_float(r.get("win_rate_pct_15d"))
        if win_rate is not None and win_rate > 1.0:
            win_rate = win_rate / 100.0
        if win_rate is not None:
            win_rate = max(0.0, min(1.0, win_rate))
        total_pnl_in = r.get("total_pnl_15d")
        roi_pct_in = r.get("roi_pct_15d")
        volume_usdc_in = r.get("total_volume_15d")

        total_pnl = _safe_float(total_pnl_in)
        roi_pct = _safe_float(roi_pct_in)
        if roi_pct is not None and roi_pct > 1.0:
            roi_pct = roi_pct / 100.0
        volume_usdc = _safe_float(volume_usdc_in)

        # --- schema clamps (NUMERIC(8,4) / NUMERIC(18,6) column bounds) ---
        # _safe_float rejects NaN/infinity (→ None); _clamp handles large finite values.
        # Capture pre-clamp values and track whether any non-None input was filtered.
        roi_pct_raw, total_pnl_raw, volume_usdc_raw = roi_pct, total_pnl, volume_usdc
        roi_pct     = _clamp(roi_pct,     -9999.9999,            9999.9999)
        total_pnl   = _clamp(total_pnl,   -999999999999.999999,  999999999999.999999)
        volume_usdc = _clamp(volume_usdc,  0.0,                   999999999999.999999)
        filtered_non_finite = (
            (roi_pct_in is not None and roi_pct is None)
            or (total_pnl_in is not None and total_pnl is None)
            or (volume_usdc_in is not None and volume_usdc is None)
        )
        if (
            roi_pct != roi_pct_raw
            or total_pnl != total_pnl_raw
            or volume_usdc != volume_usdc_raw
            or filtered_non_finite
        ):
            log.warning(
                "leaderboard sync: numeric sanitation wallet=%s "
                "roi_in=%r roi_out=%s pnl_in=%r pnl_out=%s vol_in=%r vol_out=%s",
                wallet,
                roi_pct_in, roi_pct,
                total_pnl_in, total_pnl,
                volume_usdc_in, volume_usdc,
            )

        tier = r.get("tier")
        badge = _badge_from_tier(tier, win_rate, total_pnl)
        rows.append((wallet, None, win_rate, total_pnl, volume_usdc, roi_pct, badge))

    if not rows:
        log.warning("leaderboard sync: no valid wallet rows parsed")
        return

    async with pool.acquire() as conn:
        await conn.executemany(
            """INSERT INTO leaderboard_stats
                 (wallet, alias, win_rate, total_pnl, volume_usdc, roi_pct, badge, updated_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
               ON CONFLICT (wallet) DO UPDATE SET
                 alias        = EXCLUDED.alias,
                 win_rate     = EXCLUDED.win_rate,
                 total_pnl    = EXCLUDED.total_pnl,
                 volume_usdc  = EXCLUDED.volume_usdc,
                 roi_pct      = EXCLUDED.roi_pct,
                 badge        = EXCLUDED.badge,
                 updated_at   = NOW()""",
            rows,
        )
        deleted = await conn.fetchval(
            "DELETE FROM leaderboard_stats WHERE updated_at < NOW() - INTERVAL '2 hours' RETURNING 1"
        )

    elapsed = time.monotonic() - t0
    log.info(
        "leaderboard sync: %d wallets upserted in %.2fs (stale deleted=%s)",
        len(rows),
        elapsed,
        deleted is not None,
    )


async def run_job() -> None:
    try:
        pool = get_pool()
        await sync_leaderboard(pool)
    except Exception:
        log.exception("leaderboard sync: run_job failed")
