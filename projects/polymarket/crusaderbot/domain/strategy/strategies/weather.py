"""WeatherDomainStrategy — BaseStrategy adapter wrapping strategies/weather/.

Bridges the autonomous WeatherStrategy (forecast + calibration + market fetch)
to the CrusaderBot domain strategy plane (SignalCandidate / ExitDecision /
UserContext). Called by signal_scan_job.run_once() for users on the
`weather_monitor` preset.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from ..base import BaseStrategy
from ..types import ExitDecision, MarketFilters, SignalCandidate, UserContext

log = logging.getLogger(__name__)

_WEATHER_STRATEGY_NAME = "weather"

# Module-level TTL cache: (city, date) → (expires_monotonic, markets, forecasts)
# Shared across all WeatherDomainStrategy instances so the forecast + market
# API calls happen once per city per scan tick regardless of user count.
#
# _IN_FLIGHT tracks in-progress fetch Tasks per (city, date).  A second
# coroutine that hits the cache during a live fetch awaits the same Task
# instead of launching a duplicate API call (single-flight pattern).
_FORECAST_CACHE: dict[tuple[str, str], tuple[float, list[Any], list[Any]]] = {}
_IN_FLIGHT: dict[tuple[str, str], "asyncio.Task[tuple[list[Any], list[Any]]]"] = {}
_CACHE_TTL_S: float = 300.0  # 5 minutes


def _cache_get(city: str, date: str) -> tuple[list[Any], list[Any]] | None:
    entry = _FORECAST_CACHE.get((city, date))
    if entry is None:
        return None
    expires, markets, forecasts = entry
    if time.monotonic() > expires:
        del _FORECAST_CACHE[(city, date)]
        return None
    return markets, forecasts


def _cache_set(city: str, date: str, markets: list[Any], forecasts: list[Any]) -> None:
    now = time.monotonic()
    # Evict all stale entries to prevent memory accumulation as dates roll over.
    expired = [k for k, v in _FORECAST_CACHE.items() if now > v[0]]
    for k in expired:
        _FORECAST_CACHE.pop(k, None)
    _FORECAST_CACHE[(city, date)] = (now + _CACHE_TTL_S, markets, forecasts)


class WeatherDomainStrategy(BaseStrategy):
    """BaseStrategy adapter for temperature-market edge detection.

    Wraps the forecast pipeline (Open-Meteo ECMWF/HRRR + METAR + Visual
    Crossing), Polymarket Gamma market discovery, and MAE-calibrated sigma
    into the standard CrusaderBot domain strategy interface.
    """

    name: str = _WEATHER_STRATEGY_NAME
    version: str = "1.0.0"
    risk_profile_compatibility: list[str] = ["conservative", "balanced", "aggressive"]

    async def scan(
        self,
        market_filters: MarketFilters,
        user_context: UserContext,
    ) -> list[SignalCandidate]:
        """Scan all 20 weather cities and emit YES-side SignalCandidates.

        Position sizing uses user equity as bankroll so each candidate
        reflects real per-user capital limits. Empty list when the strategy
        is disabled, no forecasts available, or no edge clears the EV floor.
        """
        from ....config import get_settings
        try:
            cfg = get_settings()
            if not getattr(cfg, "WEATHER_STRATEGY_ENABLED", False):
                return []
        except Exception:
            return []

        from ....strategies.weather.calibration import get_sigma
        from ....strategies.weather.forecast import ensemble_tmax, fetch_all
        from ....strategies.weather.locations import LOCATION_BY_CITY, LOCATIONS
        from ....strategies.weather.market import fetch_weather_markets
        from ....strategies.weather.math_utils import (
            bucket_prob,
            expected_value,
            kelly_size,
        )
        from ....strategies.weather.strategy import _hours_to_expiry, _load_config

        weather_cfg = _load_config()
        sigma = get_sigma()

        min_ev: float = weather_cfg.get("min_ev", 0.10)
        min_volume: float = weather_cfg.get("min_volume", 500.0)
        max_spread: float = weather_cfg.get("max_spread", 0.03)
        max_price: float = weather_cfg.get("max_price", 0.45)
        kelly_alpha: float = weather_cfg.get("kelly_alpha", 0.25)
        max_bet: float = weather_cfg.get("max_bet_usdc", 20.0)
        min_hours: float = float(weather_cfg.get("min_hours_to_expiry", 2.0))
        max_hours: float = float(weather_cfg.get("max_hours_to_expiry", 72.0))
        min_size: float = float(weather_cfg.get("min_size_usdc", 0.50))

        bankroll = max(user_context.equity_usdc, user_context.available_balance_usdc, 1.0)

        today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        sem = asyncio.Semaphore(5)

        async def _fetch_city(loc_name: str, loc: Any) -> tuple[list[Any], list[Any]]:
            """Fetch markets + forecasts, deduplicated via _IN_FLIGHT single-flight."""
            key = (loc_name, today_utc)
            # Check cache first — fast path, no Task allocation.
            cached = _cache_get(loc_name, today_utc)
            if cached is not None:
                return cached
            # If a fetch is already in-flight for this city+date, await it
            # instead of launching a duplicate API call.
            existing = _IN_FLIGHT.get(key)
            if existing is not None:
                try:
                    return await existing
                except Exception:
                    return [], []
            # We're first — create the Task and register it.
            async def _do_fetch() -> tuple[list[Any], list[Any]]:
                result = await asyncio.gather(
                    fetch_weather_markets(city=loc_name, limit=20),
                    fetch_all(loc, today_utc),
                    return_exceptions=False,
                )
                m, f = result  # type: ignore[misc]
                _cache_set(loc_name, today_utc, m, f)
                return m, f
            task: asyncio.Task[tuple[list[Any], list[Any]]] = asyncio.ensure_future(_do_fetch())
            _IN_FLIGHT[key] = task
            try:
                result2 = await task
            except Exception as exc:
                log.warning("weather_domain_city_scan_failed",
                            extra={"city": loc_name, "err": str(exc)})
                result2 = ([], [])
            finally:
                _IN_FLIGHT.pop(key, None)
            return result2

        async def _scan_city(loc_name: str) -> list[SignalCandidate]:
            async with sem:
                loc = LOCATION_BY_CITY.get(loc_name)
                if not loc:
                    return []

                markets, forecasts = await _fetch_city(loc_name, loc)

                if not markets or not forecasts:
                    log.debug(
                        "weather_city_no_data",
                        extra={"city": loc_name, "markets": len(markets), "forecasts": len(forecasts)},
                    )
                    return []

                mean_tmax = ensemble_tmax(forecasts)
                if mean_tmax is None:
                    log.debug("weather_city_no_ensemble", extra={"city": loc_name})
                    return []

                city_cands: list[SignalCandidate] = []
                skip_vol = skip_spread = skip_price = skip_bucket = skip_hours = skip_ev = skip_size = 0
                for wm in markets:
                    if wm.volume_24h < min_volume:
                        skip_vol += 1
                        continue
                    if wm.spread > max_spread:
                        skip_spread += 1
                        continue
                    if wm.yes_price > max_price:
                        skip_price += 1
                        continue
                    if wm.bucket_low is None or wm.bucket_high is None:
                        skip_bucket += 1
                        continue
                    if market_filters.blacklisted_market_ids and wm.market_id in market_filters.blacklisted_market_ids:
                        continue

                    # Entry time-to-expiry gate (WARP-49: MIN_HOURS=2, MAX_HOURS=72)
                    hours = _hours_to_expiry(wm.end_date_iso)
                    if hours is None or hours < min_hours or hours > max_hours:
                        skip_hours += 1
                        continue

                    p_true = bucket_prob(mean_tmax, sigma, wm.bucket_low, wm.bucket_high)
                    ev = expected_value(p_true, wm.yes_price)
                    if ev < min_ev:
                        skip_ev += 1
                        continue

                    size = kelly_size(
                        ev=ev,
                        p_true=p_true,
                        price=wm.yes_price,
                        bankroll=bankroll,
                        alpha=kelly_alpha,
                        max_bet=max_bet,
                    )
                    # Minimum order size gate (WARP-49: MIN_SIZE≥$0.50)
                    if size < min_size:
                        skip_size += 1
                        continue

                    confidence = min(p_true, 0.99)
                    city_cands.append(
                        SignalCandidate(
                            market_id=wm.market_id,
                            condition_id=wm.condition_id,
                            side="YES",
                            confidence=confidence,
                            suggested_size_usdc=size,
                            strategy_name=_WEATHER_STRATEGY_NAME,
                            signal_ts=datetime.now(timezone.utc),
                            metadata={
                                "city": wm.city,
                                "yes_price": wm.yes_price,
                                "p_true": round(p_true, 4),
                                "ev": round(ev, 4),
                                "mean_tmax_f": round(mean_tmax, 1),
                                "sigma_f": round(sigma, 2),
                                "bucket_low": wm.bucket_low,
                                "bucket_high": wm.bucket_high,
                                "end_date": wm.end_date_iso,
                                "hours_to_expiry": round(hours, 1),
                            },
                            reasoning=(
                                f"{wm.city}: p_true={p_true:.3f} vs price={wm.yes_price:.3f}, "
                                f"EV={ev:.3f}, tmax={mean_tmax:.1f}°F±{sigma:.1f}, "
                                f"expires_in={hours:.0f}h"
                            ),
                        )
                    )
                log.debug(
                    "weather_city_scan_result",
                    extra={
                        "city": loc_name,
                        "markets_found": len(markets),
                        "candidates": len(city_cands),
                        "skip_vol": skip_vol,
                        "skip_spread": skip_spread,
                        "skip_price": skip_price,
                        "skip_bucket": skip_bucket,
                        "skip_hours": skip_hours,
                        "skip_ev": skip_ev,
                        "skip_size": skip_size,
                        "mean_tmax_f": round(mean_tmax, 1),
                    },
                )
                return city_cands

        loc_names = [loc.city for loc in LOCATIONS]
        results = await asyncio.gather(*[_scan_city(c) for c in loc_names], return_exceptions=True)

        candidates: list[SignalCandidate] = []
        for city_name, result in zip(loc_names, results):
            if isinstance(result, Exception):
                log.warning("weather_domain_scan_city_error",
                            extra={"city": city_name, "err": str(result)})
            else:
                candidates.extend(result)

        return candidates

    async def evaluate_exit(self, position: dict[str, Any]) -> ExitDecision:
        """Evaluate stop-loss, trailing-stop, take-profit, and forecast-shift exits."""
        from ....config import get_settings
        try:
            cfg = get_settings()
            if not getattr(cfg, "WEATHER_STRATEGY_ENABLED", False):
                return ExitDecision(should_exit=False, reason="hold")
        except Exception:
            return ExitDecision(should_exit=False, reason="hold")

        from ....strategies.weather.calibration import get_sigma
        from ....strategies.weather.forecast import ensemble_tmax, fetch_all
        from ....strategies.weather.locations import LOCATION_BY_CITY
        from ....strategies.weather.math_utils import bucket_prob
        from ....strategies.weather.strategy import _hours_to_expiry, _load_config

        weather_cfg = _load_config()
        stop_loss_pct: float = weather_cfg.get("stop_loss_pct", 0.20)
        tp_48h: float = weather_cfg.get("tp_48h", 0.85)
        tp_48h_plus: float = weather_cfg.get("tp_48h_plus", 0.75)

        entry_price: float = float(position.get("entry_price", 0.5))
        current_price: float = float(position.get("current_price", entry_price))
        end_date: str = str(position.get("end_date") or position.get("end_date_iso") or "")
        city: str = str(position.get("city") or "")

        # Exit 1: hard stop-loss
        if current_price <= entry_price * (1.0 - stop_loss_pct):
            return ExitDecision(
                should_exit=True,
                reason="strategy_exit",
                metadata={"trigger": "stop_loss", "entry": entry_price, "current": current_price},
            )

        # Exit 2: trailing stop — breakeven activation when price was +20% above entry.
        # high_water_price must be stored in position metadata by the execution layer
        # and updated whenever current_price sets a new high.
        high_water_raw = position.get("high_water_price")
        if high_water_raw is not None:
            high_water: float = float(high_water_raw)
            if high_water >= entry_price * 1.20 and current_price < entry_price:
                return ExitDecision(
                    should_exit=True,
                    reason="strategy_exit",
                    metadata={
                        "trigger": "trailing_stop_breakeven",
                        "entry": entry_price,
                        "high_water": high_water,
                        "current": current_price,
                    },
                )

        # Exit 3: take-profit windows
        hours_remaining = _hours_to_expiry(end_date)
        if hours_remaining is not None:
            if 24 <= hours_remaining <= 48 and current_price >= tp_48h:
                return ExitDecision(
                    should_exit=True,
                    reason="strategy_exit",
                    metadata={"trigger": "tp_48h", "current": current_price, "threshold": tp_48h},
                )
            if hours_remaining > 48 and current_price >= tp_48h_plus:
                return ExitDecision(
                    should_exit=True,
                    reason="strategy_exit",
                    metadata={"trigger": "tp_48h_plus", "current": current_price, "threshold": tp_48h_plus},
                )

        # Exit 4: forecast-shift — adaptive threshold based on bucket size + 2°F buffer.
        # Exits when the current forecast mean moves outside [bucket_low - 2, bucket_high + 2],
        # i.e., clearly outside the original temperature range.
        loc = LOCATION_BY_CITY.get(city)
        if loc and end_date:
            target_date = end_date[:10] if end_date else datetime.now(timezone.utc).strftime("%Y-%m-%d")
            try:
                forecasts = await fetch_all(loc, target_date)
                current_mean = ensemble_tmax(forecasts)
                entry_mean_val = position.get("entry_mean_tmax_f") or position.get("mean_tmax_f")
                bucket_low_raw = position.get("bucket_low")
                bucket_high_raw = position.get("bucket_high")

                if (
                    entry_mean_val is not None
                    and current_mean is not None
                    and bucket_low_raw is not None
                    and bucket_high_raw is not None
                ):
                    bucket_low = float(bucket_low_raw)
                    bucket_high = float(bucket_high_raw)
                    half_range = (bucket_high - bucket_low) / 2.0
                    buffer = half_range + 2.0
                    bucket_mid = (bucket_low + bucket_high) / 2.0

                    if abs(current_mean - bucket_mid) > buffer:
                        sigma = get_sigma()
                        p_new = bucket_prob(current_mean, sigma, bucket_low, bucket_high)
                        return ExitDecision(
                            should_exit=True,
                            reason="strategy_exit",
                            metadata={
                                "trigger": "forecast_shift",
                                "entry_mean": entry_mean_val,
                                "current_mean": current_mean,
                                "bucket_mid": bucket_mid,
                                "half_range": half_range,
                                "buffer": buffer,
                                "p_new": round(p_new, 4),
                                "shift_from_mid": round(abs(current_mean - bucket_mid), 2),
                            },
                        )
                elif entry_mean_val is not None and current_mean is not None:
                    # Fallback when bucket bounds not in position metadata: fixed 2°F shift
                    if abs(current_mean - float(entry_mean_val)) >= 2.0:
                        return ExitDecision(
                            should_exit=True,
                            reason="strategy_exit",
                            metadata={
                                "trigger": "forecast_shift_fallback",
                                "entry_mean": entry_mean_val,
                                "current_mean": current_mean,
                                "shift": round(abs(current_mean - float(entry_mean_val)), 2),
                            },
                        )
            except Exception as exc:
                log.warning("weather_domain_evaluate_exit_forecast_failed",
                            extra={"city": city, "err": str(exc)})

        # Exit 5: expiry catch — close within final 2 hours
        if hours_remaining is not None and 0 < hours_remaining <= 2:
            return ExitDecision(
                should_exit=True,
                reason="strategy_exit",
                metadata={"trigger": "near_expiry", "hours_remaining": round(hours_remaining, 2)},
            )

        return ExitDecision(should_exit=False, reason="hold")

    def default_tp_sl(self) -> tuple[float, float]:
        """Returns (tp_pct=0.25, sl_pct=0.20) — aligned with tp_48h / stop_loss_pct."""
        return (0.25, 0.20)
