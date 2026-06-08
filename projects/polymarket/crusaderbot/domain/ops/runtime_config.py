"""Runtime-editable operator config — a DB overlay over static (Fly/env) settings.

Frequently-tuned knobs (strategy on/off switches, and later tuning thresholds)
live in ``system_settings`` under the ``cfg:`` namespace so an operator can change
them from the web admin **without a redeploy**. Rarely-changed globals, all
secrets, and the LIVE-trading safety guards stay in Fly secrets (static
``config.Settings`` / env) and are intentionally NOT overridable here.

Precedence: **code default → env/Fly (config.Settings) → DB override** (the DB
wins, but ONLY for whitelisted keys). Reads are cached in-process for
``CACHE_TTL_SECONDS`` (mirrors ``domain.ops.kill_switch``) so hot paths never slam
the DB.

Safety invariants:
  * Only keys in ``RUNTIME_SETTINGS`` are accepted on write and consulted on read.
    An unknown key is rejected on write and ignored on read, so the overlay can
    never shadow a secret or a LIVE guard.
  * Reads fail SAFE: any DB error or unparseable value falls back to the static
    env/Fly default (for strategy flags that default is OFF).
  * Writes are validated (type + bounds) and the in-process cache is invalidated
    immediately so the writing process reflects the change at once; other
    processes pick it up within the TTL window.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass
from typing import Any

from ...database import get_pool

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS: float = 30.0
_KEY_PREFIX = "cfg:"

_TRUE = {"true", "1", "yes", "on"}
_FALSE = {"false", "0", "no", "off"}


@dataclass(frozen=True)
class SettingSpec:
    """Whitelist entry: how a runtime key is typed, bounded, and described."""

    key: str
    kind: str            # "bool" | "float"
    label: str
    description: str
    min_value: float | None = None
    max_value: float | None = None


# The whitelist. Lane 1 ships the two single-read-site strategy master switches
# (each gates a whole scan branch in signal_scan_job.run_once). Additional flags
# and tuning thresholds are added here as their read-sites are converted in
# follow-up lanes — a key only appears once its read path actually consults the
# overlay, so the admin UI never shows a toggle that does nothing.
RUNTIME_SETTINGS: dict[str, SettingSpec] = {
    "WEATHER_STRATEGY_ENABLED": SettingSpec(
        key="WEATHER_STRATEGY_ENABLED",
        kind="bool",
        label="Weather strategy",
        description="Enable the weather strategy scan + booking (Phase B2).",
    ),
    "COMPLETE_SET_ARB_ENABLED": SettingSpec(
        key="COMPLETE_SET_ARB_ENABLED",
        kind="bool",
        label="Complete-set arbitrage",
        description="Enable the complete-set arbitrage scan + PAPER booking (Phase B3).",
    ),
    "PLAYBOOK_STRATEGY_ENABLED": SettingSpec(
        key="PLAYBOOK_STRATEGY_ENABLED",
        kind="bool",
        label="Playbook sports router",
        description="Enable the PLAYBOOK sports scan dispatch (Phase B4, PAPER).",
    ),
    "SCAN_SNAPSHOT_ENABLED": SettingSpec(
        key="SCAN_SNAPSHOT_ENABLED",
        kind="bool",
        label="Scan snapshot capture",
        description="Persist the raw full-universe market state to market_snapshots "
                    "each scan tick (walk-forward replay substrate, Phase-2c-2). "
                    "Append-only telemetry, fail-soft, no effect on trading.",
    ),
    "ORCHESTRATOR_KILL_SWITCH": SettingSpec(
        key="ORCHESTRATOR_KILL_SWITCH",
        kind="bool",
        label="Orchestrator kill-switch",
        description="WARP-78 cutover emergency fallback. When ON, the candle_auto "
                    "+ rule 'auto' EV-comparator orchestrator is DISABLED and those "
                    "users fall back to the precedence router — instant, no-redeploy. "
                    "Default OFF (orchestrator allowed). Flip ON to halt the "
                    "orchestrator if it misbehaves post-cutover.",
    ),
    "MIN_COMPLETE_SET_EDGE": SettingSpec(
        key="MIN_COMPLETE_SET_EDGE",
        kind="float",
        label="Complete-set min edge ($/pair)",
        description="Base minimum locked net profit per complete-set pair, in USDC "
                    "(e.g. 0.02 = 2c). 0 keeps the arb DORMANT (scans + logs quotes "
                    "but books nothing). Any positive value is clamped UP to the 2% "
                    "hard floor (fee/slippage-covered) — it can only TIGHTEN above "
                    "2%, never relax below it. With adaptive margin ON this is the "
                    "base floor a per-market slippage premium is added on top of.",
        min_value=0.0,
        max_value=0.5,
    ),
    "COMPLETE_SET_ADAPTIVE_MARGIN_ENABLED": SettingSpec(
        key="COMPLETE_SET_ADAPTIVE_MARGIN_ENABLED",
        kind="bool",
        label="Complete-set adaptive margin",
        description="When ON, the complete-set arb requires EXTRA edge on thin/steep "
                    "books: a per-market premium = the execution slippage of filling "
                    "the intended size above top-of-book (both legs), added on top of "
                    "the MIN_COMPLETE_SET_EDGE base floor (capped, never below floor). "
                    "Default OFF = static base only. Feature vector is logged each "
                    "evaluation regardless, for future calibration.",
    ),
}


def _parse_bool(raw: str) -> bool | None:
    v = raw.strip().lower()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    return None


def _parse_float(raw: str) -> float | None:
    try:
        f = float(raw)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


class _Cache:
    """30s TTL snapshot of the {bare_key: raw_value} override map."""

    def __init__(self) -> None:
        self._overrides: dict[str, str] | None = None
        self._expires: float = 0.0
        self._lock = asyncio.Lock()

    def read(self) -> dict[str, str] | None:
        if self._overrides is None or time.monotonic() >= self._expires:
            return None
        return self._overrides

    def store(self, overrides: dict[str, str]) -> None:
        self._overrides = overrides
        self._expires = time.monotonic() + CACHE_TTL_SECONDS

    def invalidate(self) -> None:
        self._overrides = None
        self._expires = 0.0

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock


_cache = _Cache()


def invalidate_cache() -> None:
    """Force the next read to re-query ``system_settings`` (tests / direct tweaks)."""
    _cache.invalidate()


async def _load_overrides() -> dict[str, str]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT key, value FROM system_settings WHERE key LIKE $1",
            _KEY_PREFIX + "%",
        )
    out: dict[str, str] = {}
    for r in rows:
        bare = str(r["key"])[len(_KEY_PREFIX):]
        # Only surface whitelisted, non-NULL keys — a stale row for a key that
        # was removed from the whitelist is ignored, never honoured.
        if bare in RUNTIME_SETTINGS and r["value"] is not None:
            out[bare] = str(r["value"])
    return out


async def _get_overrides() -> dict[str, str]:
    cached = _cache.read()
    if cached is not None:
        return cached
    async with _cache.lock:
        cached = _cache.read()
        if cached is not None:
            return cached
        try:
            overrides = await _load_overrides()
        except Exception as exc:  # noqa: BLE001 — fail safe to static defaults
            logger.error("runtime_config load failed: %s", exc)
            return {}  # not cached: retry next call; caller uses env defaults
        _cache.store(overrides)
        return overrides


async def resolve_bool(key: str, env_default: bool) -> bool:
    """DB override for ``key`` if present + valid, else ``env_default``."""
    spec = RUNTIME_SETTINGS.get(key)
    if spec is None or spec.kind != "bool":
        return env_default
    raw = (await _get_overrides()).get(key)
    if raw is None:
        return env_default
    parsed = _parse_bool(raw)
    return env_default if parsed is None else parsed


async def resolve_float(key: str, env_default: float) -> float:
    """DB override for ``key`` if present + valid + in-bounds, else ``env_default``."""
    spec = RUNTIME_SETTINGS.get(key)
    if spec is None or spec.kind != "float":
        return env_default
    raw = (await _get_overrides()).get(key)
    if raw is None:
        return env_default
    parsed = _parse_float(raw)
    if parsed is None:
        return env_default
    if spec.min_value is not None and parsed < spec.min_value:
        return env_default
    if spec.max_value is not None and parsed > spec.max_value:
        return env_default
    return parsed


def _canonicalize(spec: SettingSpec, value: Any) -> str:
    """Validate ``value`` against ``spec`` and return the TEXT to persist."""
    if spec.kind == "bool":
        parsed = value if isinstance(value, bool) else _parse_bool(str(value))
        if parsed is None:
            raise ValueError(f"{spec.key} expects a boolean")
        return "true" if parsed else "false"
    if spec.kind == "float":
        parsed = float(value) if isinstance(value, (int, float)) else _parse_float(str(value))
        if parsed is None or not math.isfinite(parsed):
            raise ValueError(f"{spec.key} expects a finite number")
        if spec.min_value is not None and parsed < spec.min_value:
            raise ValueError(f"{spec.key} must be >= {spec.min_value}")
        if spec.max_value is not None and parsed > spec.max_value:
            raise ValueError(f"{spec.key} must be <= {spec.max_value}")
        return repr(parsed)
    raise ValueError(f"unknown setting kind {spec.kind!r}")


async def set_override(key: str, value: Any) -> str:
    """Validate + persist an override for ``key``. Returns the stored TEXT.

    Raises ``KeyError`` for a non-whitelisted key, ``ValueError`` for an invalid
    value. Invalidates the cache so the change is visible immediately here.
    """
    spec = RUNTIME_SETTINGS.get(key)
    if spec is None:
        raise KeyError(f"{key} is not a runtime-editable setting")
    canonical = _canonicalize(spec, value)
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO system_settings (key, value, updated_at) VALUES ($1, $2, NOW()) "
            "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()",
            _KEY_PREFIX + key, canonical,
        )
    invalidate_cache()
    return canonical


async def clear_override(key: str) -> None:
    """Delete the override for ``key`` so it reverts to the env/Fly default."""
    spec = RUNTIME_SETTINGS.get(key)
    if spec is None:
        raise KeyError(f"{key} is not a runtime-editable setting")
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM system_settings WHERE key=$1", _KEY_PREFIX + key,
        )
    invalidate_cache()


async def list_effective(settings: Any) -> list[dict[str, Any]]:
    """Snapshot for the admin UI: spec + env default + override + effective value."""
    overrides = await _get_overrides()
    out: list[dict[str, Any]] = []
    for key, spec in RUNTIME_SETTINGS.items():
        env_default = getattr(settings, key, None)
        raw = overrides.get(key)
        if spec.kind == "bool":
            effective: Any = await resolve_bool(key, bool(env_default))
        else:
            effective = await resolve_float(key, float(env_default or 0.0))
        out.append(
            {
                "key": key,
                "kind": spec.kind,
                "label": spec.label,
                "description": spec.description,
                "min_value": spec.min_value,
                "max_value": spec.max_value,
                "env_default": env_default,
                "overridden": raw is not None,
                "effective": effective,
            }
        )
    return out
