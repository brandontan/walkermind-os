"""Self-learning sigma calibration via MAE of resolved weather forecasts."""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_CALIBRATION_FILE: Path = (
    Path(__file__).parent.parent.parent / "data" / "weather" / "calibration.json"
)
_MIN_SAMPLES: int = 30
_DEFAULT_SIGMA: float = 3.5
_SIGMA_MIN: float = 1.0
_SIGMA_MAX: float = 8.0
_MAE_WINDOW: int = 500

_sigma_cache: float | None = None


def load_calibration() -> dict[str, Any]:
    if not _CALIBRATION_FILE.exists():
        return {"sigma": _DEFAULT_SIGMA, "mae_history": [], "sample_count": 0}
    try:
        return json.loads(_CALIBRATION_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("load_calibration failed", extra={"err": str(exc)})
        return {"sigma": _DEFAULT_SIGMA, "mae_history": [], "sample_count": 0}


def save_calibration(data: dict[str, Any]) -> None:
    _CALIBRATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        _CALIBRATION_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as exc:
        log.error("save_calibration failed", extra={"err": str(exc)})


def update_sigma(forecast_temp: float, actual_temp: float) -> float:
    """Record a resolved forecast error and update sigma when MIN_SAMPLES reached.

    Sigma is estimated as MAE * sqrt(pi/2), which is the MLE relation for a
    half-normal error distribution. Returns the current (possibly updated) sigma.
    Updates the in-memory cache so subsequent get_sigma() calls avoid disk reads.
    """
    global _sigma_cache
    data = load_calibration()
    history: list[float] = data.get("mae_history") or []
    history.append(abs(forecast_temp - actual_temp))
    data["mae_history"] = history[-_MAE_WINDOW:]
    data["sample_count"] = len(data["mae_history"])

    if len(data["mae_history"]) >= _MIN_SAMPLES:
        mae = sum(data["mae_history"]) / len(data["mae_history"])
        new_sigma = round(mae * math.sqrt(math.pi / 2.0), 2)
        new_sigma = max(_SIGMA_MIN, min(new_sigma, _SIGMA_MAX))
        data["sigma"] = new_sigma
        log.info(
            "weather calibration updated",
            extra={"sigma": new_sigma, "mae": round(mae, 3), "samples": data["sample_count"]},
        )

    save_calibration(data)
    _sigma_cache = float(data.get("sigma", _DEFAULT_SIGMA))
    return _sigma_cache


def get_sigma() -> float:
    """Return current calibrated sigma (default 3.5°F before 30 resolved samples).

    Cached in memory after the first read — avoids repeated disk I/O during the
    hourly scan where all 20 cities call this concurrently.
    """
    global _sigma_cache
    if _sigma_cache is None:
        _sigma_cache = float(load_calibration().get("sigma", _DEFAULT_SIGMA))
    return _sigma_cache
