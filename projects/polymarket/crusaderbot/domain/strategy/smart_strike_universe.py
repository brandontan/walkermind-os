"""Smart Strike market-universe admin resolution (#1797 / #1801, owner-locked).

Single source of truth for which crypto Up/Down pairs and candle timeframes are
admin-enabled for Smart Strike (candle presets → late_entry_v3):

* pairs: BTC, ETH, SOL — **SOL disabled by default**;
* timeframes: 5m, 15m.

Each flag has a same-named env default in ``config.py`` and a ``runtime_config``
admin overlay (no redeploy). Consumed by BOTH the signal-scan universe gate
(``signal_scan_job._smart_strike_admin_universe``) and the WebTrader autotrade
status payload, so the user-facing picker can never drift from what the scanner
actually trades. These flags gate scanning/selection ONLY — they never bypass
user mode, Auto-Trade, per-user balance/risk, measured-edge policy, the kill
switch, or the live guard flags (those are enforced downstream regardless).
"""
from __future__ import annotations

from ..ops import runtime_config as _runtime_config

MASTER_FLAG = "SMART_STRIKE_ENABLED"
DEFAULT_ASSETS: tuple[str, ...] = ("BTC", "ETH", "SOL")
PAIR_FLAGS: dict[str, str] = {
    "BTC": "SMART_STRIKE_BTC_ENABLED",
    "ETH": "SMART_STRIKE_ETH_ENABLED",
    "SOL": "SMART_STRIKE_SOL_ENABLED",
}
TIMEFRAME_FLAGS: dict[str, str] = {
    "5m": "SMART_STRIKE_5M_ENABLED",
    "15m": "SMART_STRIKE_15M_ENABLED",
}


def _settings():
    """Best-effort Settings; hermetic envs without a full Settings model fall
    back to the owner-lock env defaults (SOL OFF) rather than crashing."""
    try:
        from ...config import get_settings
        return get_settings()
    except Exception:  # noqa: BLE001 — fail to defaults, never crash the scan loop
        return None


def _env_default(flag: str, default: bool) -> bool:
    s = _settings()
    return bool(getattr(s, flag, default)) if s is not None else default


async def master_enabled() -> bool:
    return await _runtime_config.resolve_bool(
        MASTER_FLAG, _env_default(MASTER_FLAG, True),
    )


async def asset_enabled(symbol: str) -> bool:
    """True if the pair is admin-enabled. Unknown (non-major) symbols pass
    through — the deterministic ``{coin}-updown-{tf}-{slot}`` slug universe and
    strategy eligibility still bound what can actually be scanned/traded."""
    flag = PAIR_FLAGS.get(str(symbol).strip().upper())
    if flag is None:
        return True
    return await _runtime_config.resolve_bool(
        flag, _env_default(flag, symbol.strip().upper() != "SOL"),
    )


async def timeframe_enabled(timeframe: str) -> bool:
    flag = TIMEFRAME_FLAGS.get(str(timeframe))
    if flag is None:
        return True  # unknown tf bounded elsewhere
    return await _runtime_config.resolve_bool(flag, _env_default(flag, True))


async def enabled_pairs() -> list[str]:
    """The admin-enabled subset of BTC/ETH/SOL (SOL excluded by default)."""
    return [a for a in DEFAULT_ASSETS if await asset_enabled(a)]


async def enabled_timeframes() -> list[str]:
    return [tf for tf in TIMEFRAME_FLAGS if await timeframe_enabled(tf)]
