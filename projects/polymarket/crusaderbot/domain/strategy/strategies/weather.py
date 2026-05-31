"""WeatherDomainStrategy — BaseStrategy adapter wrapping strategies/weather/.

Bridges the autonomous WeatherStrategy (forecast + calibration + market fetch)
to the CrusaderBot domain strategy plane (SignalCandidate / ExitDecision /
UserContext). Called by signal_scan_job.run_once() for users on the
`weather_monitor` preset.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from ..base import BaseStrategy
from ..types import ExitDecision, MarketFilters, SignalCandidate, UserContext

log = logging.getLogger(__name__)

_WEATHER_STRATEGY_NAME = "weather"


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
        from ....strategies.weather.strategy import _load_config

        weather_cfg = _load_config()
        sigma = get_sigma()

        min_ev: float = weather_cfg.get("min_ev", 0.10)
        min_volume: float = weather_cfg.get("min_volume", 500.0)
        max_spread: float = weather_cfg.get("max_spread", 0.03)
        max_price: float = weather_cfg.get("max_price", 0.45)
        kelly_alpha: float = weather_cfg.get("kelly_alpha", 0.25)
        max_bet: float = weather_cfg.get("max_bet_usdc", 20.0)

        bankroll = max(user_context.equity_usdc, user_context.available_balance_usdc, 1.0)

        today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        sem = asyncio.Semaphore(5)

        async def _scan_city(loc_name: str) -> list[SignalCandidate]:
            async with sem:
                loc = LOCATION_BY_CITY.get(loc_name)
                if not loc:
                    return []
                try:
                    markets, forecasts = await asyncio.gather(
                        fetch_weather_markets(city=loc_name, limit=20),
                        fetch_all(loc, today_utc),
                        return_exceptions=False,
                    )
                except Exception as exc:
                    log.warning("weather_domain_city_scan_failed",
                                extra={"city": loc_name, "err": str(exc)})
                    return []

                if not markets or not forecasts:
                    return []

                mean_tmax = ensemble_tmax(forecasts)
                if mean_tmax is None:
                    return []

                city_cands: list[SignalCandidate] = []
                for wm in markets:
                    if wm.volume_24h < min_volume:
                        continue
                    if wm.spread > max_spread:
                        continue
                    if wm.yes_price > max_price:
                        continue
                    if wm.bucket_low is None or wm.bucket_high is None:
                        continue
                    if market_filters.blacklisted_market_ids and wm.market_id in market_filters.blacklisted_market_ids:
                        continue

                    p_true = bucket_prob(mean_tmax, sigma, wm.bucket_low, wm.bucket_high)
                    ev = expected_value(p_true, wm.yes_price)
                    if ev < min_ev:
                        continue

                    size = kelly_size(
                        ev=ev,
                        p_true=p_true,
                        price=wm.yes_price,
                        bankroll=bankroll,
                        alpha=kelly_alpha,
                        max_bet=max_bet,
                    )
                    if size <= 0:
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
                            },
                            reasoning=(
                                f"{wm.city}: p_true={p_true:.3f} vs price={wm.yes_price:.3f}, "
                                f"EV={ev:.3f}, tmax={mean_tmax:.1f}°F±{sigma:.1f}"
                            ),
                        )
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
        """Evaluate stop-loss, take-profit, and forecast-shift exits."""
        from ....config import get_settings
        try:
            cfg = get_settings()
            if not getattr(cfg, "WEATHER_STRATEGY_ENABLED", False):
                return ExitDecision(should_exit=False, reason="hold")
        except Exception:
            return ExitDecision(should_exit=False, reason="hold")

        from ....strategies.weather.forecast import ensemble_tmax, fetch_all
        from ....strategies.weather.locations import LOCATION_BY_CITY
        from ....strategies.weather.strategy import _hours_to_expiry, _load_config

        weather_cfg = _load_config()
        stop_loss_pct: float = weather_cfg.get("stop_loss_pct", 0.20)
        tp_48h: float = weather_cfg.get("tp_48h", 0.85)
        tp_48h_plus: float = weather_cfg.get("tp_48h_plus", 0.75)
        forecast_exit_shift: float = weather_cfg.get("forecast_exit_shift_f", 2.0)

        entry_price: float = float(position.get("entry_price", 0.5))
        current_price: float = float(position.get("current_price", entry_price))
        end_date: str = str(position.get("end_date") or position.get("end_date_iso") or "")
        city: str = str(position.get("city") or "")

        if current_price <= entry_price * (1.0 - stop_loss_pct):
            return ExitDecision(
                should_exit=True,
                reason="strategy_exit",
                metadata={"trigger": "stop_loss", "entry": entry_price, "current": current_price},
            )

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

        loc = LOCATION_BY_CITY.get(city)
        if loc and end_date:
            target_date = end_date[:10] if end_date else datetime.now(timezone.utc).strftime("%Y-%m-%d")
            try:
                forecasts = await fetch_all(loc, target_date)
                current_mean = ensemble_tmax(forecasts)
                entry_mean: float = float(position.get("entry_mean_tmax_f") or 0.0)
                if current_mean is not None and abs(current_mean - entry_mean) >= forecast_exit_shift:
                    return ExitDecision(
                        should_exit=True,
                        reason="strategy_exit",
                        metadata={
                            "trigger": "forecast_shift",
                            "entry_mean": entry_mean,
                            "current_mean": current_mean,
                            "shift": round(abs(current_mean - entry_mean), 2),
                        },
                    )
            except Exception as exc:
                log.warning("weather_domain_evaluate_exit_forecast_failed",
                            extra={"city": city, "err": str(exc)})

        return ExitDecision(should_exit=False, reason="hold")

    def default_tp_sl(self) -> tuple[float, float]:
        """Returns (tp_pct=0.25, sl_pct=0.20) — aligned with tp_48h / stop_loss_pct."""
        return (0.25, 0.20)
