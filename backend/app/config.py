"""Every tunable number lives here (HANDOVER §12: no magic numbers in logic).

Two kinds of settings:
- `Settings`: fixed at startup, from environment variables prefixed GAW_
  or a .env file at the repo root (see .env.example).
- `DetectionConfig`: detection thresholds the judges can move at runtime via
  PATCH /api/config/detection. Read them with get_detection() on every tick,
  never cache them in a module.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.regions import DEFAULT_REGION

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GAW_", env_file=str(REPO_ROOT / ".env"), extra="ignore")

    # What runs at startup
    mode: Literal["live", "replay"] = "replay"  # the demo defaults to replay; live is a bonus
    autostart: bool = True  # tests set this False

    # Live ingestion
    region: str = DEFAULT_REGION
    sources: list[str] = ["adsb.fi", "adsb.lol"]  # env: GAW_SOURCES='["adsb.fi","adsb.lol"]'
    sweep_interval_s: float | None = None  # None = per-region default from regions.SWEEP_INTERVAL_S
    request_spacing_s: float = 1.1  # gap between consecutive API requests
    http_timeout_s: float = 15.0
    record_live: bool = True  # the live poller also writes raw recordings (stop scripts/record.py first)

    # Paths
    recordings_dir: Path = REPO_ROOT / "data" / "recordings"
    db_path: Path = REPO_ROOT / "data" / "app.db"
    scenarios_dir: Path = REPO_ROOT / "scenarios"

    # Pipeline timing
    tick_s: float = 5.0  # detector tick; 5 s so slider changes feel instant
    window_keep_s: float = 1800.0  # in-memory history kept; must be >= the largest detection window
    aircraft_max_age_s: float = 90.0  # an aircraft stays on the map this long after its last record

    # Replay
    replay_default_hours: float = 3.0  # with no files chosen, replay the newest N hours of recordings
    replay_speed: float = 1.0
    replay_max_speed: float = 20.0
    replay_loop: bool = True

    # Web
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # Ground Sentinel (ESP32 box)
    sentinel_offline_s: float = 10.0
    sentinel_history_max: int = 2000  # packets kept per device (~66 min at one packet per 2 s)


class DetectionConfig(BaseModel):
    """Thresholds from HANDOVER §6. Ranges match the Attack Simulator sliders (§7.1)."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    # §6.1 jamming, per H3 cell
    h3_res: int = Field(3, ge=2, le=4)  # 3 ~ 12,400 km2 cells; 2 for sparse regions; 4 for zoomed views
    jam_window_s: int = Field(1200, ge=300, le=1800)
    nacp_bad: int = Field(7, ge=5, le=9)
    nic_bad: int = Field(5, ge=0, le=8)
    min_aircraft: int = Field(3, ge=2, le=6)
    jam_min_bad: int = Field(2, ge=1, le=10)
    jam_lower_bound: float = Field(0.15, ge=0.0, le=1.0)  # Wilson 95% lower bound on the bad share
    degraded_frac: float = Field(0.10, ge=0.0, le=1.0)
    pos_loss_seen_max_s: float = 10.0  # still hearing the aircraft...
    pos_loss_seen_pos_min_s: float = 60.0  # ...but no position for this long
    gps_sourced_only: bool = True  # ignore MLAT/TIS-B/Mode-S positions for GPS-integrity checks

    # §6.2 spoofing, per aircraft
    jump_speed_kt: float = 1000.0
    jump_min_km: float = 5.0
    jump_min_dt_s: float = 5.0  # two sources can report the same aircraft ~1 s apart; ignore such pairs
    alt_peer_radius_km: float = 300.0
    alt_peer_window_s: int = 600
    alt_min_peers: int = 4
    alt_abs_ft: float = 1000.0
    alt_mad_k: float = 4.0
    cluster_radius_km: float = 1.0
    cluster_min_aircraft: int = 3
    cluster_dt_s: float = 10.0
    cluster_alt_spread_ft: float = 3000.0
    track_mismatch_deg: float = 60.0
    track_mismatch_min_gs_kt: float = 150.0
    spoof_cell_min_flags: int = Field(2, ge=1, le=5)  # weak-evidence aircraft needed before a cell turns purple

    # §6.3 early warning
    warn_horizon_s: int = 900
    warn_step_s: int = 30

    # §6.4 incidents
    incident_close_s: int = 600
    jammer_radius_pct: float = 80.0
    jammer_min_radius_km: float = 15.0

    # §6.5 evaluation
    eval_detect_within_s: int = 300


settings = Settings()

_detection = DetectionConfig()


def get_detection() -> DetectionConfig:
    return _detection


def update_detection(changes: dict) -> DetectionConfig:
    """Validate a partial update against the field ranges, then swap it in atomically."""
    global _detection
    _detection = DetectionConfig.model_validate({**_detection.model_dump(), **changes})
    return _detection


def reset_detection() -> DetectionConfig:
    global _detection
    _detection = DetectionConfig()
    return _detection
