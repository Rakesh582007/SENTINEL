"""Incidents and the approximate jammer area (HANDOVER §6.4).  STATUS: TODO

An incident is "something is wrong in this area since HH:MM": it groups
neighbouring alarm cells, collects the affected aircraft, estimates where a
jammer might be, and is what the PDF report describes.

Contract (runtime.compute_tick already calls update() and summary()):

    tracker = IncidentTracker()
    tracker.update(cells, window_records, cfg, now)   # every tick
    tracker.summary() -> [{"id", "kind", "opened_ts", "closed_ts", "cells",
                           "n_aircraft", "est_lat", "est_lon", "est_radius_km",
                           "max_frac_bad", "injected"}]
    tracker.get(id) -> full dict incl. aircraft list [{hex, flight, first_bad_ts, first_bad_pos}]
    tracker.reset()   # replay seek / mode switch

Rules:
- Open when a cell first becomes "jammed" or "spoofing"; merge neighbouring
  alarm cells (h3.grid_disk(cell, 1)) into the same open incident.
- Close after cfg.incident_close_s with none of its cells in alarm.
- Jammer area (jamming incidents only): each bad aircraft's FIRST bad position
  in the incident; centre = mean of those points; radius = the
  cfg.jammer_radius_pct percentile of distances to the centre, at least
  cfg.jammer_min_radius_km (stats.percentile, geo.haversine_km).
  Always label it "approximate area for investigation", never a pinpoint.
- Persist opened/closed incidents to the `incidents` table (db.py) so the PDF
  survives a restart.
"""
from __future__ import annotations

from app.config import DetectionConfig
from app.detect.jamming import CellStat
from app.records import Record


class IncidentTracker:
    def __init__(self) -> None:
        self._incidents: dict[str, dict] = {}

    def update(self, cells: dict[str, CellStat], records: list[Record], cfg: DetectionConfig, now: float) -> None:
        # TODO: implement per the contract above.
        return None

    def summary(self) -> list[dict]:
        return []

    def get(self, incident_id: str) -> dict | None:
        return self._incidents.get(incident_id)

    def reset(self) -> None:
        self._incidents.clear()
