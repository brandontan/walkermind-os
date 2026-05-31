"""20 global city locations with ICAO METAR codes and coordinates."""
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
    # United States (5)
    Location("New York",      "US", "KJFK",  40.6413,  -73.7781, "America/New_York"),
    Location("Los Angeles",   "US", "KLAX",  33.9425, -118.4081, "America/Los_Angeles"),
    Location("Chicago",       "US", "KORD",  41.9742,  -87.9073, "America/Chicago"),
    Location("Miami",         "US", "KMIA",  25.7959,  -80.2870, "America/New_York"),
    Location("Dallas",        "US", "KDFW",  32.8998,  -97.0403, "America/Chicago"),
    # Europe (5)
    Location("London",        "GB", "EGLL",  51.4775,   -0.4614, "Europe/London"),
    Location("Paris",         "FR", "LFPG",  49.0097,    2.5478, "Europe/Paris"),
    Location("Berlin",        "DE", "EDDB",  52.3667,   13.5033, "Europe/Berlin"),
    Location("Madrid",        "ES", "LEMD",  40.4719,   -3.5626, "Europe/Madrid"),
    Location("Amsterdam",     "NL", "EHAM",  52.3086,    4.7639, "Europe/Amsterdam"),
    # Asia (4)
    Location("Tokyo",         "JP", "RJTT",  35.5494,  139.7798, "Asia/Tokyo"),
    Location("Singapore",     "SG", "WSSS",   1.3644,  103.9915, "Asia/Singapore"),
    Location("Dubai",         "AE", "OMDB",  25.2532,   55.3657, "Asia/Dubai"),
    Location("Bangkok",       "TH", "VTBS",  13.6811,  100.7470, "Asia/Bangkok"),
    # Oceania (1)
    Location("Sydney",        "AU", "YSSY", -33.9461,  151.1772, "Australia/Sydney"),
    # South America (3)
    Location("Sao Paulo",     "BR", "SBGR", -23.4356,  -46.4731, "America/Sao_Paulo"),
    Location("Buenos Aires",  "AR", "SAEZ", -34.8222,  -58.5358, "America/Argentina/Buenos_Aires"),
    Location("Bogota",        "CO", "SKBO",   4.7016,  -74.1469, "America/Bogota"),
    # North America extras (2)
    Location("Mexico City",   "MX", "MMMX",  19.4363,  -99.0721, "America/Mexico_City"),
    Location("Toronto",       "CA", "CYYZ",  43.6772,  -79.6306, "America/Toronto"),
]

LOCATION_BY_CITY: Final[dict[str, Location]] = {loc.city: loc for loc in LOCATIONS}
