"""Spoofing detector (HANDOVER §6.2): per-aircraft red flags.  STATUS: TODO

Jamming makes an aircraft *know* it is lost (scores drop). Spoofing fools it:
its scores can look perfect while its position is wrong. So this module looks
for physical impossibilities instead of low scores.

Contract (already wired into runtime.compute_tick, which calls both functions
every tick and paints flagged cells purple):

    flag_aircraft(records, cfg) -> {hex: [reason codes]}
    spoofed_cells(flags, records, cfg) -> {h3 cell: number of flagged aircraft}

Reason codes and rules (every number is in DetectionConfig):
1. "impossible_jump": consecutive positions of the same hex imply
   > cfg.jump_speed_kt AND are > cfg.jump_min_km apart. Sort each aircraft's
   records by ts first, drop exact (lat, lon) repeats, and skip pairs closer
   than cfg.jump_min_dt_s in time (two sources can report the same aircraft
   ~1 s apart with slightly different positions). Use geo.haversine_km and
   geo.implied_speed_kt.
2. "alt_offset_outlier": off = alt_geom - alt_baro. Peers = other airborne
   aircraft within cfg.alt_peer_radius_km over the last cfg.alt_peer_window_s,
   need >= cfg.alt_min_peers. Flag if |off - median| > max(cfg.alt_abs_ft,
   cfg.alt_mad_k * MAD) (stats.median_mad). NEVER flag the raw difference:
   +1,500 ft is normal (temperature), measured on real data.
3. "colocation_cluster": >= cfg.cluster_min_aircraft distinct airborne hexes
   within cfg.cluster_radius_km of each other within cfg.cluster_dt_s, with an
   altitude spread > cfg.cluster_alt_spread_ft.
4. "track_mismatch" (optional): reported track vs bearing between consecutive
   positions differs > cfg.track_mismatch_deg while gs > cfg.track_mismatch_min_gs_kt
   (geo.initial_bearing_deg, geo.angle_diff_deg).

Only use records with r.lat/r.lon (not last_lat) and r.airborne.
Tests to write first (tests/test_spoofing.py): a 25 km jump in 10 s is
flagged; a normal 10 s step at 450 kt is not; a +1,550 ft offset among
peers at +1,500 ft is not; a -2,500 ft offset among them is.
"""
from __future__ import annotations

from app.config import DetectionConfig
from app.records import Record


def flag_aircraft(records: list[Record], cfg: DetectionConfig) -> dict[str, list[str]]:
    # TODO: implement rules 1-2 first (jump + altitude offset), cluster later.
    return {}


def spoofed_cells(flags: dict[str, list[str]], records: list[Record], cfg: DetectionConfig) -> dict[str, int]:
    """Map flagged aircraft to the H3 cell of their latest position (cfg.h3_res)."""
    # TODO: use jamming.cell_of(record, cfg.h3_res) on each flagged aircraft's newest record.
    return {}
