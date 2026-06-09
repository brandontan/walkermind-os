"""Admin-controlled strategy global on/off flags.

Flags are stored in ``system_settings`` using two key namespaces:

  strategy_enabled:{name}   — global on/off for a named strategy
                              (affects all users; OFF stops new signals)
  bot_override:{name}       — runtime override for a specific bot subsystem
                              (takes effect on next scan tick, no redeploy)

Supported strategy names (STRATEGIES):
  late_entry_v3, signal_following, copy_trade, weather, playbook

Supported bot override names (BOT_OVERRIDES):
  weather_strategy, complete_set_arb, playbook_sports, scan_snapshot_capture

Values are stored as JSON booleans: ``true`` / ``false``.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

STRATEGIES: list[str] = [
    "late_entry_v3",
    "signal_following",
    "copy_trade",
    "weather",
    "playbook",
]

BOT_OVERRIDES: list[str] = [
    "weather_strategy",
    "complete_set_arb",
    "playbook_sports",
    "scan_snapshot_capture",
]

_STRATEGY_KEY_PREFIX = "strategy_enabled:"
_OVERRIDE_KEY_PREFIX = "bot_override:"


def _strategy_key(name: str) -> str:
    return f"{_STRATEGY_KEY_PREFIX}{name}"


def _override_key(name: str) -> str:
    return f"{_OVERRIDE_KEY_PREFIX}{name}"


async def get_all_flags() -> dict[str, Any]:
    """Return a dict with all strategy and bot-override flags.

    Shape::

        {
            "strategies": {"late_entry_v3": True, "signal_following": False, ...},
            "bot_overrides": {"weather_strategy": False, "complete_set_arb": True, ...},
        }

    Missing keys default to ``True`` (enabled) so that a fresh deployment
    with no rows in ``system_settings`` behaves as fully enabled.
    """
    strategies: dict[str, bool] = {s: True for s in STRATEGIES}
    overrides: dict[str, bool] = {o: False for o in BOT_OVERRIDES}
    try:
        from ...database import get_pool  # type: ignore
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT key, value FROM system_settings WHERE key LIKE $1 OR key LIKE $2",
                f"{_STRATEGY_KEY_PREFIX}%",
                f"{_OVERRIDE_KEY_PREFIX}%",
            )
            import json as _json
            for row in rows:
                key: str = row["key"]
                try:
                    val = _json.loads(row["value"])
                except Exception:
                    val = str(row["value"]).lower() in {"true", "1", "yes"}
                if key.startswith(_STRATEGY_KEY_PREFIX):
                    name = key[len(_STRATEGY_KEY_PREFIX):]
                    if name in strategies:
                        strategies[name] = bool(val)
                elif key.startswith(_OVERRIDE_KEY_PREFIX):
                    name = key[len(_OVERRIDE_KEY_PREFIX):]
                    if name in overrides:
                        overrides[name] = bool(val)
    except Exception as exc:  # noqa: BLE001
        log.debug("strategy_flags get_all_flags failed: %s", exc)
    return {"strategies": strategies, "bot_overrides": overrides}


async def set_strategy_flag(name: str, enabled: bool) -> None:
    """Persist a strategy global on/off flag to system_settings."""
    if name not in STRATEGIES:
        raise ValueError(f"Unknown strategy: {name!r}")
    await _upsert(_strategy_key(name), enabled)


async def set_override_flag(name: str, enabled: bool) -> None:
    """Persist a bot runtime override flag to system_settings."""
    if name not in BOT_OVERRIDES:
        raise ValueError(f"Unknown bot override: {name!r}")
    await _upsert(_override_key(name), enabled)


async def is_strategy_enabled(name: str) -> bool:
    """Return True if the named strategy is globally enabled (default: True)."""
    try:
        from ...database import get_pool  # type: ignore
        pool = get_pool()
        async with pool.acquire() as conn:
            val = await conn.fetchval(
                "SELECT value FROM system_settings WHERE key=$1",
                _strategy_key(name),
            )
            if val is None:
                return True
            import json as _json
            return bool(_json.loads(val))
    except Exception as exc:  # noqa: BLE001
        log.debug("is_strategy_enabled failed for %s: %s", name, exc)
        return True


async def _upsert(key: str, value: bool) -> None:
    import json as _json
    val_str = _json.dumps(value)
    try:
        from ...database import get_pool  # type: ignore
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO system_settings (key, value, updated_at)
                VALUES ($1, $2, NOW())
                ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value,
                        updated_at = NOW()
                """,
                key, val_str,
            )
    except Exception as exc:  # noqa: BLE001
        log.error("strategy_flags _upsert failed key=%s: %s", key, exc)
        raise
