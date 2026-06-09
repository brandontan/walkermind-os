"""File-based JSON persistence for WeatherStrategy market state."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_DATA_DIR: Path = Path(__file__).parent.parent.parent / "data" / "weather" / "markets"


def get_data_dir() -> Path:
    return _DATA_DIR


def _market_path(market_id: str) -> Path:
    safe = market_id.replace("/", "_").replace("\\", "_")[:120]
    return _DATA_DIR / f"{safe}.json"


def load_market_state(market_id: str) -> dict[str, Any]:
    path = _market_path(market_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("load_market_state failed", extra={"market_id": market_id, "err": str(exc)})
        return {}


def save_market_state(market_id: str, state: dict[str, Any]) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = _market_path(market_id)
    try:
        path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    except Exception as exc:
        log.error("save_market_state failed", extra={"market_id": market_id, "err": str(exc)})


def list_market_files() -> list[str]:
    if not _DATA_DIR.exists():
        return []
    return [p.stem for p in sorted(_DATA_DIR.glob("*.json"))]


async def load_market_state_async(market_id: str) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, load_market_state, market_id)


async def save_market_state_async(market_id: str, state: dict[str, Any]) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, save_market_state, market_id, state)
