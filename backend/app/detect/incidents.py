"""Incidents and the approximate jammer area (HANDOVER §6.4).

An incident is "something has been wrong in this area since HH:MM". It groups
neighbouring alarm cells, collects the affected aircraft, estimates where a
jammer might be, and is what the PDF report describes.

    tracker = IncidentTracker(db=None)
    tracker.update(cells, window_records, cfg, now, spoof_flags)   # every tick
    tracker.summary()   -> short dicts for the tick payload
    tracker.get(id)     -> full dict incl. aircraft (for the PDF)
    tracker.reset()     -> replay seek / mode switch

Rules:
- Open when a cell enters "jammed" or "spoofing". An alarm cell next to an
  open incident of the same kind (h3.grid_disk(cell, 1)) joins that incident.
- Close after cfg.incident_close_s with none of its cells in alarm.
- Jammer area (jamming only), per affected aircraft: readsb's last-good GPS
  position (gpsOkLat/Lon) if known, else its first bad position. Centre =
  mean of those points; radius = the cfg.jammer_radius_pct percentile of
  their distances from the centre, at least cfg.jammer_min_radius_km.
  Always "approximate area for investigation", never a pinpoint.
- Every change is upserted into SQLite so the report survives a restart.
"""
from __future__ import annotations

import itertools
import json
import logging

import h3

from app.config import DetectionConfig
from app.detect.geo import haversine_km
from app.detect.jamming import CellStat, bad_reason, cell_of
from app.detect.stats import percentile
from app.records import Record

log = logging.getLogger("gaw.incidents")

KIND_OF_STATE = {"jammed": "jamming", "spoofing": "spoofing"}


class IncidentTracker:
    def __init__(self, db=None) -> None:
        self.db = db
        self._incidents: dict[str, dict] = {}
        self._seq = itertools.count(1)

    # ------------------------------------------------------------------ main
    def update(self, cells: dict[str, CellStat], records: list[Record], cfg: DetectionConfig, now: float,
               spoof_flags: dict[str, list[str]] | None = None) -> None:
        alarm = {c: s for c, s in cells.items() if s.state in KIND_OF_STATE}
        changed: set[str] = set()

        for cell, stat in alarm.items():
            kind = KIND_OF_STATE[stat.state]
            inc = self._find_open(cell, kind)
            if inc is None:
                inc = self._open(cell, kind, now)
            if cell not in inc["cells"]:
                inc["cells"].append(cell)
            inc["last_alarm_ts"] = now
            inc["max_frac_bad"] = max(inc["max_frac_bad"], round(stat.frac_bad, 3))
            inc["peak_aircraft"] = max(inc["peak_aircraft"], stat.n_aircraft)
            changed.add(inc["id"])

        if changed:
            self._collect_aircraft(records, cfg, spoof_flags or {}, changed)

        for inc in self._incidents.values():
            if inc["closed_ts"] is None and inc["id"] not in changed and now - inc["last_alarm_ts"] > cfg.incident_close_s:
                inc["closed_ts"] = now
                changed.add(inc["id"])
            if inc["id"] in changed and inc["kind"] == "jamming":
                self._estimate_area(inc, cfg)
        for inc_id in changed:
            self._save(self._incidents[inc_id])

    # ------------------------------------------------------------------ parts
    def _find_open(self, cell: str, kind: str) -> dict | None:
        near = set(h3.grid_disk(cell, 1))
        for inc in self._incidents.values():
            if inc["closed_ts"] is None and inc["kind"] == kind and near.intersection(inc["cells"]):
                return inc
        return None

    def _open(self, cell: str, kind: str, now: float) -> dict:
        inc_id = f"inc-{next(self._seq)}"
        inc = {"id": inc_id, "kind": kind, "opened_ts": now, "closed_ts": None, "last_alarm_ts": now,
               "cells": [cell], "aircraft": {}, "max_frac_bad": 0.0, "peak_aircraft": 0,
               "est_lat": None, "est_lon": None, "est_radius_km": None}
        self._incidents[inc_id] = inc
        log.info("incident %s opened (%s) at %s", inc_id, kind, cell)
        return inc

    def _collect_aircraft(self, records: list[Record], cfg: DetectionConfig, spoof_flags: dict[str, list[str]], ids: set[str]) -> None:
        open_incs = [self._incidents[i] for i in ids]
        injected_by_hex = {r.hex: r.injected for r in records if r.injected}
        for r in sorted(records, key=lambda r: r.ts):
            cell = cell_of(r, cfg.h3_res)
            if cell is None:
                continue
            for inc in open_incs:
                if cell not in inc["cells"] or r.hex in inc["aircraft"]:
                    continue
                if inc["kind"] == "jamming":
                    why = bad_reason(r, cfg)
                else:
                    reasons = spoof_flags.get(r.hex)
                    why = ",".join(reasons) if reasons else None
                if not why:
                    continue
                pos = r.best_position()
                inc["aircraft"][r.hex] = {
                    "hex": r.hex, "flight": r.flight, "first_bad_ts": r.ts, "reason": why,
                    "first_bad_pos": [round(pos[0], 4), round(pos[1], 4)] if pos else None,
                    "last_good_pos": [r.gps_ok_lat, r.gps_ok_lon] if r.gps_ok_lat is not None else None,
                    "alt_baro": r.alt_baro, "injected": r.injected or injected_by_hex.get(r.hex),
                }

    def _estimate_area(self, inc: dict, cfg: DetectionConfig) -> None:
        pts = [a["last_good_pos"] or a["first_bad_pos"] for a in inc["aircraft"].values()]
        pts = [p for p in pts if p and p[0] is not None]
        if not pts:
            lat_lons = [h3.cell_to_latlng(c) for c in inc["cells"]]
            pts = [list(p) for p in lat_lons]
        lat = sum(p[0] for p in pts) / len(pts)
        lon = sum(p[1] for p in pts) / len(pts)
        dists = [haversine_km(lat, lon, p[0], p[1]) for p in pts]
        radius = max(cfg.jammer_min_radius_km, percentile(dists, cfg.jammer_radius_pct) if len(dists) > 1 else 0.0)
        inc.update(est_lat=round(lat, 4), est_lon=round(lon, 4), est_radius_km=round(radius, 1))

    def _save(self, inc: dict) -> None:
        if self.db is None:
            return
        try:
            with self.db:
                self.db.execute(
                    "INSERT OR REPLACE INTO incidents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (inc["id"], inc["kind"], inc["opened_ts"], inc["closed_ts"], json.dumps(inc["cells"]),
                     json.dumps(list(inc["aircraft"].values())), inc["est_lat"], inc["est_lon"],
                     inc["est_radius_km"], inc["max_frac_bad"], int(self._injected(inc))),
                )
        except Exception:
            log.exception("could not save incident %s", inc["id"])

    # ------------------------------------------------------------------ views
    @staticmethod
    def _injected(inc: dict) -> bool:
        """ANY simulated aircraft makes the incident a test (one real low-NACp aircraft in the
        area must not make a simulated attack look real)."""
        return any(a["injected"] for a in inc["aircraft"].values())

    @staticmethod
    def _mixed(inc: dict) -> bool:
        """Simulated and real (non-injected) affected aircraft in the same incident."""
        ac = inc["aircraft"].values()
        return any(a["injected"] for a in ac) and any(not a["injected"] for a in ac)

    def _view(self, inc: dict, full: bool) -> dict:
        out = {k: v for k, v in inc.items() if k != "aircraft"}
        out["n_aircraft"] = len(inc["aircraft"])
        out["injected"] = self._injected(inc)
        out["mixed"] = self._mixed(inc)
        out["open"] = inc["closed_ts"] is None
        if full:
            out["aircraft"] = sorted(inc["aircraft"].values(), key=lambda a: a["first_bad_ts"])
        return out

    def summary(self) -> list[dict]:
        """Newest first. Creation order, not opened_ts: after a replay jumps back in time, an
        incident opened after the jump has an earlier timestamp but is still the newest."""
        return [self._view(i, False) for i in reversed(list(self._incidents.values()))]

    def get(self, incident_id: str) -> dict | None:
        inc = self._incidents.get(incident_id)
        return self._view(inc, True) if inc else None

    def close_all(self, now: float) -> None:
        """Replay seek or loop: the history belongs to the old time, so end every open incident
        there, but keep them (the list and the PDFs survive the jump)."""
        for inc in self._incidents.values():
            if inc["closed_ts"] is None:
                inc["closed_ts"] = max(now, inc["opened_ts"])
                self._save(inc)

    def reset(self) -> None:
        """Mode switch: a fresh experiment."""
        self._incidents.clear()
