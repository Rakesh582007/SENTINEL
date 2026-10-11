"""Early warning (HANDOVER §6.3): who is flying INTO trouble.  STATUS: TODO

This is what turns a map into a safety tool: "IGO2317 enters a jammed area
in ~12 min".

Contract (wired into runtime.compute_tick; its result is sent as `alerts`):

    early_warnings(latest, alarm_cells, cfg, now) -> list[dict]

    latest:      {hex: newest Record} for aircraft heard recently
    alarm_cells: {h3 cell: "jammed" | "spoofing"} at cfg.h3_res
    returns:     [{"kind": "early_warning", "hex", "flight", "h3", "cell_state",
                   "eta_s", "entry": [lat, lon], "path": [[lat, lon], ...],
                   "injected": bool, "message": str}]

Rules:
- Only airborne aircraft with lat, lon, gs and track, whose CURRENT cell is
  not already an alarm cell.
- Step along the great circle every cfg.warn_step_s up to cfg.warn_horizon_s
  (geo.destination_point with dist = gs_kt * 1.852 * t_hours).
- First step inside an alarm cell -> one alert. De-duplicate per (hex, cell)
  across ticks; drop it when the aircraft enters the cell or the cell clears.
- `injected` = True when the alarm cell's badness is only from simulated
  attacks (CellStat.n_injected == CellStat.n_bad), so the UI can badge it.
Tests: an aircraft 100 km west of a jammed cell heading east at 400 kt gets
eta ~ 8 min; the same aircraft heading west gets nothing.
"""
from __future__ import annotations

from app.config import DetectionConfig
from app.records import Record


def early_warnings(latest: dict[str, Record], alarm_cells: dict[str, str], cfg: DetectionConfig, now: float) -> list[dict]:
    # TODO: implement per the contract above.
    return []
