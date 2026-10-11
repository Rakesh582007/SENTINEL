#!/usr/bin/env python3
"""GPS Attack Watch - standalone ADS-B recorder (Python standard library only).

Start it as early as possible and leave it running until the hackathon begins.
No `pip install` needed.

    python backend/scripts/record.py --once          # ~10 s connectivity check, then exit
    python backend/scripts/record.py                 # record north_india until Ctrl+C
    python backend/scripts/record.py --region all_india
    python backend/scripts/record.py --points "31.6,74.9,250;28.6,77.2,150"

(Windows: use `py` instead of `python` if `python` is not found.)

Every sweep asks each source (adsb.fi, adsb.lol) about each query circle and
appends the raw answers to data/recordings/ (format: backend/app/ingest/recording.py).
It only downloads public aggregated data. It never transmits any radio signal.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.ingest.recording import append_line, make_line, new_run_id  # noqa: E402
from app.ingest.sources import DEFAULT_SOURCES, SOURCE_EVERY_N_SWEEPS, SOURCES, USER_AGENT, build_url, due, fetch_json  # noqa: E402
from app.regions import DEFAULT_REGION, REGIONS, SWEEP_INTERVAL_S, get_region, parse_points  # noqa: E402

LOW_NACP = 7  # same starting threshold as config.DetectionConfig.nacp_bad; only used for the console summary


def keep_awake() -> str:
    """Ask Windows not to sleep while this process runs (the screen may still turn off)."""
    if sys.platform != "win32":
        return "not Windows: disable sleep in your OS settings"
    try:
        import ctypes

        es_continuous, es_system_required = 0x80000000, 0x00000001
        ok = ctypes.windll.kernel32.SetThreadExecutionState(es_continuous | es_system_required)
        return "sleep blocked while recording" if ok else "could not block sleep"
    except Exception as e:  # pragma: no cover - Windows only
        return f"could not block sleep ({e})"


def summarize(responses: list[dict | None]) -> dict:
    """Merge one point's answers from all sources by hex; count what matters."""
    seen: dict[str, dict] = {}
    for resp in responses:
        for ac in (resp or {}).get("ac") or []:
            hex_id = str(ac.get("hex", "")).lower()
            if hex_id:
                seen.setdefault(hex_id, ac)
    airborne = [a for a in seen.values() if a.get("alt_baro") != "ground"]
    low = sum(1 for a in airborne if isinstance(a.get("nac_p"), int) and not isinstance(a.get("nac_p"), bool) and a["nac_p"] <= LOW_NACP)
    no_pos = sum(1 for a in airborne if not isinstance(a.get("lat"), (int, float)))
    return {"union": len(seen), "airborne": len(airborne), "low_nacp": low, "no_pos": no_pos}


def ist(ts: float) -> str:
    return time.strftime("%H:%M:%S", time.gmtime(ts + 5.5 * 3600))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", default=DEFAULT_REGION, choices=sorted(REGIONS))
    ap.add_argument("--points", help='custom circles "lat,lon,radius_nm;..." (overrides --region)')
    ap.add_argument("--sources", default=",".join(DEFAULT_SOURCES), help=f"comma list from {sorted(SOURCES)}")
    ap.add_argument("--interval", type=float, help="seconds between sweep starts (default depends on region)")
    ap.add_argument("--spacing", type=float, default=1.1, help="seconds between consecutive requests")
    ap.add_argument("--out", default=str(REPO_ROOT / "data" / "recordings"))
    ap.add_argument("--hours", type=float, help="stop after this many hours")
    ap.add_argument("--once", action="store_true", help="one sweep, print the result, exit")
    args = ap.parse_args()

    points = parse_points(args.points) if args.points else get_region(args.region)
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    for s in sources:
        if s not in SOURCES:
            ap.error(f"unknown source {s!r}")
    interval = args.interval or SWEEP_INTERVAL_S.get(args.region, 10.0)
    out = Path(args.out)
    run_id = new_run_id()
    deadline = time.time() + args.hours * 3600 if args.hours else None

    print(f"GPS Attack Watch recorder | run {run_id} | {len(points)} circle(s) x {len(sources)} source(s) every {interval:.0f}s")
    print(f"  circles: {', '.join(f'{p.name}({p.lat},{p.lon},{p.radius_nm}NM)' for p in points)}")
    print(f"  cadence: {', '.join(f'{s} every {SOURCE_EVERY_N_SWEEPS.get(s, 1)} sweep(s)' for s in sources)}")
    print(f"  output:  {out}")
    print(f"  power:   {keep_awake()}  (keep the charger in; set lid-close to 'Do nothing')")
    print("  receive-only: downloads public aggregated ADS-B data; transmits nothing.\n")

    cooldown_until = {s: 0.0 for s in sources}
    fail_streak = {s: 0 for s in sources}
    ok_count = {s: 0 for s in sources}
    req_count = {s: 0 for s in sources}
    lines = bytes_written = sweeps = 0
    path: Path | None = None
    started = time.time()

    try:
        while True:
            sweep_start = time.time()
            sweeps += 1
            parts = []
            for point in points:
                answers = []
                for source in sources:
                    if time.time() < cooldown_until[source] or not due(source, sweeps):
                        continue
                    status, data, err, ms = fetch_json(build_url(source, point), user_agent=USER_AGENT)
                    poll_ts = time.time()
                    req_count[source] += 1
                    line = make_line(poll_ts, source, point.as_dict(), status, ms, err, data)
                    path = append_line(out, line, run_id)
                    lines += 1
                    bytes_written = sum(p.stat().st_size for p in out.glob(f"rec_*_{run_id}.jsonl.gz"))
                    if data is not None and status == 200:
                        ok_count[source] += 1
                        fail_streak[source] = 0
                        answers.append(data)
                    else:
                        fail_streak[source] += 1
                        if status == 429:
                            cooldown_until[source] = time.time() + 120
                        elif fail_streak[source] >= 3:
                            cooldown_until[source] = time.time() + min(600, 30 * 2 ** (fail_streak[source] - 3))
                        print(f"  ! {source} {point.name}: {err} (streak {fail_streak[source]})", file=sys.stderr)
                    time.sleep(args.spacing)
                s = summarize(answers)
                parts.append(f"{point.name} {s['union']:3d}ac low{s['low_nacp']} nopos{s['no_pos']}")
            mb = bytes_written / 1e6
            print(f"{ist(sweep_start)} IST  #{sweeps:<5d} " + " | ".join(parts) + f" | {mb:.1f} MB")

            if args.once:
                rate = ", ".join(f"{s} {ok_count[s]}/{req_count[s]} ok" for s in sources)
                print(f"\nOne sweep done ({rate}). Last file: {path}")
                print("If both sources say ok, run again without --once and leave it running.")
                return 0 if any(ok_count.values()) else 1
            if deadline and time.time() > deadline:
                break
            time.sleep(max(0.0, interval - (time.time() - sweep_start)))
    except KeyboardInterrupt:
        pass

    hours = (time.time() - started) / 3600
    rate = ", ".join(f"{s} {ok_count[s]}/{req_count[s]} ok" for s in sources)
    print(f"\nStopped after {hours:.2f} h, {sweeps} sweeps, {lines} lines, {bytes_written / 1e6:.1f} MB ({rate}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
