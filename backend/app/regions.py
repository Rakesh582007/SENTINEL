"""Region presets: which circles the poller asks the ADS-B APIs about.

Stdlib only, because the standalone recorder imports this before anyone has
run `pip install`.

The key idea: H3 hexagons tile the whole planet, so detection works anywhere
with zero code change. A "region" is only the list of query circles. Each
circle costs one API request per source per sweep, and both APIs cap the
radius at 250 NM (~463 km). Hexagons appear wherever aircraft are; a region
with few aircraft simply shows most cells as "insufficient".
"""
from __future__ import annotations

from dataclasses import dataclass

MAX_RADIUS_NM = 250  # adsb.fi (v3) and adsb.lol both cap point queries at 250 NM
NM_TO_KM = 1.852


@dataclass(frozen=True)
class QueryPoint:
    name: str
    lat: float
    lon: float
    radius_nm: int

    def __post_init__(self) -> None:
        if not (-90 <= self.lat <= 90 and -180 <= self.lon <= 180):
            raise ValueError(f"bad coordinates for query point {self.name!r}")
        if not (1 <= self.radius_nm <= MAX_RADIUS_NM):
            raise ValueError(f"radius_nm must be 1..{MAX_RADIUS_NM} for {self.name!r}")

    @property
    def radius_km(self) -> float:
        return self.radius_nm * NM_TO_KM

    def as_dict(self) -> dict:
        return {"name": self.name, "lat": self.lat, "lon": self.lon, "radius_nm": self.radius_nm}


# Measured 11 Oct 2026 ~12:14 IST (union of adsb.fi + adsb.lol):
#   amritsar 44 aircraft, jk 3, delhi 51. J&K is nearly blind with free data.
AMRITSAR = QueryPoint("amritsar", 31.6, 74.9, 250)  # Punjab + border belt (63% of reported incidents)
JK = QueryPoint("jk", 33.6, 75.0, 150)  # J&K; very few receivers feed this area
DELHI = QueryPoint("delhi", 28.6, 77.2, 150)  # densest nearby traffic; good for simulator demos

# 11 mainland circles of 250 NM that between them reach every major Indian
# airport (checked in tests/test_regions.py), plus the Andaman islands.
ALL_INDIA = (
    QueryPoint("north", 33.0, 76.0, 250),
    QueryPoint("rajasthan", 28.0, 73.5, 250),
    QueryPoint("up", 27.0, 81.0, 250),
    QueryPoint("east", 25.5, 88.5, 250),
    QueryPoint("northeast", 26.0, 94.0, 250),
    QueryPoint("gujarat", 23.0, 70.5, 250),
    QueryPoint("central", 22.5, 77.5, 250),
    QueryPoint("odisha", 21.0, 84.5, 250),
    QueryPoint("west", 18.5, 74.5, 250),
    QueryPoint("deccan", 16.5, 80.5, 250),
    QueryPoint("south", 12.0, 77.0, 250),
    QueryPoint("andaman", 11.6, 92.7, 150),
)

REGIONS: dict[str, tuple[QueryPoint, ...]] = {
    "nw_border": (AMRITSAR, JK),
    "delhi": (DELHI,),
    "north_india": (AMRITSAR, JK, DELHI),
    "all_india": ALL_INDIA,
}

DEFAULT_REGION = "north_india"

# Seconds between the starts of two sweeps. A sweep = every point x every source.
# With 2 sources and ~1.1 s between requests, each host stays well under 1 req/s.
SWEEP_INTERVAL_S: dict[str, float] = {
    "nw_border": 10.0,
    "delhi": 10.0,
    "north_india": 10.0,
    "all_india": 60.0,
}


def get_region(name: str) -> tuple[QueryPoint, ...]:
    try:
        return REGIONS[name]
    except KeyError:
        raise KeyError(f"unknown region {name!r}; choose one of {sorted(REGIONS)}") from None


def parse_points(spec: str) -> tuple[QueryPoint, ...]:
    """Parse "lat,lon,radius_nm;lat,lon,radius_nm" into custom query points."""
    points = []
    for i, chunk in enumerate(p for p in spec.split(";") if p.strip()):
        parts = [x.strip() for x in chunk.split(",")]
        if len(parts) != 3:
            raise ValueError(f"point {i + 1}: expected lat,lon,radius_nm but got {chunk!r}")
        lat, lon, radius = float(parts[0]), float(parts[1]), int(float(parts[2]))
        points.append(QueryPoint(f"custom{i + 1}", lat, lon, radius))
    if not points:
        raise ValueError("no points given")
    return tuple(points)
