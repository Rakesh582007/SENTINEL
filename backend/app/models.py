"""Pydantic request bodies for the REST API (ranges = the simulator slider ranges)."""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

Lat = Annotated[float, Field(ge=-90, le=90)]
Lon = Annotated[float, Field(ge=-180, le=180)]
LatLon = tuple[Lat, Lon]


class ModeIn(BaseModel):
    mode: Literal["live", "replay"]
    recordings: list[str] | None = None  # file names in data/recordings; None = newest hours (or the bundled sample)
    speed: float | None = Field(None, ge=0.1, le=20)
    start_ts: float | None = None


class RegionIn(BaseModel):
    name: str | None = None  # a preset from regions.REGIONS
    points: str | None = None  # or custom circles "lat,lon,radius_nm;..."


class SeekIn(BaseModel):
    ts: float


class SpeedIn(BaseModel):
    speed: float = Field(ge=0.1, le=20)


class JammingIn(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    kind: Literal["jamming"] = "jamming"
    center: LatLon  # [lat, lon]
    radius_km: float = Field(60, ge=10, le=150)
    strength: float = Field(0.7, ge=0, le=1)  # share of aircraft inside that lose GPS integrity
    position_loss: float = Field(0.3, ge=0, le=1)  # share of those that also stop reporting a position
    duration_s: float | None = Field(None, ge=60, le=1800)  # None = until switched off


class SpoofIn(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    kind: Literal["spoof"] = "spoof"
    hex: str = "random"  # or an aircraft hex from the map
    offset_km: float = Field(25, ge=0, le=80)
    bearing_deg: float = Field(45, ge=0, lt=360)
    alt_offset_ft: float = Field(0, ge=-4000, le=4000)
    duration_s: float | None = Field(300, ge=30, le=1800)


AttackIn = Annotated[Union[JammingIn, SpoofIn], Field(discriminator="kind")]


class AttackPatch(BaseModel):
    """Slider moves. Only the fields sent are changed (exclude_unset).

    An explicit null is ignored (Injector.update), except duration_s: null there
    means "until switched off". NaN/inf are rejected (JSON.stringify sends NaN as null,
    other clients may send NaN literally).
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    active: bool | None = None
    duration_s: float | None = Field(None, ge=30, le=1800)
    center: LatLon | None = None
    radius_km: float | None = Field(None, ge=10, le=150)
    strength: float | None = Field(None, ge=0, le=1)
    position_loss: float | None = Field(None, ge=0, le=1)
    hex: str | None = None  # an aircraft hex, or "random": a random airborne aircraft (409 if none)
    offset_km: float | None = Field(None, ge=0, le=80)
    bearing_deg: float | None = Field(None, ge=0, lt=360)
    alt_offset_ft: float | None = Field(None, ge=-4000, le=4000)


class SentinelIn(BaseModel):
    """What the ESP32 posts (HANDOVER §9.1). Extra fields are kept as-is.
    NaN/inf are rejected: a stored NaN made GET /api/sentinel/latest fail (500)."""

    model_config = ConfigDict(extra="allow", allow_inf_nan=False)
    id: str = "sentinel-1"
    ts: float | None = None  # device millis since boot; the server stamps recv_ts itself
    lat: float | None = None
    lon: float | None = None
    alt: float | None = None
    fix: bool = False
    sats_used: int | None = None
    sats_in_view: int | None = None
    avg_snr: float | None = None
    hdop: float | None = None
    status: str = "OK"
    snr_list: list[float] | None = None
