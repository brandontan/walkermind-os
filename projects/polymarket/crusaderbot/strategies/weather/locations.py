"""City locations aligned to Polymarket's active weather market roster.

City names must match question text exactly (case-insensitive substring check),
e.g. "New York City" matches "Will the highest temperature in New York City be...".
Roster verified from live Gamma API 2026-06-01; Polymarket rotates cities daily
so this list is intentionally broad to cover observed and likely future cities.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class Location:
    city: str
    country: str
    metar_station: str   # ICAO airport code
    latitude: float
    longitude: float
    timezone: str        # IANA timezone for local date resolution


LOCATIONS: Final[list[Location]] = [
    # Americas
    Location("New York City", "US", "KJFK",  40.6413,  -73.7781, "America/New_York"),
    Location("Chicago",       "US", "KORD",  41.9742,  -87.9073, "America/Chicago"),
    Location("San Francisco", "US", "KSFO",  37.6213, -122.3790, "America/Los_Angeles"),
    Location("Los Angeles",   "US", "KLAX",  33.9425, -118.4081, "America/Los_Angeles"),
    Location("Miami",         "US", "KMIA",  25.7959,  -80.2870, "America/New_York"),
    Location("Dallas",        "US", "KDFW",  32.8998,  -97.0403, "America/Chicago"),
    Location("Toronto",       "CA", "CYYZ",  43.6772,  -79.6306, "America/Toronto"),
    # Europe
    Location("London",        "GB", "EGLL",  51.4775,   -0.4614, "Europe/London"),
    Location("Paris",         "FR", "LFPG",  49.0097,    2.5478, "Europe/Paris"),
    Location("Munich",        "DE", "EDDM",  48.3537,   11.7750, "Europe/Berlin"),
    Location("Berlin",        "DE", "EDDB",  52.3667,   13.5033, "Europe/Berlin"),
    Location("Madrid",        "ES", "LEMD",  40.4719,   -3.5626, "Europe/Madrid"),
    Location("Amsterdam",     "NL", "EHAM",  52.3086,    4.7639, "Europe/Amsterdam"),
    # Middle East
    Location("Dubai",         "AE", "OMDB",  25.2532,   55.3657, "Asia/Dubai"),
    Location("Jeddah",        "SA", "OEJN",  21.6796,   39.1565, "Asia/Riyadh"),
    # Asia
    Location("Tokyo",         "JP", "RJTT",  35.5494,  139.7798, "Asia/Tokyo"),
    Location("Seoul",         "KR", "RKSI",  37.4602,  126.4407, "Asia/Seoul"),
    Location("Beijing",       "CN", "ZBAA",  40.0801,  116.5846, "Asia/Shanghai"),
    Location("Shanghai",      "CN", "ZSPD",  31.1434,  121.8052, "Asia/Shanghai"),
    Location("Shenzhen",      "CN", "ZGSZ",  22.6393,  113.8106, "Asia/Shanghai"),
    Location("Wuhan",         "CN", "ZHHH",  30.7838,  114.2081, "Asia/Shanghai"),
    Location("Hong Kong",     "HK", "VHHH",  22.3080,  113.9185, "Asia/Hong_Kong"),
    Location("Singapore",     "SG", "WSSS",   1.3644,  103.9915, "Asia/Singapore"),
    Location("Kuala Lumpur",  "MY", "WMKK",   2.7456,  101.7072, "Asia/Kuala_Lumpur"),
    Location("Bangkok",       "TH", "VTBS",  13.6811,  100.7470, "Asia/Bangkok"),
]

LOCATION_BY_CITY: Final[dict[str, Location]] = {loc.city: loc for loc in LOCATIONS}
