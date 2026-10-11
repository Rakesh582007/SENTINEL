"""Turn raw API answers (or recording lines) into Records.

Stdlib only. Every gotcha below was either seen in real adsb.fi / adsb.lol
answers on 11 Oct 2026 or is documented in readsb's README-json.md:

- every field is optional (seen missing: gs, flight, alt_geom, alt_baro, nac_p)
- alt_baro is the string "ground" for aircraft on the ground
- track can be missing while calc_track is present
- `now` is milliseconds in the v2/v3 APIs, seconds in readsb's aircraft.json
- lat/lon vanish once the position is >60 s old; `lastPosition` then holds it
- Python treats True/False as ints, so booleans must never pass as numbers
- `type` says where the position came from; only adsb_* positions reflect the
  aircraft's own GPS (see records.GPS_SOURCED_TYPES)
- readsb's experimental gpsOkBefore / gpsOkLat / gpsOkLon appear when the
  aggregator itself saw an aircraft lose GPS. Seen live on 11 Oct 2026 12:32 IST:
  FDX5384 (B77L) at FL370 near 33.5N 72.9E, NIC 0 / NACp 0, gpsOkBefore set.
"""
from __future__ import annotations

from typing import Iterable

from app.records import Record


def num(x) -> float | None:
    """A finite float, or None. Rejects bools, strings and NaN."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    f = float(x)
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def as_int(x) -> int | None:
    f = num(x)
    return None if f is None else int(round(f))


def epoch_seconds(raw_now, fallback: float) -> float:
    """API `now` to unix seconds; ms values (>1e11) are divided by 1000."""
    f = num(raw_now)
    if f is None or f <= 0:
        return fallback
    return f / 1000.0 if f > 1e11 else f


def normalize_aircraft(ac: dict, poll_ts: float, source: str) -> Record | None:
    """One aircraft object -> Record. Returns None when there is no usable hex id."""
    if not isinstance(ac, dict):
        return None
    hex_id = ac.get("hex")
    if not isinstance(hex_id, str) or not hex_id.strip():
        return None
    hex_id = hex_id.strip().lower()

    alt_baro_raw = ac.get("alt_baro")
    on_ground = isinstance(alt_baro_raw, str) and alt_baro_raw.strip().lower() == "ground"
    alt_baro = None if on_ground else as_int(alt_baro_raw)

    lat, lon = num(ac.get("lat")), num(ac.get("lon"))
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        lat = lon = None
    seen = num(ac.get("seen"))
    seen_pos = num(ac.get("seen_pos"))

    last_lat = last_lon = None
    if lat is None:
        lp = ac.get("lastPosition")
        if isinstance(lp, dict):
            last_lat, last_lon = num(lp.get("lat")), num(lp.get("lon"))
            if last_lat is None or last_lon is None:
                last_lat = last_lon = None
            lp_seen = num(lp.get("seen_pos"))
            if lp_seen is not None:
                seen_pos = lp_seen

    track = num(ac.get("track"))
    if track is None:
        track = num(ac.get("calc_track"))

    flight_raw = ac.get("flight")
    flight = (flight_raw.strip() or None) if isinstance(flight_raw, str) else None

    src_type = ac.get("type") if isinstance(ac.get("type"), str) else None

    if lat is not None:
        age = seen_pos if seen_pos is not None else (seen or 0.0)
    else:
        age = seen or 0.0
    ts = poll_ts - max(0.0, age)

    return Record(
        ts=ts,
        poll_ts=poll_ts,
        hex=hex_id,
        source=source,
        flight=flight,
        lat=lat,
        lon=lon,
        last_lat=last_lat,
        last_lon=last_lon,
        alt_baro=alt_baro,
        alt_geom=as_int(ac.get("alt_geom")),
        on_ground=on_ground,
        gs=num(ac.get("gs")),
        track=track,
        nic=as_int(ac.get("nic")),
        nac_p=as_int(ac.get("nac_p")),
        version=as_int(ac.get("version")),
        src_type=src_type,
        seen=seen,
        seen_pos=seen_pos,
        gps_ok_before=epoch_or_none(ac.get("gpsOkBefore")),
        gps_ok_lat=num(ac.get("gpsOkLat")),
        gps_ok_lon=num(ac.get("gpsOkLon")),
    )


def epoch_or_none(x) -> float | None:
    f = num(x)
    if f is None or f <= 0:
        return None
    return f / 1000.0 if f > 1e11 else f


def normalize_response(resp: dict | None, source: str, poll_ts: float) -> list[Record]:
    """A whole API answer -> list of Records (aircraft without a hex are dropped)."""
    if not isinstance(resp, dict):
        return []
    aircraft = resp.get("ac")
    if aircraft is None:
        aircraft = resp.get("aircraft")  # readsb aircraft.json shape
    if not isinstance(aircraft, list):
        return []
    out = []
    for ac in aircraft:
        rec = normalize_aircraft(ac, poll_ts, source)
        if rec is not None:
            out.append(rec)
    return out


def normalize_line(line: dict) -> list[Record]:
    """A recording line (see ingest/recording.py) -> Records."""
    if not isinstance(line, dict) or line.get("http") != 200:
        return []
    poll_ts = num(line.get("poll_ts"))
    if poll_ts is None:
        return []
    return normalize_response(line.get("response"), str(line.get("source", "unknown")), poll_ts)


def merge_freshest(records: Iterable[Record]) -> dict[str, Record]:
    """One Record per hex: the freshest position wins; ties prefer a record that has nac_p."""
    best: dict[str, Record] = {}
    for r in records:
        cur = best.get(r.hex)
        if cur is None:
            best[r.hex] = r
            continue
        if r.has_position and not cur.has_position:
            best[r.hex] = r
        elif r.has_position == cur.has_position and (
            r.ts > cur.ts or (r.ts == cur.ts and cur.nac_p is None and r.nac_p is not None)
        ):
            best[r.hex] = r
    return best
