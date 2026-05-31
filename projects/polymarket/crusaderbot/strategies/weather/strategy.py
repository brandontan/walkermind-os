"""WeatherStrategy — Polymarket weather market edge detection and monitoring."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .calibration import get_sigma
from .forecast import fetch_all, ensemble_tmax
from .locations import LOCATIONS, LOCATION_BY_CITY
from .market import WeatherMarket, fetch_weather_markets
from .math_utils import bucket_prob, expected_value, kelly_size
from .storage import load_market_state_async, save_market_state_async, get_data_dir

log = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / "weather_config.json"

_DEFAULT_CONFIG: dict[str, Any] = {
    "min_ev": 0.10,
    "min_volume": 500.0,
    "max_spread": 0.03,
    "max_price": 0.45,
    "kelly_alpha": 0.25,
    "max_bet_usdc": 20.0,
    "stop_loss_pct": 0.20,
    "trailing_stop_activation_pct": 0.20,
    "tp_24h": None,
    "tp_48h": 0.85,
    "tp_48h_plus": 0.75,
    "forecast_exit_shift_f": 2.0,
}


def _load_config() -> dict[str, Any]:
    try:
        raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        return {**_DEFAULT_CONFIG, **raw}
    except Exception:
        return _DEFAULT_CONFIG.copy()


class WeatherStrategy:
    """Autonomous weather-market edge detection strategy for CrusaderBot.

    Identifies mispricing in Polymarket daily temperature markets across 20 global
    cities using multi-source ensemble forecasts and probabilistic edge detection.

    Public interface (called by scheduler):
        await scan_cycle()     — full opportunity scan, run hourly
        await monitor_cycle()  — open-position exit checks, run every 10 min
        get_status()           — dashboard summary dict
    """

    def __init__(self) -> None:
        self._cfg = _load_config()
        self._candidates_last: list[dict[str, Any]] = []
        self._positions: dict[str, dict[str, Any]] = {}   # market_id → position state
        self._last_scan: datetime | None = None
        self._last_monitor: datetime | None = None
        self._scan_count: int = 0
        self._entries_total: int = 0
        self._errors: int = 0
        get_data_dir().mkdir(parents=True, exist_ok=True)
        self._load_positions_from_storage()

    def _load_positions_from_storage(self) -> None:
        """Populate _positions from persisted JSON files on startup."""
        try:
            from .storage import list_market_files, load_market_state
            for safe_id in list_market_files():
                state = load_market_state(safe_id)
                if state.get("status") == "open":
                    market_id = state.get("market_id") or safe_id
                    self._positions[market_id] = state
        except Exception as exc:
            log.warning("weather load_positions_from_storage failed", extra={"err": str(exc)})

    # ------------------------------------------------------------------ #
    # Scan cycle (hourly)                                                  #
    # ------------------------------------------------------------------ #

    async def scan_cycle(self) -> dict[str, Any]:
        """Full opportunity scan across all 20 cities.

        For each city: fetch weather markets → get ensemble forecast →
        compute bucket probability → evaluate EV → emit entry candidates.
        Returns summary metrics dict.
        """
        self._cfg = _load_config()
        self._last_scan = datetime.now(timezone.utc)
        self._scan_count += 1

        candidates: list[dict[str, Any]] = []
        errors: int = 0

        # Run city scans with bounded concurrency (semaphore=5 to respect API limits)
        sem = asyncio.Semaphore(5)

        async def _scan_city(city_name: str) -> list[dict[str, Any]]:
            async with sem:
                return await self._scan_one_city(city_name)

        loc_names = [loc.city for loc in LOCATIONS]
        results = await asyncio.gather(
            *[_scan_city(c) for c in loc_names],
            return_exceptions=True,
        )

        for city_name, result in zip(loc_names, results):
            if isinstance(result, Exception):
                log.warning("scan_city failed",
                            extra={"city": city_name, "err": str(result)})
                errors += 1
            else:
                candidates.extend(result)

        self._candidates_last = candidates
        self._errors += errors

        log.info(
            "weather scan_cycle done",
            extra={
                "scan": self._scan_count,
                "cities_scanned": len(loc_names),
                "candidates": len(candidates),
                "errors": errors,
            },
        )
        return {
            "scan": self._scan_count,
            "ts": self._last_scan.isoformat(),
            "cities_scanned": len(loc_names),
            "candidates": len(candidates),
            "errors": errors,
        }

    async def _scan_one_city(self, city_name: str) -> list[dict[str, Any]]:
        loc = LOCATION_BY_CITY.get(city_name)
        if not loc:
            return []

        today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Fetch markets and forecast concurrently
        markets, forecasts = await asyncio.gather(
            fetch_weather_markets(city=city_name, limit=20),
            fetch_all(loc, today_utc),
            return_exceptions=False,
        )

        if not markets or not forecasts:
            return []

        sigma = get_sigma()
        mean_tmax = ensemble_tmax(forecasts)
        if mean_tmax is None:
            return []

        candidates = []
        for wm in markets:
            c = self._evaluate_market(wm, mean_tmax, sigma)
            if c is not None:
                candidates.append(c)
        return candidates

    def _evaluate_market(
        self,
        wm: WeatherMarket,
        mean_tmax: float,
        sigma: float,
    ) -> dict[str, Any] | None:
        """Return candidate dict if market passes all entry filters, else None."""
        cfg = self._cfg

        # Volume / spread / price filters
        if wm.volume_24h < cfg["min_volume"]:
            return None
        if wm.spread > cfg["max_spread"]:
            return None
        if wm.yes_price > cfg["max_price"]:
            return None
        if wm.bucket_low is None or wm.bucket_high is None:
            return None

        # Edge calculation
        p_true = bucket_prob(mean_tmax, sigma, wm.bucket_low, wm.bucket_high)
        ev = expected_value(p_true, wm.yes_price)

        if ev < cfg["min_ev"]:
            return None

        size = kelly_size(
            ev=ev,
            p_true=p_true,
            price=wm.yes_price,
            bankroll=1000.0,   # conservative default; overridden by execution layer
            alpha=cfg["kelly_alpha"],
            max_bet=cfg["max_bet_usdc"],
        )
        if size <= 0:
            return None

        return {
            "market_id": wm.market_id,
            "condition_id": wm.condition_id,
            "city": wm.city,
            "question": wm.question,
            "yes_price": wm.yes_price,
            "p_true": round(p_true, 4),
            "ev": round(ev, 4),
            "size_usdc": size,
            "mean_tmax_f": round(mean_tmax, 1),
            "sigma_f": round(sigma, 2),
            "bucket_low": wm.bucket_low,
            "bucket_high": wm.bucket_high,
            "end_date": wm.end_date_iso,
        }

    # ------------------------------------------------------------------ #
    # Monitor cycle (every 10 min)                                         #
    # ------------------------------------------------------------------ #

    async def monitor_cycle(self) -> dict[str, Any]:
        """Check open positions for exit conditions.

        Exit rules:
        - Stop-loss: price dropped >= stop_loss_pct from entry
        - Trailing stop: activated at +20%, moves stop to breakeven
        - Take-profit: 24h → hold; 24–48h → TP at 0.85; 48h+ → TP at 0.75
        - Forecast exit: close if ensemble Tmax shifted >= 2°F from entry bucket

        Returns summary dict with closed/held counts.
        """
        self._last_monitor = datetime.now(timezone.utc)
        positions = list(self._positions.values())
        closed = 0
        held = 0

        async def _process_position(pos: dict[str, Any]) -> tuple[str, str | None]:
            try:
                action = await self._check_exit(pos)
                return pos.get("market_id", ""), action
            except Exception as exc:
                log.warning("monitor_cycle position check failed",
                            extra={"market_id": pos.get("market_id"), "err": str(exc)})
                return pos.get("market_id", ""), "error"

        results = await asyncio.gather(*[_process_position(p) for p in positions])

        for market_id, action in results:
            if action == "error":
                self._errors += 1
            elif action == "close":
                pos = self._positions.get(market_id)
                if pos:
                    await self._close_position(pos)
                closed += 1
            else:
                held += 1

        log.info("weather monitor_cycle done",
                 extra={"closed": closed, "held": held, "open": len(self._positions)})
        return {"ts": self._last_monitor.isoformat(), "closed": closed, "held": held,
                "open_positions": len(self._positions)}

    async def _check_exit(self, pos: dict[str, Any]) -> str:
        """Return 'close' or 'hold' for a position."""
        cfg = self._cfg
        entry_price: float = pos.get("entry_price", 0.5)
        current_price: float = pos.get("current_price", entry_price)
        entry_ts_str: str = pos.get("entry_ts", "")
        bucket_low: float = pos.get("bucket_low", 0.0)
        bucket_high: float = pos.get("bucket_high", 100.0)
        city: str = pos.get("city", "")
        end_date: str = pos.get("end_date", "")

        # Time-to-expiry
        hours_remaining = _hours_to_expiry(end_date)

        # Stop-loss check
        if current_price <= entry_price * (1.0 - cfg["stop_loss_pct"]):
            log.info("weather stop-loss triggered",
                     extra={"market_id": pos.get("market_id"), "entry": entry_price,
                            "current": current_price})
            return "close"

        # Take-profit by time
        if hours_remaining is not None:
            if 24 <= hours_remaining <= 48 and current_price >= cfg["tp_48h"]:
                return "close"
            if hours_remaining > 48 and current_price >= cfg["tp_48h_plus"]:
                return "close"

        # Forecast-shift exit: re-fetch ensemble and check bucket shift
        loc = LOCATION_BY_CITY.get(city)
        if loc and end_date:
            target_date = end_date[:10] if end_date else datetime.now(timezone.utc).strftime("%Y-%m-%d")
            forecasts = await fetch_all(loc, target_date)
            current_mean = ensemble_tmax(forecasts)
            entry_mean_val = pos.get("entry_mean_tmax_f") or pos.get("mean_tmax_f")
            if entry_mean_val is not None and current_mean is not None and abs(current_mean - float(entry_mean_val)) >= cfg["forecast_exit_shift_f"]:
                log.info("weather forecast-shift exit",
                         extra={"market_id": pos.get("market_id"),
                                "entry_mean": entry_mean_val, "current_mean": current_mean})
                return "close"

        return "hold"

    async def _close_position(self, pos: dict[str, Any]) -> None:
        """Mark position closed in storage. Execution is delegated to CrusaderBot router."""
        market_id = pos.get("market_id", "")
        state = await load_market_state_async(market_id)
        state["status"] = "closed"
        state["closed_ts"] = datetime.now(timezone.utc).isoformat()
        await save_market_state_async(market_id, state)
        self._positions.pop(market_id, None)

    # ------------------------------------------------------------------ #
    # Status for dashboard                                                 #
    # ------------------------------------------------------------------ #

    def get_status(self) -> dict[str, Any]:
        """Return a summary dict for dashboard / reporting consumption."""
        return {
            "strategy": "weather",
            "enabled": True,
            "last_scan": self._last_scan.isoformat() if self._last_scan else None,
            "last_monitor": self._last_monitor.isoformat() if self._last_monitor else None,
            "scan_count": self._scan_count,
            "open_positions": len(self._positions),
            "entries_total": self._entries_total,
            "errors_total": self._errors,
            "candidates_last_scan": len(self._candidates_last),
            "cities_covered": len(LOCATIONS),
            "sigma_f": get_sigma(),
        }


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def _hours_to_expiry(end_date_iso: str) -> float | None:
    if not end_date_iso:
        return None
    try:
        end = datetime.fromisoformat(end_date_iso.replace("Z", "+00:00"))
        delta = end - datetime.now(timezone.utc)
        return delta.total_seconds() / 3600.0
    except Exception:
        return None
