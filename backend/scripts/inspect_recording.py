#!/usr/bin/env python3
"""Coverage report for recordings: is there enough traffic to detect anything, and where?

    python backend/scripts/inspect_recording.py               # everything in data/recordings
    python backend/scripts/inspect_recording.py --last 3      # newest 3 UTC hours only
    python backend/scripts/inspect_recording.py --dir PATH

Needs `pip install -r backend/requirements.txt` (uses the real jamming detector).
Run it tonight after a few hours of recording: the "busiest cells" list tells you
where a judge's simulated jammer will visibly turn cells red.
"""
from __future__ import annotations

import argparse
import bisect
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

import h3  # noqa: E402

from app.config import DetectionConfig  # noqa: E402
from app.detect.jamming import bad_reason, classify_cells  # noqa: E402
from app.ingest.normalize import normalize_line  # noqa: E402
from app.ingest.recording import iter_recording, list_recordings  # noqa: E402
from app.ingest.replay import stamp_of  # noqa: E402

IST = 5.5 * 3600
AREA_KM2 = {2: 86_800, 3: 12_400, 4: 1_770}


def ist(ts: float, fmt: str = "%d %b %H:%M") -> str:
    return time.strftime(fmt, time.gmtime(ts + IST))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=str(REPO_ROOT / "data" / "recordings"))
    ap.add_argument("--last", type=int, help="only the newest N UTC hours")
    ap.add_argument("--window-min", type=float, default=20.0)
    ap.add_argument("--step-min", type=float, default=5.0)
    args = ap.parse_args()

    files = list_recordings(Path(args.dir))
    if args.last:
        keep = set(sorted({stamp_of(p) for p in files})[-args.last:])
        files = [p for p in files if stamp_of(p) in keep]
    if not files:
        print(f"No recordings in {args.dir}. Start backend/scripts/record.py first.")
        return 1

    per_answer: dict[tuple[str, str], list[int]] = defaultdict(list)
    requests: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    union: dict[tuple[str, int], set] = defaultdict(set)
    hourly: dict[tuple[str, str], list[int]] = defaultdict(list)
    recs = []
    for f in files:
        for line in iter_recording(f):
            key = (line.get("point", {}).get("name", "?"), line.get("source", "?"))
            requests[key][0] += 1
            got = normalize_line(line)
            if line.get("http") == 200:
                requests[key][1] += 1
                per_answer[key].append(len(got))
            for r in got:
                union[(key[0], int(r.poll_ts // 30))].add(r.hex)
            recs.extend(got)
    if not recs:
        print("Recordings contain no aircraft.")
        return 1
    for (point, bucket), hexes in union.items():
        hourly[(point, ist(bucket * 30, "%H"))].append(len(hexes))

    recs.sort(key=lambda r: r.ts)
    times = [r.ts for r in recs]
    t0, t1 = times[0], times[-1]
    print(f"Recordings: {len(files)} file(s), {ist(t0)} to {ist(t1, '%H:%M')} IST ({(t1 - t0) / 3600:.1f} h), {len(recs):,} aircraft records\n")

    print("Per circle and source        mean aircraft/answer   answers ok")
    for (point, source), counts in sorted(per_answer.items()):
        req, ok = requests[(point, source)]
        print(f"  {point:10s} {source:15s} {statistics.mean(counts):10.1f}            {ok}/{req}")

    print("\nUnique aircraft per circle (both sources merged, per 30 s):")
    points = sorted({p for p, _ in union})
    for point in points:
        vals = [len(h) for (p, _), h in union.items() if p == point]
        print(f"  {point:10s} median {statistics.median(vals):5.1f}   min {min(vals):3d}   max {max(vals):3d}")

    hours = sorted({h for _, h in hourly})
    if len(hours) > 1:
        print("\nBy IST hour (median unique aircraft per 30 s):")
        print("  hour  " + "".join(f"{p:>10s}" for p in points))
        for hr in hours:
            row = [statistics.median(hourly[(p, hr)]) if hourly.get((p, hr)) else float("nan") for p in points]
            print(f"  {hr}:00 " + "".join(f"{v:10.1f}" for v in row))

    cfg = DetectionConfig()
    airborne = [r for r in recs if not r.on_ground]
    reasons: dict[str, set] = defaultdict(set)
    for r in airborne:
        why = bad_reason(r, cfg)
        if why:
            reasons[why].add(r.hex)
    n_ac = len({r.hex for r in airborne})
    print(f"\nGPS health over the whole recording: {n_ac} airborne aircraft seen")
    for why in ("low_nacp", "low_nic", "position_lost", "gps_lost_flag"):
        print(f"  {why:14s} {len(reasons.get(why, ())):4d} aircraft")

    window = args.window_min * 60
    step = args.step_min * 60
    print(f"\nDetectability: {args.window_min:.0f}-min windows every {args.step_min:.0f} min, a cell needs >= {cfg.min_aircraft} aircraft")
    busiest: dict[str, list[int]] = defaultdict(list)
    for res in (3, 2):
        c = cfg.model_copy(update={"h3_res": res})
        occupied, usable, states_seen = [], [], defaultdict(int)
        t = t0 + min(window, max(0.0, t1 - t0))
        while t <= t1 + 1:
            lo, hi = bisect.bisect_left(times, t - window), bisect.bisect_right(times, t)
            cells = classify_cells(recs[lo:hi], c)
            occupied.append(len(cells))
            usable.append(sum(1 for x in cells.values() if x.state != "insufficient"))
            for x in cells.values():
                states_seen[x.state] += 1
                if res == 3:
                    busiest[x.h3].append(x.n_aircraft)
            t += step
        occ, use = statistics.median(occupied), statistics.median(usable)
        share = use / occ if occ else 0
        print(f"  res {res} (~{AREA_KM2[res]:,} km2 cells): median {occ:.0f} occupied, {use:.0f} detectable ({share:.0%})"
              f"   states seen: {dict(states_seen)}")

    print("\nBusiest res-3 cells (put the demo jammer here; median aircraft per window):")
    top = sorted(busiest.items(), key=lambda kv: statistics.median(kv[1]), reverse=True)[:8]
    for cell, ns in top:
        lat, lon = h3.cell_to_latlng(cell)
        print(f"  {lat:6.2f}, {lon:6.2f}   median {statistics.median(ns):4.1f}   max {max(ns):3d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
