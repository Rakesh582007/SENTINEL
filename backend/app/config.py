"""Every tunable number lives here (HANDOVER §12: no magic numbers in logic).

Two kinds of settings:
- `Settings`: fixed at startup, from environment variables prefixed GAW_
  (GEMINI_API_KEY has no prefix) or a .env file: backend/.env (see
  backend/.env.example) or the repo root .env. Both paths are resolved from
  this file, so they work whether uvicorn starts in backend/ or the repo root;
  backend/.env wins. Real environment variables beat both.
- `DetectionConfig`: detection thresholds the judges can move at runtime via
  PATCH /api/config/detection. Read them with get_detection() on every tick,
  never cache them in a module.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.regions import DEFAULT_REGION

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GAW_", env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"),
                                      env_file_encoding="utf-8", extra="ignore", populate_by_name=True)

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
    db_flush_s: float = Field(1.0, gt=0.0, le=60.0)  # queued SQLite writes are flushed this often, outside the tick
    scenarios_dir: Path = REPO_ROOT / "scenarios"

    # Pipeline timing
    tick_s: float = 5.0  # detector tick; 5 s so slider changes feel instant
    window_keep_s: float = 1800.0  # in-memory history kept; must be >= the largest detection window
    aircraft_max_age_s: float = 90.0  # an aircraft stays on the map this long after its last record

    # Replay
    replay_files: str = ""  # GAW_REPLAY_FILES: comma-separated names in recordings_dir; pins what replay plays
    replay_default_hours: float = 3.0  # with no files chosen, replay the newest N hours of recordings
    replay_speed: float = 1.0
    replay_max_speed: float = 20.0
    replay_loop: bool = True

    # Web
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # Ground Sentinel (ESP32 box)
    sentinel_offline_s: float = 10.0
    sentinel_history_max: int = 2000  # packets kept per device (~66 min at one packet per 2 s)
    # Server re-check of the box's alarms (sentinel.py; wall clock, it is real hardware)
    sentinel_baseline_s: float = Field(120.0, ge=10.0)  # fix held this long before baseline SNR + position are learned
    sentinel_snr_drop_db: float = Field(10.0, gt=0.0)  # JAMMING: avg SNR this far below the baseline
    sentinel_fix_loss_s: float = Field(5.0, gt=0.0)  # JAMMING: fix lost this long after a baseline existed
    sentinel_move_m: float = Field(50.0, gt=0.0)  # SPOOF: the fixed box "moves" this far from its reference
    sentinel_alt_jump_m: float = Field(100.0, gt=0.0)  # SPOOF: its altitude jumps this much

    # AI summary (app/ai/summary.py, decision D22): words only; detection never depends on it
    gemini_api_key: SecretStr = Field(SecretStr(""), validation_alias=AliasChoices("GEMINI_API_KEY", "GAW_GEMINI_API_KEY"))
    ai_enabled: bool = True  # GAW_AI_ENABLED; with no key the template summary is used anyway
    ai_models: str = "gemini-2.5-flash,gemini-2.5-flash-lite,gemini-2.0-flash"  # GAW_AI_MODELS, tried in order
    ai_timeout_s: float = Field(8.0, ge=2.0, le=30.0)  # per model attempt (and the PDF's whole wait)
    ai_cache_ttl_s: float = Field(120.0, ge=10.0, le=1800.0)
    ai_max_per_min: int = Field(12, ge=1, le=600)  # global limit on Gemini calls, protects the free quota

    @property
    def ai_model_list(self) -> list[str]:
        return [m.strip() for m in self.ai_models.split(",") if m.strip()]

    @property
    def replay_file_list(self) -> list[str]:
        return [n.strip() for n in self.replay_files.split(",") if n.strip()]


class DetectionConfig(BaseModel):
    """Thresholds from HANDOVER §6. Ranges match the Attack Simulator sliders (§7.1).

    Every field has bounds, so PATCH /api/config/detection answers 422 instead of
    letting a value crash the tick (e.g. warn_step_s=0 or jammer_radius_pct=150).
    """

    model_config = ConfigDict(validate_assignment=True, extra="forbid", allow_inf_nan=False)

    # §6.1 jamming, per H3 cell
    h3_res: int = Field(3, ge=2, le=4)  # 3 ~ 12,400 km2 cells; 2 for sparse regions; 4 for zoomed views
    jam_window_s: int = Field(1200, ge=300, le=1800)
    nacp_bad: int = Field(7, ge=5, le=9)
    nic_bad: int = Field(5, ge=0, le=8)
    min_aircraft: int = Field(3, ge=2, le=6)
    jam_min_bad: int = Field(2, ge=1, le=10)
    jam_lower_bound: float = Field(0.15, ge=0.0, le=1.0)  # Wilson 95% lower bound on the bad share
    degraded_frac: float = Field(0.10, ge=0.0, le=1.0)
    pos_loss_seen_max_s: float = Field(10.0, ge=1.0, le=120.0)  # still hearing the aircraft...
    pos_loss_seen_pos_min_s: float = Field(60.0, ge=10.0, le=600.0)  # ...but no position for this long
    gps_sourced_only: bool = True  # ignore MLAT/TIS-B/Mode-S positions for GPS-integrity checks

    # §6.2 spoofing, per aircraft
    jump_speed_kt: float = Field(1000.0, ge=500.0, le=5000.0)
    jump_min_km: float = Field(5.0, ge=0.5, le=100.0)
    jump_min_dt_s: float = Field(5.0, ge=0.0, le=60.0)  # two sources can report the same aircraft ~1 s apart; ignore such pairs
    alt_peer_radius_km: float = Field(300.0, ge=10.0, le=1000.0)
    alt_peer_window_s: int = Field(600, ge=60, le=1800)
    alt_min_peers: int = Field(4, ge=2, le=50)
    alt_abs_ft: float = Field(1000.0, ge=100.0, le=10000.0)
    alt_mad_k: float = Field(4.0, ge=1.0, le=20.0)
    cluster_radius_km: float = Field(1.0, ge=0.1, le=20.0)
    cluster_min_aircraft: int = Field(3, ge=2, le=20)
    cluster_dt_s: float = Field(10.0, ge=1.0, le=120.0)
    cluster_alt_spread_ft: float = Field(3000.0, ge=500.0, le=40000.0)
    track_mismatch_deg: float = Field(60.0, ge=10.0, le=180.0)
    track_mismatch_min_gs_kt: float = Field(150.0, ge=0.0, le=600.0)
    spoof_cell_min_flags: int = Field(2, ge=1, le=5)  # weak-evidence aircraft needed before a cell turns purple
    # Feed-glitch guards (decision D20; seen on real data 12 Oct 01:25 IST when adsb.fi froze for 30 s):
    spoof_frozen_speed_frac: float = Field(0.25, ge=0.05, le=0.9)  # jump start "frozen" if it moved < this x its gs...
    spoof_frozen_min_gs_kt: float = Field(100.0, ge=0.0, le=600.0)  # ...for aircraft claiming at least this speed
    spoof_mass_jump_min: int = Field(3, ge=2, le=50)  # this many aircraft jumping in one poll = feed glitch
    spoof_mass_jump_window_s: float = Field(10.0, ge=1.0, le=120.0)  # "one poll" = landings this close in time
    spoof_cluster_min_polls: int = Field(2, ge=1, le=10)  # a co-location must persist, pinned in place, this many polls
    alt_min_alt_ft: int = Field(5000, ge=0, le=20000)  # below this, QNH settings and terrain make the offset noisy
    alt_recent_readings: int = Field(3, ge=1, le=10)  # newest readings per aircraft checked for an altitude offset...
    alt_outlier_min_count: int = Field(2, ge=1, le=10)  # ...this many must be outliers (or all of them, if fewer)
    track_check_max_dt_s: float = Field(20.0, ge=5.0, le=120.0)  # longer gaps can hide a legitimate turn (3 deg/s = 60 deg in 20 s)
    track_check_min_km: float = Field(1.0, ge=0.1, le=20.0)  # shorter hops are dominated by position noise
    track_mismatch_min_count: int = Field(2, ge=1, le=10)  # a track mismatch must repeat this often
    cluster_lookback_s: float = Field(120.0, ge=10.0, le=600.0)  # only recent positions for the O(n^2) cluster check

    # §6.3 early warning
    warn_horizon_s: int = Field(900, ge=60, le=3600)
    warn_step_s: int = Field(30, ge=5, le=300)
    warn_min_gs_kt: float = Field(60.0, ge=0.0, le=300.0)  # slower = taxiing, holding low or a helicopter: no projection

    # §6.4 incidents
    incident_close_s: int = Field(600, ge=30, le=7200)
    jammer_radius_pct: float = Field(80.0, ge=1.0, le=100.0)
    jammer_min_radius_km: float = Field(15.0, ge=1.0, le=500.0)

    # §6.5 evaluation
    eval_detect_within_s: int = Field(300, ge=30, le=3600)
    eval_slack_s: float = Field(15.0, ge=0.0, le=120.0)  # a detection logged up to one poll before the recorded start still counts

    # Replay
    replay_gap_s: float = Field(120.0, ge=30.0, le=3600.0)  # a pause in the recording longer than this is skipped, not replayed

    @model_validator(mode="after")
    def _step_within_horizon(self) -> DetectionConfig:
        if self.warn_step_s > self.warn_horizon_s:
            raise ValueError("warn_step_s must not exceed warn_horizon_s")
        return self


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
