"""Heisenberg agent 556 (real-time trades) client.

Thin async wrapper around the Falcon parameterized-retrieval endpoint —
follows the same defensive pattern as services/heisenberg.py and
services/copy_trade/wallet_360.py:

- Returns [] if HEISENBERG_API_TOKEN is unset (caller handles the skip).
- Never raises; on HTTP error logs a warning and returns [].
- Field-name aliasing tolerates several plausible upstream conventions
  (`wallet` / `proxy_wallet` / `address`, `side` / `direction`, etc.) so a
  rename upstream does NOT silently produce empty rows — bad shapes surface
  as a `bad_trade` warning instead.
"""
from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

log = logging.getLogger(__name__)

_FALCON_URL = "https://narrative.agent.heisenberg.so/api/v2/semantic/retrieve/parameterized"
_AGENT_ID = 556
_TIMEOUT = httpx.Timeout(15.0)


@dataclass(frozen=True)
class RealtimeTrade:
    """One row produced by agent 556 — already normalised + validated."""
    wallet: str
    condition_id: str
    side: str               # 'YES' / 'NO' (upstream-conformant; not normalised)
    price: float | None     # nullable: agent may omit on certain order types
    size_usdc: float | None
    trade_time: datetime    # UTC, parsed from upstream timestamp
    raw: dict[str, Any]     # full raw payload — kept for forensic debugging


def _safe_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _first_not_none(*vals: Any) -> Any:
    """First arg that is not None. Used so legitimate falsy values (0, 0.0, '')
    survive field-alias fallback — `or` chains would drop them."""
    for v in vals:
        if v is not None:
            return v
    return None


def _coerce_dt(val: Any) -> datetime | None:
    """Parse a Heisenberg timestamp (ISO-8601, epoch int, or epoch str)."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    if isinstance(val, (int, float)):
        try:
            return datetime.fromtimestamp(float(val), tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    s = str(val).strip()
    if not s:
        return None
    # Try epoch first (Heisenberg sometimes uses unix seconds as a string).
    try:
        return datetime.fromtimestamp(float(s), tz=timezone.utc)
    except (ValueError, OSError, OverflowError):
        pass
    # Fall back to ISO-8601 (with the common Z-suffix tolerance).
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _normalise(r: dict[str, Any]) -> RealtimeTrade | None:
    """Map one raw upstream row into RealtimeTrade. Returns None if invalid."""
    wallet = r.get("wallet") or r.get("proxy_wallet") or r.get("address") or r.get("trader")
    condition_id = (
        r.get("condition_id")
        or r.get("conditionId")
        or r.get("market_id")
        or r.get("marketId")
    )
    side = r.get("side") or r.get("direction") or r.get("outcome")
    if not (wallet and condition_id and side):
        return None
    trade_time = _coerce_dt(_first_not_none(
        r.get("trade_time"), r.get("timestamp"), r.get("ts"), r.get("created_at"),
    ))
    if trade_time is None:
        return None
    return RealtimeTrade(
        wallet=str(wallet)[:42],
        condition_id=str(condition_id)[:80],
        side=str(side)[:8].upper(),
        # `_first_not_none` instead of `or` so a legitimate 0 / 0.0 price or
        # size survives — in prediction markets price=0 is a real value
        # (fully-resolved-NO outcome).
        price=_safe_float(_first_not_none(r.get("price"), r.get("fill_price"))),
        size_usdc=_safe_float(_first_not_none(
            r.get("size_usdc"), r.get("size"), r.get("notional_usdc"),
        )),
        trade_time=trade_time,
        raw=r,
    )


async def fetch_recent(
    *,
    window_seconds: int = 300,
    limit: int = 100,
) -> list[RealtimeTrade]:
    """Pull recent trades from agent 556. Returns [] on token-unset or any error.

    Params shape follows the existing 584/581 pattern — string-coerced ints.
    """
    token = os.getenv("HEISENBERG_API_TOKEN", "")
    if not token:
        return []

    body: dict[str, Any] = {
        "agent_id": _AGENT_ID,
        "params": {"lookback_seconds": str(window_seconds)},
        "pagination": {"limit": limit, "offset": 0},
        "formatter_config": {"format_type": "raw"},
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                _FALCON_URL,
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code != 200:
                log.warning(
                    "heisenberg_trades: agent %d HTTP %d body=%s",
                    _AGENT_ID, resp.status_code, resp.text[:200],
                )
                return []
            data = resp.json()
            if not isinstance(data, dict):
                log.warning(
                    "heisenberg_trades: expected dict response, got %s",
                    type(data).__name__,
                )
                return []
    except Exception as exc:
        # Broad catch upholds the "never raises" contract — covers
        # httpx.HTTPError / TimeoutException / json.JSONDecodeError /
        # any unexpected upstream malformation.
        log.warning("heisenberg_trades: request failed: %s", exc)
        return []

    results: list[dict] = data.get("data", {}).get("results", []) or []
    if not results:
        return []

    out: list[RealtimeTrade] = []
    bad = 0
    for r in results:
        norm = _normalise(r) if isinstance(r, dict) else None
        if norm is None:
            bad += 1
            continue
        out.append(norm)

    if bad:
        log.warning(
            "heisenberg_trades: %d/%d rows dropped — likely upstream field-name drift; "
            "sample keys=%s",
            bad, len(results), sorted(results[0].keys()) if isinstance(results[0], dict) else "non-dict",
        )

    return out


__all__ = ["RealtimeTrade", "fetch_recent"]
