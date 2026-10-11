"""The normalised aircraft record: one per aircraft per API answer.

A slots dataclass rather than a pydantic model, because replaying a long
recording pushes millions of these through the pipeline. Validation happens
once, in ingest/normalize.py; API responses use the pydantic models in models.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# readsb `type` values whose position comes from the aircraft's own navigation
# system (so nic / nac_p describe that aircraft's GPS). MLAT, TIS-B, ADS-R and
# Mode S positions do not, so they are excluded from GPS-integrity checks.
GPS_SOURCED_TYPES = frozenset({"adsb_icao", "adsb_other"})


@dataclass(slots=True)
class Record:
    ts: float  # unix s: when the position was valid (poll_ts - seen_pos), or the last message if no position
    poll_ts: float  # unix s: when we received the API answer; drives replay order
    hex: str  # ICAO 24-bit id, lowercase ("~" prefix = non-ICAO address)
    source: str  # "adsb.fi" | "adsb.lol" | ...
    flight: str | None = None
    lat: float | None = None  # None = no current position
    lon: float | None = None
    last_lat: float | None = None  # readsb `lastPosition` once the current position is >60 s old
    last_lon: float | None = None
    alt_baro: int | None = None  # feet, pressure altitude
    alt_geom: int | None = None  # feet, GNSS altitude (WGS84 ellipsoid)
    on_ground: bool = False
    gs: float | None = None  # knots
    track: float | None = None  # degrees true; falls back to calc_track
    nic: int | None = None
    nac_p: int | None = None
    version: int | None = None  # ADS-B version 0/1/2
    src_type: str | None = None  # readsb `type`: adsb_icao, mlat, mode_s, ...
    seen: float | None = None  # s since any message
    seen_pos: float | None = None  # s since last position
    gps_ok_before: float | None = None  # readsb experimental: GPS was fine before this unix time
    gps_ok_lat: float | None = None  # readsb experimental: last position while GPS was still fine
    gps_ok_lon: float | None = None
    injected: str | None = None  # comma-separated attack ids when the simulator altered this record
    original: Record | None = field(default=None, repr=False, compare=False)  # pristine copy before injection

    @property
    def has_position(self) -> bool:
        return self.lat is not None and self.lon is not None

    def best_position(self) -> tuple[float, float] | None:
        """Current position if we have one, otherwise the last known one."""
        if self.lat is not None and self.lon is not None:
            return (self.lat, self.lon)
        if self.last_lat is not None and self.last_lon is not None:
            return (self.last_lat, self.last_lon)
        return None

    @property
    def gps_sourced(self) -> bool:
        """True when nic/nac_p describe this aircraft's own GPS (unknown type counts as yes)."""
        return self.src_type is None or self.src_type in GPS_SOURCED_TYPES

    @property
    def airborne(self) -> bool:
        return not self.on_ground

    def to_dict(self) -> dict:
        return {
            "ts": self.ts,
            "hex": self.hex,
            "flight": self.flight,
            "lat": self.lat,
            "lon": self.lon,
            "last_lat": self.last_lat,
            "last_lon": self.last_lon,
            "alt_baro": self.alt_baro,
            "alt_geom": self.alt_geom,
            "on_ground": self.on_ground,
            "gs": self.gs,
            "track": self.track,
            "nic": self.nic,
            "nac_p": self.nac_p,
            "version": self.version,
            "src_type": self.src_type,
            "seen": self.seen,
            "seen_pos": self.seen_pos,
            "gps_ok_before": self.gps_ok_before,
            "gps_ok_lat": self.gps_ok_lat,
            "gps_ok_lon": self.gps_ok_lon,
            "source": self.source,
            "injected": self.injected,
        }
