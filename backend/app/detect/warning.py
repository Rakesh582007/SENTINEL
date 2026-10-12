"""Early warning (HANDOVER §6.3): who is flying INTO trouble.

This is what turns a map into a safety tool: "IGO2317 enters a jammed area
in ~12 min".

    early_warnings(latest, alarm_cells, cfg, now, injected_cells=(), mixed_cells=()) -> list[dict]

    latest:         {hex: newest Record} for aircraft heard recently
    alarm_cells:    {h3 cell: "jammed" | "spoofing"}
    injected_cells: alarm cells with ANY simulated (injected) effect
    mixed_cells:    alarm cells with both simulated and real (non-injected) effects

Each airborne aircraft with a position, speed and track that is NOT already in
an alarm cell is stepped forward along a great circle every cfg.warn_step_s
up to cfg.warn_horizon_s. The first step inside an alarm cell gives one alert.
Alerts are recomputed every tick, so there is exactly one per (aircraft, cell)
and they disappear by themselves when the aircraft enters or the cell clears.
"""
from __future__ import annotations

import h3

from app.config import DetectionConfig
from app.detect.geo import KT_TO_KMH, destination_point
from app.records import Record

MIN_GS_KT = 60.0  # slower than this is taxiing, holding low, or a helicopter; projection is meaningless


def early_warnings(latest: dict[str, Record], alarm_cells: dict[str, str], cfg: DetectionConfig, now: float,
                   injected_cells: set[str] | frozenset = frozenset(),
                   mixed_cells: set[str] | frozenset = frozenset()) -> list[dict]:
    if not alarm_cells:
        return []
    res = h3.get_resolution(next(iter(alarm_cells)))
    alerts = []
    for r in latest.values():
        if r.on_ground or not r.has_position or r.gs is None or r.track is None or r.gs < MIN_GS_KT:
            continue
        if h3.latlng_to_cell(r.lat, r.lon, res) in alarm_cells:
            continue
        age = max(0.0, now - r.ts)
        path = [[round(r.lat, 4), round(r.lon, 4)]]
        for t in range(cfg.warn_step_s, cfg.warn_horizon_s + 1, cfg.warn_step_s):
            lat, lon = destination_point(r.lat, r.lon, r.track, r.gs * KT_TO_KMH * t / 3600.0)
            path.append([round(lat, 4), round(lon, 4)])
            cell = h3.latlng_to_cell(lat, lon, res)
            if cell not in alarm_cells:
                continue
            eta = max(0.0, t - age)
            state = alarm_cells[cell]
            what = "a GPS-jammed area" if state == "jammed" else "an area with suspected GPS spoofing"
            name = r.flight or r.hex.upper()
            alerts.append({
                "id": f"ew-{r.hex}-{cell}",
                "kind": "early_warning",
                "hex": r.hex,
                "flight": r.flight,
                "h3": cell,
                "cell_state": state,
                "eta_s": round(eta),
                "entry": [round(lat, 4), round(lon, 4)],
                "path": path,
                "injected": cell in injected_cells,
                "mixed": cell in mixed_cells,
                "severity": "high" if eta <= 300 else "medium",
                "message": f"{name} enters {what} in ~{max(1, round(eta / 60))} min. Prepare backup navigation.",
            })
            break
    alerts.sort(key=lambda a: a["eta_s"])
    return alerts
