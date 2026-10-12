"""Export data/sample as compact normalized records for the standalone web build.

The standalone build (npm run dev:standalone / build:standalone) replays this
file through a browser copy of the detectors, so the UI can be shown without
the Python backend. Records go through the real backend normalizer, so the
browser sees exactly what the detectors see.

    python web/scripts/export_sample.py            # from the repo root
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from app.ingest.normalize import normalize_line  # noqa: E402
from app.ingest.recording import iter_recording, list_recordings  # noqa: E402

OUT = REPO / "web" / "src" / "standalone" / "sample-records.json.gz"
FIELDS = ["hex", "src", "flight", "age_s", "lat", "lon", "last_lat", "last_lon", "alt_baro", "alt_geom", "on_ground",
          "gs", "track", "nic", "nac_p", "type", "seen", "seen_pos", "gps_ok_before_rel", "gps_ok_lat", "gps_ok_lon"]


def main() -> None:
    files = list_recordings(REPO / "data" / "sample")
    tables: dict[str, dict[str, int]] = {"hex": {}, "flight": {}, "src": {}, "type": {}}

    def idx(table: str, value):
        if value is None:
            return -1
        t = tables[table]
        if value not in t:
            t[value] = len(t)
        return t[value]

    def rnd(x, n=1):
        return None if x is None else round(x, n)

    frames = []
    for path in files:
        for line in iter_recording(path):
            recs = normalize_line(line)
            if not recs:
                continue
            poll = float(line["poll_ts"])
            frames.append([poll, [[
                idx("hex", r.hex), idx("src", r.source), idx("flight", r.flight), rnd(poll - r.ts),
                rnd(r.lat, 5), rnd(r.lon, 5), rnd(r.last_lat, 5), rnd(r.last_lon, 5),
                r.alt_baro, r.alt_geom, 1 if r.on_ground else 0, rnd(r.gs), rnd(r.track), r.nic, r.nac_p,
                idx("type", r.src_type), rnd(r.seen), rnd(r.seen_pos),
                rnd(r.gps_ok_before - poll) if r.gps_ok_before is not None else None,
                rnd(r.gps_ok_lat, 5), rnd(r.gps_ok_lon, 5),
            ] for r in recs]])
    frames.sort(key=lambda f: f[0])
    t0 = frames[0][0]
    doc = {
        "about": "Real ADS-B traffic recorded 11 Oct 2026 12:20-12:39 IST (region north_india) from adsb.fi and adsb.lol, "
                 "normalized by backend/app/ingest/normalize.py. Data credit: adsb.fi and adsb.lol contributors. "
                 "Non-commercial testing of this student project only.",
        "files": [p.name for p in files],
        "t0": t0,
        "fields": FIELDS,
        "tables": {k: list(v) for k, v in tables.items()},
        "frames": [[round(f[0] - t0, 3), f[1]] for f in frames],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(gzip.compress(json.dumps(doc, separators=(",", ":")).encode(), compresslevel=9, mtime=0))
    print(f"{len(frames)} frames, {sum(len(f[1]) for f in frames)} records, {len(tables['hex'])} aircraft -> {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
