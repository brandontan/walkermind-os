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

_CACHE_TTL_S: float = 300.0  # 5 minutes

# Global markets cache: one API call per scan window covers all cities.
# Polymarket weather markets carry no tags and rotate cities daily, so we
# fetch all active markets sorted by startDate and filter by city in Python.
# date_str → (expires_monotonic, list[WeatherMarket])
_DAILY_MARKETS_CACHE: dict[str, tuple[float, list[Any]]] = {}
_DAILY_MARKETS_IN_FLIGHT: "dict[str, asyncio.Task[list[Any]]]" = {}

# Per-(city, date) forecast cache.
_FORECAST_CACHE: dict[tuple[str, str], tuple[float, list[Any]]] = {}
_FORECAST_IN_FLIGHT: "dict[tuple[str, str], asyncio.Task[list[Any]]]" = {}


def _daily_markets_get(date: str) -> list[Any] | None:
    entry = _DAILY_MARKETS_CACHE.get(date)
    if entry is None:
        return None
    expires, markets = entry
    if time.monotonic() > expires:
        del _DAILY_MARKETS_CACHE[date]
        return None
    return markets


def _forecast_cache_get(city: str, date: str) -> list[Any] | None:
    entry = _FORECAST_CACHE.get((city, date))
    if entry is None:
        return None
    expires, forecasts = entry
    if time.monotonic() > expires:
        del _FORECAST_CACHE[(city, date)]
        return None
    return forecasts


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
        """Scan Polymarket weather cities and emit YES-side SignalCandidates.

        One global markets fetch per 5-min window covers all cities; city
        filtering happens in Python. Forecasts are fetched per-city and
        cached independently. Cities are sourced from LOCATIONS, aligned to
        Polymarket's actual daily weather market roster.
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

        async def _get_all_markets() -> list[Any]:
            """One global fetch of all active weather markets, cached 5 min.

            Polymarket weather markets carry no tags and the city roster
            rotates daily — we fetch everything sorted by startDate and
            filter by city name in Python, avoiding per-city API calls.
            """
            cached_all = _daily_markets_get(today_utc)
            if cached_all is not None:
                return cached_all
            existing_task = _DAILY_MARKETS_IN_FLIGHT.get(today_utc)
            if existing_task is not None:
                try:
                    return await existing_task
                except Exception:
                    return []
            async def _do_fetch_all() -> list[Any]:
                result = await fetch_weather_markets(city=None, limit=500)
                now = time.monotonic()
                expired_dm = [k for k, v in _DAILY_MARKETS_CACHE.items() if now > v[0]]
                for k in expired_dm:
                    _DAILY_MARKETS_CACHE.pop(k, None)
                _DAILY_MARKETS_CACHE[today_utc] = (now + _CACHE_TTL_S, result)
                return result
            task_all: asyncio.Task[list[Any]] = asyncio.ensure_future(_do_fetch_all())
            _DAILY_MARKETS_IN_FLIGHT[today_utc] = task_all
            try:
                all_markets = await task_all
            except Exception as exc:
                log.warning("weather_domain_all_markets_failed", extra={"err": str(exc)})
                all_markets = []
            finally:
                _DAILY_MARKETS_IN_FLIGHT.pop(today_utc, None)
            return all_markets

        async def _get_forecasts(loc_name: str, loc: Any) -> list[Any]:
            """Per-city forecast fetch with single-flight dedup, cached 5 min."""
            cached_fc = _forecast_cache_get(loc_name, today_utc)
            if cached_fc is not None:
                return cached_fc
            key = (loc_name, today_utc)
            existing_task = _FORECAST_IN_FLIGHT.get(key)
            if existing_task is not None:
                try:
                    return await existing_task
                except Exception:
                    return []
            async def _do_fetch_fc() -> list[Any]:
                result = await fetch_all(loc, today_utc)
                now = time.monotonic()
                expired_fc = [k for k, v in _FORECAST_CACHE.items() if now > v[0]]
                for k in expired_fc:
                    _FORECAST_CACHE.pop(k, None)
                _FORECAST_CACHE[key] = (now + _CACHE_TTL_S, result)
                return result
            task_fc: asyncio.Task[list[Any]] = asyncio.ensure_future(_do_fetch_fc())
            _FORECAST_IN_FLIGHT[key] = task_fc
            try:
                forecasts = await task_fc
            except Exception as exc:
                log.warning("weather_domain_forecast_failed",
                            extra={"city": loc_name, "err": str(exc)})
                forecasts = []
            finally:
                _FORECAST_IN_FLIGHT.pop(key, None)
            return forecasts

        async def _fetch_city(loc_name: str, loc: Any) -> tuple[list[Any], list[Any]]:
            """Return (city_markets, forecasts) using shared global caches."""
            all_markets, forecasts = await asyncio.gather(
                _get_all_markets(),
                _get_forecasts(loc_name, loc),
                return_exceptions=False,
            )
            city_markets = []
            for m in (all_markets or []):
                if loc_name.lower() in (m.question or "").lower():
                    m.city = loc_name
                    city_markets.append(m)
            return city_markets, forecasts or []

        async def _scan_city(loc_name: str) -> list[SignalCandidate]:
            async with sem:
                loc = LOCATION_BY_CITY.get(loc_name)
                if not loc:
                    return []

                markets, forecasts = await _fetch_city(loc_name, loc)

                if not markets or not forecasts:
                    log.debug(
                        "weather_city_no_data",
                        extra={
                            "city": loc_name,
                            "markets": len(markets) if markets else 0,
                            "forecasts": len(forecasts) if forecasts else 0,
                        },
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
