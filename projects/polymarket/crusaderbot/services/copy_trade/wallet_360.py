"""Wallet 360 enrichment — fetches deep wallet analytics from Falcon API.

Public surface:
    get_wallet_360(address, window_days="7")  — returns Wallet360 dataclass

In-memory cache with 10-minute TTL. Returns available=False on any failure.
Never raises — callers receive a partial result with available=False instead.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import aiohttp

log = logging.getLogger(__name__)

_FALCON_URL = "https://narrative.agent.heisenberg.so/api/v2/semantic/retrieve/parameterized"
_TIMEOUT = aiohttp.ClientTimeout(total=15)
_CACHE_TTL = 600  # 10 minutes

# {cache_key: (monotonic_ts, Wallet360)}
_cache: dict[str, tuple[float, "Wallet360"]] = {}


@dataclass(frozen=True)
class Wallet360:
    address: str
    win_rate: float | None
    roi: float | None
    total_pnl: float | None
    sharpe_ratio: float | None
    max_drawdown: float | None
    markets_traded: int | None
    total_trades: int | None
    performance_trend: str | None
    risk_level: str | None
    sybil_risk_flag: bool
    sybil_risk_score: float | None
    combined_risk_score: float | None
    flagged_metrics: list[str] | None
    last_active: str | None
    available: bool


def _unavailable(address: str) -> Wallet360:
    return Wallet360(
        address=address,
        win_rate=None,
        roi=None,
        total_pnl=None,
        sharpe_ratio=None,
        max_drawdown=None,
        markets_traded=None,
        total_trades=None,
        performance_trend=None,
        risk_level=None,
        sybil_risk_flag=False,
        sybil_risk_score=None,
        combined_risk_score=None,
        flagged_metrics=None,
        last_active=None,
        available=False,
    )


def _safe_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _safe_int(val: Any) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _safe_bool(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    return bool(val) if val is not None else False


async def get_wallet_360(address: str, window_days: str = "7") -> Wallet360:
    cache_key = f"{address.lower()}:{window_days}"
    now = time.monotonic()
    cached = _cache.get(cache_key)
    if cached and (now - cached[0]) < _CACHE_TTL:
        return cached[1]

    result = await _fetch(address, window_days)
    _cache[cache_key] = (time.monotonic(), result)
    return result


async def _fetch(address: str, window_days: str) -> Wallet360:
    api_key = os.environ.get("HEISENBERG_API_TOKEN", "")
    if not api_key:
        log.warning("wallet_360: HEISENBERG_API_TOKEN not set")
        return _unavailable(address)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "agent_id": 581,
        "params": {
            "proxy_wallet": address,
            "window_days": window_days,
        },
        "pagination": {"limit": 1, "offset": 0},
        "formatter_config": {"format_type": "raw"},
    }

    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.post(_FALCON_URL, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    log.warning(
                        "wallet_360: Falcon API status=%d addr=%s", resp.status, address
                    )
                    return _unavailable(address)
                data = await resp.json()
    except (aiohttp.ClientError, TimeoutError) as exc:
        log.warning("wallet_360: Falcon API request failed addr=%s: %s", address, exc)
        return _unavailable(address)
    except Exception:
        log.exception("wallet_360: unexpected error addr=%s", address)
        return _unavailable(address)

    results: list[dict] = data.get("data", {}).get("results", [])
    if not results:
        log.warning("wallet_360: empty results addr=%s", address)
        return _unavailable(address)

    r = results[0]
    flagged_raw = r.get("flagged_metrics")
    flagged: list[str] | None = None
    if isinstance(flagged_raw, list):
        flagged = [str(f) for f in flagged_raw]
    elif isinstance(flagged_raw, str) and flagged_raw:
        flagged = [flagged_raw]

    return Wallet360(
        address=address,
        win_rate=_safe_float(r.get("win_rate")),
        roi=_safe_float(r.get("roi")),
        total_pnl=_safe_float(r.get("total_pnl")),
        sharpe_ratio=_safe_float(r.get("sharpe_ratio")),
        max_drawdown=_safe_float(r.get("max_drawdown")),
        markets_traded=_safe_int(r.get("markets_traded")),
        total_trades=_safe_int(r.get("total_trades")),
        performance_trend=r.get("performance_trend"),
        risk_level=r.get("risk_level"),
        sybil_risk_flag=_safe_bool(r.get("sybil_risk_flag")),
        sybil_risk_score=_safe_float(r.get("sybil_risk_score")),
        combined_risk_score=_safe_float(r.get("combined_risk_score")),
        flagged_metrics=flagged,
        last_active=r.get("last_active"),
        available=True,
    )
