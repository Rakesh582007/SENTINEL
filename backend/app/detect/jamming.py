"""Jamming detector (HANDOVER §6.1): share of aircraft with bad GPS per H3 cell.

The crowd idea: one aircraft with a weak GPS score proves nothing (old
avionics, a glitch); many different aircraft in the same cell going bad in
the same window means interference there.

Implemented. Spoofing, early warning, incidents and evaluation are in the
sibling modules and are still TODO.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

import h3

from app.config import DetectionConfig
from app.detect.stats import wilson_lower_bound
from app.records import Record

STATES = ("insufficient", "clear", "degraded", "jammed")  # "spoofing" is set by spoofing.py on top


@dataclass(slots=True)
class CellStat:
    h3: str
    n_aircraft: int
    n_bad: int
    frac_bad: float
    lower_bound: float
    state: str
    n_injected: int = 0  # bad aircraft whose badness came from a simulated attack
    bad_hexes: list[str] = field(default_factory=list)
    reasons: dict[str, int] = field(default_factory=dict)  # reason code -> aircraft count

    def to_props(self) -> dict:
        return {
            "h3": self.h3,
            "state": self.state,
            "n_aircraft": self.n_aircraft,
            "n_bad": self.n_bad,
            "frac_bad": round(self.frac_bad, 3),
            "lower_bound": round(self.lower_bound, 3),
            "n_injected": self.n_injected,
            "reasons": self.reasons,
        }


def eligible(r: Record, cfg: DetectionConfig) -> bool:
    """Airborne, and (by default) a position that came from the aircraft's own GPS."""
    if r.on_ground:
        return False
    return r.gps_sourced or not cfg.gps_sourced_only


def bad_reason(r: Record, cfg: DetectionConfig) -> str | None:
    """Why this record counts as 'bad GPS', or None if it looks healthy."""
    if r.gps_ok_before is not None:
        return "gps_lost_flag"  # readsb itself noticed this aircraft lost GPS
    if (
        r.lat is None
        and r.last_lat is not None
        and r.seen is not None
        and r.seen <= cfg.pos_loss_seen_max_s
        and r.seen_pos is not None
        and r.seen_pos >= cfg.pos_loss_seen_pos_min_s
    ):
        return "position_lost"  # still transmitting, but no position
    if r.nac_p is not None and r.nac_p <= cfg.nacp_bad:
        return "low_nacp"
    if r.nic is not None and r.nic <= cfg.nic_bad:
        return "low_nic"
    return None


def classify_state(n: int, k: int, frac: float, lower_bound: float, cfg: DetectionConfig) -> str:
    if n < cfg.min_aircraft:
        return "insufficient"
    if k >= cfg.jam_min_bad and lower_bound >= cfg.jam_lower_bound:
        return "jammed"
    if k >= 1 and frac >= cfg.degraded_frac:
        return "degraded"
    return "clear"


def cell_of(r: Record, res: int) -> str | None:
    pos = r.best_position()
    if pos is None:
        return None
    return h3.latlng_to_cell(pos[0], pos[1], res)


def classify_cells(records: Iterable[Record], cfg: DetectionConfig) -> dict[str, CellStat]:
    """Records from the detection window -> one CellStat per occupied cell.

    Counts unique aircraft (hex), not records. An aircraft is bad in a cell only
    if one of its records inside that cell was bad.
    """
    seen: dict[str, set[str]] = defaultdict(set)
    bad: dict[str, dict[str, str]] = defaultdict(dict)  # cell -> hex -> reason
    injected: dict[str, set[str]] = defaultdict(set)
    for r in records:
        if not eligible(r, cfg):
            continue
        cell = cell_of(r, cfg.h3_res)
        if cell is None:
            continue
        seen[cell].add(r.hex)
        reason = bad_reason(r, cfg)
        if reason:
            bad[cell].setdefault(r.hex, reason)
            if r.injected:
                injected[cell].add(r.hex)

    out: dict[str, CellStat] = {}
    for cell, hexes in seen.items():
        n = len(hexes)
        bad_here = bad.get(cell, {})
        k = len(bad_here)
        frac = k / n
        lb = wilson_lower_bound(k, n)
        reasons: dict[str, int] = defaultdict(int)
        for why in bad_here.values():
            reasons[why] += 1
        out[cell] = CellStat(
            h3=cell,
            n_aircraft=n,
            n_bad=k,
            frac_bad=frac,
            lower_bound=lb,
            state=classify_state(n, k, frac, lb, cfg),
            n_injected=len(injected.get(cell, ())),
            bad_hexes=sorted(bad_here),
            reasons=dict(reasons),
        )
    return out


def cell_polygon(cell: str) -> list[list[float]]:
    """GeoJSON ring ([lon, lat] pairs, closed) for an H3 cell."""
    ring = [[round(lng, 5), round(lat, 5)] for lat, lng in h3.cell_to_boundary(cell)]
    ring.append(ring[0])
    return ring


def to_geojson(cells: dict[str, CellStat]) -> dict:
    """FeatureCollection the frontend can draw directly (no H3 maths in the browser)."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": c.h3,
                "geometry": {"type": "Polygon", "coordinates": [cell_polygon(c.h3)]},
                "properties": c.to_props(),
            }
            for c in cells.values()
        ],
    }
