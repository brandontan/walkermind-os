"""In-memory real-time trade buffer (replaces the dropped
``heisenberg_realtime_trades`` table).

Per-process, bounded, time-windowed store of recent Heisenberg agent-556 trades.
The 60s sync job (:mod:`jobs.heisenberg_realtime_sync`) records into it; the
Sharp Money signal (:mod:`domain.playbook.sharp_flow`) and the copy-trade
fast-track (:mod:`services.copy_trade.realtime_fast_track`) read from it.

No durable storage — keeps the DB lean per the operator ruling that real-time
signals need no persistence (the table was the top disk hog, dropped in
migration 087). Resets on process restart, which is acceptable: the sync job
refills it within one tick and both readers are fail-soft (empty buffer → the
Sharp Money module simply abstains, the fast-track finds nothing to mirror).

asyncio-only invariant: every public function here is synchronous and does no
``await``, so on the single event loop a call is atomic w.r.t. other coroutines —
no lock (and certainly no threading) is needed.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable

from .heisenberg_trades import RealtimeTrade

logger = logging.getLogger(__name__)

# Hard memory cap — far above a realistic 24h sharp-wallet trade volume, but a
# backstop so a misbehaving upstream can never grow the buffer without bound.
_MAX_ENTRIES: int = 20_000
_DEFAULT_RETENTION_HOURS: int = 24

# Dedup key (wallet_lc, condition_id, trade_time_iso, side_lc) -> latest trade.
# Mirrors the former UPSERT key on heisenberg_realtime_trades.
_Key = tuple[str, str, str, str]
_store: dict[_Key, RealtimeTrade] = {}


def _aware(dt: datetime) -> datetime:
    """Coerce a datetime to aware UTC (naive → assume UTC) so window comparisons
    never raise on a naive/aware mismatch."""
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _key(tr: RealtimeTrade) -> _Key:
    return (
        (tr.wallet or "").lower(),
        tr.condition_id or "",
        tr.trade_time.isoformat() if tr.trade_time else "",
        (tr.side or "").lower(),
    )


def record_trades(
    trades: Iterable[RealtimeTrade], *, retention_hours: int = _DEFAULT_RETENTION_HOURS
) -> int:
    """Upsert ``trades`` into the buffer (dedup by wallet+market+time+side), then
    prune entries older than ``retention_hours`` and enforce the size cap.

    Returns the count of trades ingested (insert or update — matches the former
    UPSERT's "rows touched" semantics). Never raises — observability/strategy
    feed must not break the sync loop.
    """
    count = 0
    try:
        for tr in trades:
            if tr is None or tr.trade_time is None:
                continue
            _store[_key(tr)] = tr
            count += 1
        _prune(retention_hours)
        _enforce_cap()
    except Exception as exc:  # noqa: BLE001 — never break the producer
        logger.warning("heisenberg_buffer.record_trades failed: %s", exc)
    return count


def _prune(retention_hours: int) -> None:
    if retention_hours <= 0:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(hours=retention_hours)
    stale = [k for k, tr in _store.items() if _aware(tr.trade_time) < cutoff]
    for k in stale:
        _store.pop(k, None)


def _enforce_cap() -> None:
    over = len(_store) - _MAX_ENTRIES
    if over <= 0:
        return
    # Evict the oldest entries by trade_time.
    oldest = sorted(_store.items(), key=lambda kv: _aware(kv[1].trade_time))[:over]
    for k, _ in oldest:
        _store.pop(k, None)


def trades_for_markets(
    condition_ids: Iterable[str], since: datetime
) -> list[RealtimeTrade]:
    """Trades for any of ``condition_ids`` with ``trade_time > since``. Unordered.

    Backs :func:`domain.playbook.sharp_flow.fetch_sharp_flows` (the per-market
    sharp-flow aggregation), which applies the leaderboard sharp-wallet filter.
    """
    cids = {c for c in condition_ids if c}
    if not cids:
        return []
    since = _aware(since)
    return [
        tr for tr in _store.values()
        if tr.condition_id in cids and _aware(tr.trade_time) > since
    ]


def trades_for_wallet(wallet: str, since: datetime) -> list[RealtimeTrade]:
    """Trades for one leader ``wallet`` with ``trade_time > since``, oldest first.

    Backs the copy-trade fast-track's per-wallet watermark scan.
    """
    wl = (wallet or "").lower()
    if not wl:
        return []
    since = _aware(since)
    out = [
        tr for tr in _store.values()
        if (tr.wallet or "").lower() == wl and _aware(tr.trade_time) > since
    ]
    out.sort(key=lambda tr: _aware(tr.trade_time))
    return out


def clear() -> None:
    """Drop all buffered trades (test helper / explicit reset)."""
    _store.clear()


def size() -> int:
    """Current buffered trade count."""
    return len(_store)


__all__ = [
    "record_trades",
    "trades_for_markets",
    "trades_for_wallet",
    "clear",
    "size",
]
