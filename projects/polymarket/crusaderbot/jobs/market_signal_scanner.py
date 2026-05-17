"""Market signal scanner — edge-finder + momentum_reversal publication writer.

Dual-feed pipeline:
  Demo path (DEMO_FEED_ID): Polymarket API prices, is_demo=TRUE, edge scoring
  Live path (LIVE_FEED_ID): Heisenberg agents 568/575/585, is_demo=FALSE, candle logic

Both feeds write to signal_publications for signal_following pipeline to consume.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID

import structlog

from ..config import get_settings
from ..database import get_pool
from ..integrations import polymarket
from ..services import heisenberg

log = structlog.get_logger(__name__)

# Feed UUIDs — must match migration seeds
DEMO_FEED_ID: UUID = UUID("00000000-0000-0000-0001-000000000001")  # migration 024
LIVE_FEED_ID: UUID = UUID("00000000-0000-0000-0002-000000000001")  # migration 025

# Legacy constant preserved for backward compat with existing test mocks only.
# Runtime thresholds are now read from config (SCANNER_* env vars).
EDGE_PRICE_THRESHOLD: float = 0.15

# Live path thresholds
EDGE_DEVIATION_PCT: float = 0.08       # legacy — overridden by SCANNER_EDGE_DEVIATION_PCT
MOMENTUM_CANDLES: int = 3              # consecutive candles in one direction

# Shared config
MIN_LIQUIDITY: float = 10_000.0        # legacy — scanner uses SCANNER_MIN_LIQUIDITY (5k)
DEDUP_WINDOW_HOURS: int = 2
SIGNAL_EXPIRY_HOURS: int = 4
DEFAULT_SIGNAL_SIZE_USDC: float = 10.0
DEFAULT_CONFIDENCE: float = 0.65
LIVE_MARKETS_PER_CYCLE: int = 20

# Heisenberg agent IDs
_AGENT_CANDLESTICKS = 568
_AGENT_LIQUIDITY = 575
_AGENT_SOCIAL = 585

JOB_ID = "market_signal_scanner"

_scanner_state: dict = {
    "scanned": 0,
    "published": 0,
    "last_tick_ts": None,  # float | None — UTC epoch
}


def get_scanner_state() -> dict:
    """Return a snapshot of the last scanner tick state.

    Module-level singleton — adequate for single-instance MVP.
    Multi-worker deployments should move this to Redis.
    """
    return dict(_scanner_state)


# ---- Shared DB helpers ----

async def _feed_active(feed_id: UUID) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM signal_feeds WHERE id=$1 AND status='active'",
            feed_id,
        )
    return row is not None


async def _already_published(feed_id: UUID, market_id: str, side: str) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=DEDUP_WINDOW_HOURS)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT 1 FROM signal_publications
             WHERE feed_id=$1 AND market_id=$2 AND side=$3
               AND exit_signal=FALSE AND exit_published_at IS NULL
               AND published_at > $4
            """,
            feed_id, market_id, side, cutoff,
        )
    return row is not None


async def _publish(
    feed_id: UUID,
    market_id: str,
    side: str,
    target_price: float,
    signal_type: str,
    payload: dict,
    is_demo: bool,
) -> None:
    expires_at = datetime.now(timezone.utc) + timedelta(hours=SIGNAL_EXPIRY_HOURS)
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO signal_publications
                (feed_id, market_id, side, target_price, signal_type,
                 payload, exit_signal, published_at, expires_at, is_demo)
            VALUES ($1,$2,$3,$4,$5,$6::jsonb,FALSE,NOW(),$7,$8)
            """,
            feed_id, market_id, side, target_price, signal_type,
            json.dumps(payload), expires_at, is_demo,
        )


# ---- Live path signal logic ----

def _candle_close(c: dict) -> float | None:
    v = c.get("c") or c.get("close")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _check_edge_finder(candles: list[dict]) -> tuple[str | None, float]:
    """Return (side, latest_close) if candle deviation exceeds threshold, else (None, 0)."""
    deviation_pct = get_settings().SCANNER_EDGE_DEVIATION_PCT
    closes = [_candle_close(c) for c in candles]
    closes = [v for v in closes if v is not None]
    if len(closes) < 6:
        return None, 0.0
    mean6h = sum(closes[-6:]) / 6
    if mean6h == 0:
        return None, 0.0
    latest = closes[-1]
    if abs(latest - mean6h) / mean6h <= deviation_pct:
        return None, 0.0
    return ("YES" if latest < mean6h else "NO"), latest


def _check_momentum(candles: list[dict]) -> str | None:
    """Return side if last 3 consecutive candles trend same direction, else None."""
    closes = [_candle_close(c) for c in candles[-(MOMENTUM_CANDLES + 1):]]
    closes = [v for v in closes if v is not None]
    if len(closes) < MOMENTUM_CANDLES + 1:
        return None
    diffs = [closes[i + 1] - closes[i] for i in range(len(closes) - 1)]
    tail = diffs[-MOMENTUM_CANDLES:]
    if all(d > 0 for d in tail):
        return "YES"
    if all(d < 0 for d in tail):
        return "NO"
    return None


_STOPWORDS = frozenset({
    "will", "the", "a", "an", "of", "in", "is", "are", "be", "to",
    "for", "at", "and", "or", "but", "by", "on", "with", "this",
    "that", "have", "has", "had", "from", "as", "it", "its", "was",
})


def extract_keywords(question: str) -> str:
    words = [
        w.strip("?.,!;:") for w in question.split()
        if w.strip("?.,!;:").lower() not in _STOPWORDS and len(w.strip("?.,!;:")) > 2
    ]
    return ",".join(words[:3])


# ---- Live path scan ----

async def _run_heisenberg_signals() -> tuple[int, int]:
    """Scan real non-demo markets using Heisenberg agents. Returns (scanned, published)."""
    if not os.getenv("HEISENBERG_API_TOKEN", ""):
        log.warning("heisenberg_token_missing",
                    message="HEISENBERG_API_TOKEN not set — skipping live scan")
        return 0, 0

    if not await _feed_active(LIVE_FEED_ID):
        log.warning("live_feed_inactive",
                    message="live feed not found — run migration 025")
        return 0, 0

    pool = get_pool()
    async with pool.acquire() as conn:
        markets = await conn.fetch(
            """
            SELECT id, condition_id, yes_token_id, question
              FROM markets
             WHERE status='active' AND is_demo=FALSE
               AND (resolved=FALSE OR resolved IS NULL)
             LIMIT $1
            """,
            LIVE_MARKETS_PER_CYCLE,
        )

    if not markets:
        return 0, 0

    scanned = 0
    published = 0
    now = int(time.time())

    for row in markets:
        market_id = str(row["condition_id"] or row["id"])
        token_id = row["yes_token_id"]
        question = str(row["question"] or "")

        try:
            # A. Liquidity screen
            liq_results = await heisenberg.retrieve(
                _AGENT_LIQUIDITY,
                {"condition_id": market_id, "min_volume_24h": "1000"},
                limit=1,
            )
            if not liq_results:
                continue
            liq = liq_results[0]
            if liq.get("volume_collapse_risk_flag") or liq.get("liquidity_tier") == "very_low":
                continue

            # B. Candlestick data (requires yes_token_id)
            if not token_id:
                continue
            candle_results = await heisenberg.retrieve(
                _AGENT_CANDLESTICKS,
                {
                    "token_id": token_id,
                    "interval": "1h",
                    "start_time": str(now - 86400),
                    "end_time": str(now),
                },
                limit=50,
            )
            if len(candle_results) < 6:
                continue

            scanned += 1

            # C. Signal logic
            edge_side, edge_price = _check_edge_finder(candle_results)
            mom_side = _check_momentum(candle_results)
            latest_close = _candle_close(candle_results[-1]) or 0.0

            signals = [
                ("edge_finder", edge_side, edge_price),
                ("momentum_reversal", mom_side, latest_close),
            ]
            for sig_type, side, price in signals:
                if not side:
                    continue
                if await _already_published(LIVE_FEED_ID, market_id, side):
                    continue

                payload: dict = {
                    "strategy": sig_type,
                    "question": question[:200],
                    "confidence": DEFAULT_CONFIDENCE,
                    "size_usdc": DEFAULT_SIGNAL_SIZE_USDC,
                }

                # D. Social pulse enrichment (non-blocking)
                try:
                    kw = extract_keywords(question)
                    social = await heisenberg.retrieve(
                        _AGENT_SOCIAL,
                        {"keywords": "{" + kw + "}", "hours_back": "6"},
                        limit=1,
                    )
                    if social:
                        s = social[0]
                        if (
                            float(s.get("acceleration") or 0) > 1.2
                            and float(s.get("author_diversity_pct") or 0) > 40
                        ):
                            payload["social_momentum"] = True
                except Exception as exc:
                    log.debug("social_pulse_failed", market_id=market_id, error=str(exc))

                await _publish(
                    LIVE_FEED_ID, market_id, side, price,
                    sig_type, payload, is_demo=False,
                )
                published += 1
                log.info("live_signal_published",
                         market_id=market_id, side=side,
                         signal_type=sig_type, price=price)

        except Exception as exc:
            log.warning("live_market_failed", market_id=market_id, error=str(exc))

    return scanned, published


# ---- Main entry ----

async def run_job() -> tuple[int, int]:
    """Run one scan tick. Returns (markets_scanned, signals_published).

    Demo path uses Polymarket API prices with threshold edge logic (is_demo=TRUE).
    Live path uses Heisenberg candlestick + liquidity agents (is_demo=FALSE).
    """
    demo_scanned = 0
    demo_published = 0

    if await _feed_active(DEMO_FEED_ID):
        cfg = get_settings()
        edge_min_price: float = cfg.SCANNER_EDGE_MIN_PRICE
        edge_max_price: float = cfg.SCANNER_EDGE_MAX_PRICE
        min_edge_bps: int = cfg.SCANNER_MIN_EDGE_BPS
        min_confidence: float = cfg.SCANNER_MIN_CONFIDENCE
        min_liq: float = cfg.SCANNER_MIN_LIQUIDITY

        try:
            markets = await polymarket.get_markets(limit=200)
        except Exception as exc:
            log.warning("polymarket_fetch_failed", error=str(exc))
            markets = []

        _demo_rejected = 0
        _demo_errors = 0

        log.info("signal_scan_cycle_start", scanning=len(markets or []))

        for m in markets or []:
            mid = "unknown"
            try:
                mid = str(m.get("conditionId") or m.get("id") or "")
                if m.get("closed") or m.get("resolved"):
                    _demo_rejected += 1
                    continue
                if not mid:
                    _demo_errors += 1
                    continue
                liq = float(m.get("liquidity") or 0)
                if liq < min_liq:
                    log.debug("signal_scan_market", market_id=mid, result="REJECTED",
                              reason="low_liquidity", liquidity=liq)
                    _demo_rejected += 1
                    continue

                outcomes = m.get("outcomePrices") or [None, None]
                # Polymarket Gamma API returns outcomePrices as a JSON-encoded
                # string (e.g. '["0.565", "0.435"]') rather than a parsed list.
                # Deserialise before indexing — direct float(outcomes[0]) on the
                # raw string raises ValueError, which the except block catches and
                # silently skips the market, producing zero signal publications.
                if isinstance(outcomes, str):
                    import json as _json
                    try:
                        outcomes = _json.loads(outcomes)
                    except Exception:
                        outcomes = [None, None]
                yes_p: float | None = (
                    float(outcomes[0]) if outcomes and outcomes[0] is not None else None
                )
                no_p: float | None = (
                    float(outcomes[1])
                    if len(outcomes) > 1 and outcomes[1] is not None
                    else None
                )

                if yes_p is None:
                    log.debug("signal_scan_market", market_id=mid, result="REJECTED",
                              reason="no_price")
                    _demo_rejected += 1
                    continue

                # Price eligibility: skip near-resolved markets
                if not (edge_min_price <= yes_p <= edge_max_price):
                    log.debug("signal_scan_market", market_id=mid, result="REJECTED",
                              reason="price_out_of_range", yes_price=yes_p)
                    _demo_rejected += 1
                    continue

                # Edge scoring: fair value baseline is 0.5 for binary markets
                edge = abs(yes_p - 0.5)
                edge_bps = int(edge * 10_000)

                if edge_bps < min_edge_bps:
                    log.debug("signal_scan_market", market_id=mid, result="REJECTED",
                              reason="insufficient_edge", edge_bps=edge_bps,
                              min_edge_bps=min_edge_bps, yes_price=yes_p)
                    _demo_rejected += 1
                    continue

                # All filters passed — count as approved
                demo_scanned += 1

                # Side: buy the underpriced outcome
                side = "YES" if yes_p < 0.5 else "NO"
                confidence = min(min_confidence + edge * 2.0, 0.90)
                target_price = yes_p if side == "YES" else (no_p or round(1.0 - yes_p, 4))

                log.info("signal_scan_market", market_id=mid, yes_price=yes_p,
                         edge_bps=edge_bps, liquidity=liq, side=side, result="APPROVED")

                base: dict = {
                    "strategy": "edge_finder",
                    "liquidity": liq,
                    "question": str(m.get("question") or "")[:200],
                    "confidence": confidence,
                    "size_usdc": DEFAULT_SIGNAL_SIZE_USDC,
                    "edge_bps": edge_bps,
                    "yes_price": yes_p,
                }

                if not await _already_published(DEMO_FEED_ID, mid, side):
                    await _publish(
                        DEMO_FEED_ID, mid, side, target_price, "edge_finder",
                        {**base, "signal_reason": f"{side.lower()}_edge"},
                        True,
                    )
                    demo_published += 1
                else:
                    log.debug("signal_scan_market", market_id=mid, result="DEDUP",
                              reason="already_published", side=side)

            except Exception as exc:
                log.warning("signal_scan_market_error", market_id=mid, error=str(exc))
                _demo_errors += 1

        log.info("signal_scan_cycle_end",
                 edge_approved=demo_scanned,
                 rejected=_demo_rejected,
                 errors=_demo_errors,
                 published=demo_published)
    else:
        log.warning("demo_feed_inactive",
                    message="run migration 024_signal_scan_engine_seed.sql")

    # Live path — Heisenberg agents
    live_scanned, live_published = await _run_heisenberg_signals()

    total_scanned = demo_scanned + live_scanned
    total_published = demo_published + live_published
    log.info("signal_scan_tick_done",
             demo_scanned=demo_scanned, live_scanned=live_scanned,
             published=total_published)
    _scanner_state["scanned"] = total_scanned
    _scanner_state["published"] = total_published
    _scanner_state["last_tick_ts"] = time.time()
    return total_scanned, total_published


__all__ = ["run_job", "get_scanner_state", "JOB_ID", "DEMO_FEED_ID", "LIVE_FEED_ID"]
