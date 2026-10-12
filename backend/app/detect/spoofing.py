"""Spoofing detector (HANDOVER §6.2): per-aircraft red flags.

Jamming makes an aircraft *know* it is lost (its GPS scores drop). Spoofing
fools it: the scores can look perfect while the position is wrong. So this
module looks for physical impossibilities instead of low scores.

    flag_aircraft(records, cfg) -> {hex: [reason codes]}
    spoofed_cells(flags, records, cfg) -> {h3 cell: number of flagged aircraft}

Reason codes (every number lives in DetectionConfig):
1. "impossible_jump": consecutive positions of one aircraft imply more than
   cfg.jump_speed_kt over more than cfg.jump_min_km. Pairs closer than
   cfg.jump_min_dt_s are skipped: two sources can report the same aircraft
   about a second apart with slightly different positions.
   Feed-glitch guards (12 Oct 01:25 IST: adsb.fi froze for 30 s, served stale
   positions, then five aircraft across North India "jumped" 10-14 km at once):
   no flag if the jump's start position had barely moved since the fix before
   it although the aircraft reported flying (cfg.spoof_frozen_*), or if at least
   cfg.spoof_mass_jump_min aircraft jump in the same poll.
2. "alt_offset_outlier": GPS altitude minus barometric altitude, compared
   with nearby aircraft. The difference is normally positive and grows with
   altitude (about +4% here, set by air temperature), so each aircraft's
   offset is compared as a FRACTION of its altitude against the median
   fraction of its peers. Never flag the raw difference: +1,500 ft at FL350
   is normal.
3. "colocation_cluster": several different aircraft reporting nearly the same
   spot at the same moment but thousands of feet apart vertically, which is
   what a spoofer pulling everyone to one fake position produces. The same
   aircraft must stay stacked on the same spot for cfg.spoof_cluster_min_polls
   polls: airway traffic in trail at FL330/350/390 passes one point within
   seconds (seen 12 Oct 00:40 IST) but moves on; a spoofer pins them (seen
   11 Oct 23:34 IST near Amritsar: FL195/370/390 on one point for over a minute).
4. "track_mismatch": the reported direction of travel disagrees with the
   direction between its last two positions.

Strong vs weak evidence (lesson from the first live run, 11 Oct 13:50: two
inland one-aircraft "spoofing" alarms with nothing behind them):
- STRONG ("impossible_jump", "colocation_cluster") can paint a cell purple alone.
- WEAK ("alt_offset_outlier", "track_mismatch") is shown on the aircraft, but a
  cell needs cfg.spoof_cell_min_flags such aircraft before it turns purple.
- Weak rules must also repeat: track mismatch twice, altitude outlier on at
  least two of the aircraft's last three readings.

Informational, NOT spoofing evidence: "recovery_jump" = an impossible jump
where either end had a bad GPS score. Seen on real data (FDX5384, 11 Oct):
during GPS loss the position froze, then leapt 13 km in 22 s when GPS came
back. That is the tail of jamming, so it must not paint a cell purple.
"feed_glitch" = an impossible jump explained by the data feed (see 1.); also info only.
SPOOF_REASONS lists the codes that do paint cells.
"""
from __future__ import annotations

from collections import defaultdict

from app.config import DetectionConfig
from app.detect.geo import angle_diff_deg, haversine_km, implied_speed_kt, initial_bearing_deg
from app.detect.jamming import cell_of
from app.detect.stats import median_mad
from app.records import Record

STRONG_REASONS = frozenset({"impossible_jump", "colocation_cluster"})
WEAK_REASONS = frozenset({"alt_offset_outlier", "track_mismatch"})
SPOOF_REASONS = STRONG_REASONS | WEAK_REASONS


def _weak_gps(r: Record, cfg: DetectionConfig) -> bool:
    return (r.nic is not None and r.nic <= cfg.nic_bad) or (r.nac_p is not None and r.nac_p <= cfg.nacp_bad)


def _usable(r: Record, cfg: DetectionConfig) -> bool:
    """Airborne, with a position that (by default, decision D9) came from the aircraft's own GPS:
    MLAT / TIS-B / ADS-R positions are computed by the ground network and jump on their own."""
    return not r.on_ground and r.lat is not None and r.lon is not None and (r.gps_sourced or not cfg.gps_sourced_only)


def _tracks(records: list[Record], cfg: DetectionConfig) -> dict[str, list[Record]]:
    """Positions per aircraft, time-ordered, exact repeats removed."""
    by_hex: dict[str, list[Record]] = defaultdict(list)
    for r in records:
        if _usable(r, cfg):
            by_hex[r.hex].append(r)
    for hex_id, rs in by_hex.items():
        rs.sort(key=lambda r: r.ts)
        out, seen = [], set()
        for r in rs:
            key = (r.lat, r.lon)
            if key not in seen:
                seen.add(key)
                out.append(r)
        by_hex[hex_id] = out
    return by_hex


def _frozen(before: Record | None, start: Record, cfg: DetectionConfig) -> bool:
    """The jump's start position had barely moved since the fix before it, although the
    aircraft reports flying: the feed froze and served a stale position, so the "jump" is
    the feed catching up. A spoofer pinning an aircraft to a point is different: its
    reported ground speed is low too, so this stays False and the jump is still flagged."""
    if before is None:
        return False
    gs = start.gs if start.gs is not None else before.gs
    dt = start.ts - before.ts
    if gs is None or gs < cfg.spoof_frozen_min_gs_kt or dt <= 0:
        return False
    moved_kt = implied_speed_kt(haversine_km(before.lat, before.lon, start.lat, start.lon), dt)
    return moved_kt < cfg.spoof_frozen_speed_frac * gs


def _jump_and_track(tracks: dict[str, list[Record]], cfg: DetectionConfig, flags: dict[str, set]) -> None:
    jumps: list[tuple[float, str]] = []  # (poll time of the landing fix, hex) of jumps that look like spoofing
    for hex_id, rs in tracks.items():
        before = prev = None
        mismatches = 0
        for r in rs:
            if prev is None:
                prev = r
                continue
            dt = r.ts - prev.ts
            if dt < cfg.jump_min_dt_s:
                continue  # too close in time to compare; keep the older anchor
            d = haversine_km(prev.lat, prev.lon, r.lat, r.lon)
            if d > cfg.jump_min_km and implied_speed_kt(d, dt) > cfg.jump_speed_kt:
                if _weak_gps(prev, cfg) or _weak_gps(r, cfg):
                    flags[hex_id].add("recovery_jump")
                elif _frozen(before, prev, cfg):
                    flags[hex_id].add("feed_glitch")
                else:
                    jumps.append((r.poll_ts, hex_id))
            elif (
                r.track is not None and prev.track is not None and r.gs is not None
                and r.gs > cfg.track_mismatch_min_gs_kt and dt <= cfg.track_check_max_dt_s and d >= cfg.track_check_min_km
                and angle_diff_deg(_mean_heading(prev.track, r.track),
                                   initial_bearing_deg(prev.lat, prev.lon, r.lat, r.lon)) > cfg.track_mismatch_deg
            ):
                mismatches += 1
                if mismatches >= cfg.track_mismatch_min_count:
                    flags[hex_id].add("track_mismatch")
            before, prev = prev, r
    # Many different aircraft "jumping" in the same poll is the feed, not a spoofer.
    for t, hex_id in jumps:
        same_poll = {h for t2, h in jumps if abs(t2 - t) <= cfg.spoof_mass_jump_window_s}
        flags[hex_id].add("feed_glitch" if len(same_poll) >= cfg.spoof_mass_jump_min else "impossible_jump")


def _mean_heading(a: float, b: float) -> float:
    """Average of two headings along the short way round (350 and 10 -> 0)."""
    d = ((b - a + 540.0) % 360.0) - 180.0
    return (a + d / 2.0) % 360.0


def _alt_offset(tracks: dict[str, list[Record]], cfg: DetectionConfig, flags: dict[str, set]) -> None:
    newest_ts = max((rs[-1].ts for rs in tracks.values() if rs), default=None)
    if newest_ts is None:
        return
    recent: dict[str, list[Record]] = {}
    for hex_id, rs in tracks.items():
        picked = []
        for r in reversed(rs):
            if r.ts < newest_ts - cfg.alt_peer_window_s or len(picked) == cfg.alt_recent_readings:
                break
            if r.alt_geom is not None and r.alt_baro is not None and r.alt_baro >= cfg.alt_min_alt_ft and r.gps_sourced:
                picked.append(r)
        if picked:
            recent[hex_id] = picked
    latest = {h: rs[0] for h, rs in recent.items()}
    for hex_id, r in latest.items():
        peers = [
            p.alt_geom / p.alt_baro - 1.0
            for other, p in latest.items()
            if other != hex_id and haversine_km(r.lat, r.lon, p.lat, p.lon) <= cfg.alt_peer_radius_km
        ]
        if len(peers) < cfg.alt_min_peers:
            continue
        med, mad = median_mad(peers)
        readings = recent[hex_id]
        outliers = sum(
            1 for x in readings
            if abs((x.alt_geom - x.alt_baro) - med * x.alt_baro) > max(cfg.alt_abs_ft, cfg.alt_mad_k * mad * x.alt_baro)
        )
        if outliers >= min(cfg.alt_outlier_min_count, len(readings)):
            flags[hex_id].add("alt_offset_outlier")


def _clusters(tracks: dict[str, list[Record]], cfg: DetectionConfig, flags: dict[str, set]) -> None:
    newest_ts = max((rs[-1].ts for rs in tracks.values() if rs), default=None)
    if newest_ts is None:
        return
    recent = [r for rs in tracks.values() for r in rs if r.ts >= newest_ts - cfg.cluster_lookback_s and r.alt_baro is not None]
    recent.sort(key=lambda r: r.ts)
    sightings: dict[frozenset, list[tuple[float, float, float]]] = defaultdict(list)  # aircraft set -> (ts, lat, lon)
    for i, a in enumerate(recent):
        group = {a.hex: a}
        for b in recent[i + 1:]:
            if b.ts - a.ts > cfg.cluster_dt_s:
                break
            if b.hex not in group and haversine_km(a.lat, a.lon, b.lat, b.lon) <= cfg.cluster_radius_km:
                group[b.hex] = b
        if len(group) >= cfg.cluster_min_aircraft:
            alts = [r.alt_baro for r in group.values()]
            if max(alts) - min(alts) > cfg.cluster_alt_spread_ft:
                sightings[frozenset(group)].append((a.ts, a.lat, a.lon))
    for hexes, seen in sightings.items():
        if _pinned_polls(seen, cfg) >= cfg.spoof_cluster_min_polls:
            for hex_id in hexes:
                flags[hex_id].add("colocation_cluster")


def _pinned_polls(seen: list[tuple[float, float, float]], cfg: DetectionConfig) -> int:
    """Separate polls (>= cluster_dt_s apart) at which the same aircraft were stacked on the
    same spot (within cluster_radius_km of the first sighting). A spoofer pins aircraft to one
    point; airway traffic stacked at different levels passes a point once and moves on."""
    seen = sorted(seen)
    t0, lat0, lon0 = seen[0]
    polls, last = 1, t0
    for t, lat, lon in seen[1:]:
        if t - last >= cfg.cluster_dt_s and haversine_km(lat0, lon0, lat, lon) <= cfg.cluster_radius_km:
            polls, last = polls + 1, t
    return polls


def flag_aircraft(records: list[Record], cfg: DetectionConfig) -> dict[str, list[str]]:
    tracks = _tracks(records, cfg)
    flags: dict[str, set] = defaultdict(set)
    _jump_and_track(tracks, cfg, flags)
    _alt_offset(tracks, cfg, flags)
    _clusters(tracks, cfg, flags)
    return {h: sorted(v) for h, v in flags.items() if v}


def flagged_by_cell(flags: dict[str, list[str]], records: list[Record], cfg: DetectionConfig) -> dict[str, list[str]]:
    """Aircraft with spoofing evidence, grouped by the cell of their newest position."""
    spoofed = {h for h, reasons in flags.items() if SPOOF_REASONS.intersection(reasons)}
    if not spoofed:
        return {}
    newest: dict[str, Record] = {}
    for r in records:
        if r.hex in spoofed and _usable(r, cfg) and (r.hex not in newest or r.ts > newest[r.hex].ts):
            newest[r.hex] = r
    out: dict[str, list[str]] = defaultdict(list)
    for r in newest.values():
        cell = cell_of(r, cfg.h3_res)
        if cell:
            out[cell].append(r.hex)
    return dict(out)


def spoofed_cells(flags: dict[str, list[str]], records: list[Record], cfg: DetectionConfig) -> dict[str, int]:
    """Cells that turn purple: >= 1 aircraft with strong evidence, or >= cfg.spoof_cell_min_flags with weak."""
    out = {}
    for cell, hexes in flagged_by_cell(flags, records, cfg).items():
        strong = sum(1 for h in hexes if STRONG_REASONS.intersection(flags[h]))
        if strong >= 1 or len(hexes) - strong >= cfg.spoof_cell_min_flags:
            out[cell] = len(hexes)
    return out
