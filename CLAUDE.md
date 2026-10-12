# CLAUDE.md — SENTINEL / GPS Attack Watch

Read this first, every session. The full spec is `docs/HANDOVER.md`: read the section for a module before changing it. Where this file and the handover disagree, **this file wins**; the decisions log below says why.

## What it is

A local web app (one laptop, no cloud) that detects GPS **jamming** and **spoofing** from public aircraft ADS-B data (adsb.fi + adsb.lol), warns flights heading into affected areas, and auto-files incident reports. Three sections: **Live Airspace**, **Attack Simulator** (judges inject attacks with sliders, on live or replayed data), **Ground Sentinel** (ESP32 + GPS box on the table). Team Ethicals, SEDHACKS'26; build day Mon 12 Oct 2026 08:00 IST. The demo runs in replay mode by default; live is a bonus.

## Ground rules (never break)

- **Receive-only.** Never transmit, or suggest transmitting, any RF signal. Attacks exist only as data injection, always tagged `Record.injected` and shown as "INJECTED TEST ATTACK".
- Never claim who is jamming. The jammer estimate is an "approximate area for investigation".
- Every threshold lives in `backend/app/config.py`. Runtime-tunable ones are in `DetectionConfig`; read them with `get_detection()` on every tick.
- All time logic uses `rt.clock.now()`, never `time.time()` (replay runs at up to 20x and seeks backwards). Exception: the Ground Sentinel, which is real hardware on the wall clock.
- Detectors read `rt.window` (memory). Never query SQLite inside the tick.
- The UI must credit adsb.fi and adsb.lol (adsb.fi terms: non-commercial use, credit + link).
- `cd backend && pytest` stays green. Every detector gets tests before it gets wired in.
- Never commit `data/recordings/` (5-10 MB per hour).

## Run

```bash
# 1. Recorder (stdlib only) - keep it running until the event
python backend/scripts/record.py --once      # 10 s check
python backend/scripts/record.py

# 2. Backend
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload   # API docs: http://localhost:8000/docs
pytest

# 3. How much traffic did we record, and where will a demo jammer show up?
python scripts/inspect_recording.py
```

**Demo day: run uvicorn WITHOUT `--reload`**; it restarts on file save and wipes attacks and incidents:
`uvicorn app.main:app --host 0.0.0.0 --port 8000`.

Startup mode comes from `GAW_MODE` (default `replay`: the newest 3 h of `data/recordings`, or the bundled `data/sample` if there are none). Switch at runtime with `POST /api/mode {"mode": "live"}`. Stop `record.py` while the app runs live: the live poller writes recordings itself (`GAW_RECORD_LIVE`).

**Pin the demo recording** with `GAW_REPLAY_FILES` (comma-separated file names from `data/recordings`; `GET /api/recordings` lists them), in the environment or `.env`:

```bash
GAW_REPLAY_FILES=rec_20261011_08_r080803.jsonl.gz,rec_20261011_09_r080803.jsonl.gz
```

When set, every replay started without explicit names (startup, and `POST /api/mode {"mode": "replay"}`) plays exactly those files instead of "the newest 3 h", so the demo shows a window you have checked. An unknown name stops startup with an error naming `GAW_REPLAY_FILES`.

## Status (11 Oct, backend complete)

| Area | Status |
|---|---|
| Recorder, sources, regions, recording format | done; recorder running on the demo laptop |
| `scripts/inspect_recording.py` | done; coverage, GPS health, detectability, busiest cells |
| Normalize, records, window, clock, runtime, db | done + tests |
| Live poller, replay (speed, seek, loop) | done; smoke-tested end to end on real data |
| Attack injector (simulator) + scenario runner (`/api/scenarios`) | done + tests |
| `detect/jamming.py` | done + tests |
| `detect/spoofing.py` (jump, altitude offset, cluster, track; recovery jumps separated) | done + tests; zero false alarms on the 19-min real sample |
| `detect/warning.py` (15-min projection alerts) | done + tests |
| `detect/incidents.py` (+ SQLite) and `report/pdf.py` | done + tests |
| `detect/evaluate.py` (detected / missed / undetectable / pending / unexplained) | done + tests |
| `sentinel.py` server re-check (baseline SNR, fix loss, drift) | done + tests |
| `web/` | **not started** (full spec: `docs/FRONTEND_HANDOVER.md`) |
| `firmware/` | not here (see `firmware/README.md`) |

## Next tasks, in order

1. Frontend in `web/` against the tick payload below (two people from hour 0).
2. Tonight: run `scripts/inspect_recording.py` on the night's recording; pick demo jammer spots from "busiest cells"; update `scenarios/demo1.json` centre if needed.
3. Tune thresholds only with evidence from recordings; every change in `config.py` with a test.
4. Each teammate reads one detector file end to end so they can explain it to judges.

## Architecture in one picture

```
adsb.fi + adsb.lol --> LivePoller --+                      +--> jamming.classify_cells --> cells (GeoJSON)
                                    +--> Injector.apply --> Window (memory, 30 min) --+--> spoofing / warning / incidents / evaluate
data/recordings ---> Replayer ------+   (simulated attacks)                          +--> tick payload --> /ws (every 5 s)
                       (Clock follows replay time)          SQLite: ground truth, sentinel, incidents
```

## Tick payload (`/ws`, one JSON message per tick; newest tick sent on connect)

```
{type:"tick", ts, mode, region, h3_res, window_s,
 cells: GeoJSON FeatureCollection; properties {h3, state, n_aircraft, n_bad, frac_bad, lower_bound, n_injected, reasons},
 aircraft: [{hex, flight, lat, lon, pos_lost, alt_baro, alt_geom, on_ground, gs, track, nic, nac_p, source, age_s,
             bad (reason or null), spoof ([reasons]), injected (attack ids or null)}],
 alerts: [{id, kind: early_warning | sentinel_jamming | sentinel_spoof, hex, flight, h3, cell_state, eta_s, entry, path, injected, severity, message}],
 incidents_summary: [{id, kind, opened_ts, closed_ts, open, cells, n_aircraft, est_lat, est_lon, est_radius_km, max_frac_bad, injected}],
 attacks: [{id, kind, live, remaining_s, center, radius_km, strength, position_loss, hex, offset_km, alt_offset_ft, label, max_aircraft_inside, ...}],
 sentinel: [{id, status (device), server_status, server_reason, baseline_snr, age_s, avg_snr, sats_used, ...}],
 replay: {t_start, t_end, ts, progress, speed, paused, ...} | null, scenario: {id, fired, remaining, next_ts} | null,
 stats: {aircraft, cells: {state: count}, window_records}, credits: {source: url}}
```

Cell states: `insufficient` (< min aircraft), `clear`, `degraded`, `jammed`, `spoofing`.

## Decisions log (deviations from the handover)

- **D1 Region = list of query circles** (`regions.py`: `nw_border`, `delhi`, `north_india` (default), `all_india` = 12 circles reaching every major airport). H3 is global, so detection works anywhere with no code change. `POST /api/region` switches live polling.
- **D2 Poll adsb.fi (v3 endpoint) and adsb.lol, merge by hex.** The handover had adsb.lol primary; measured, adsb.fi sees 2-4x more in North India. adsb.fi's v2 lat/lon endpoint is deprecated; use v3.
- **D3 adsb.lol every 3rd sweep.** It answered 429 three times in 12 min at 3 req/10 s and adds only 1-2 aircraft up north.
- **D4 Detection reads an in-memory window**; SQLite keeps only what must survive a restart.
- **D5 One `Clock`** for live and replay.
- **D6 `Record` is a slots dataclass** (fast replay); pydantic only at the API edge (`models.py`).
- **D7 Injection is deterministic per aircraft** (hash of attack id + hex), so the Strength slider is monotonic and doesn't flicker. Altered records keep `original`: `DELETE /api/attacks/{id}` restores history (map clears at once); `PATCH active=false` stops injecting and lets the window age out (realistic).
- **D8 Replay seek and loop keep attacks** (timers rebased, ground-truth events closed and reopened). A mode switch clears everything. Attacks only touch records that arrive after them, so keep replay playing during the simulator demo.
- **D9 Only GPS-sourced positions count** (`type` adsb_icao/adsb_other); MLAT, TIS-B, ADS-R and Mode S are excluded from integrity checks.
- **D10 Parse readsb extras**: `lastPosition` (position lost), `gpsOkBefore` / `gpsOkLat` / `gpsOkLon` (aggregator saw GPS loss) — a `gpsOkBefore` record counts as bad.
- **D11 `GET /api/attacks/preview`** reports the busiest H3 cell under the circle, because detection is per cell: a circle with 4 aircraft spread over 3 cells detects nothing.
- **D12 Evaluation reports `undetectable` separately** from missed.
- **D13 Recording format**: one gzip member per JSON line (crash-safe), hourly files with a run id (a restart never appends to a damaged file).
- **D14 Sentinel status adds `SEARCHING`** (no fix / no sky view) so an indoor box doesn't read as jamming.
- **D15 `recovery_jump` is not spoofing.** Real data (FDX5384): during GPS loss the position froze, then leapt 13 km in 22 s when GPS returned. A jump with a weak NIC/NACp at either end is logged as `recovery_jump` and never paints a cell purple (`spoofing.SPOOF_REASONS`).
- **D16 Altitude offset is compared as a fraction of altitude** (GPS minus baro grows with height, ~+4%), so a normal low aircraft isn't flagged against high peers.
- **D18 Strong vs weak spoofing evidence.** First live run (11 Oct 13:50) raised two inland one-aircraft spoofing alarms. Now `impossible_jump` / `colocation_cluster` can turn a cell purple alone; `alt_offset_outlier` / `track_mismatch` must repeat on the aircraft and need `spoof_cell_min_flags` (2) aircraft per cell. A judge's spoof with `offset_km` > 0 still turns its cell purple; an altitude-only spoof flags the aircraft, not the cell.
- **D17 Attacks act only from their start time and expire only by duration**; evaluation never calls an unmatched alarm "false", because on live data it may be real.

## Measured facts (Sun 11 Oct 2026, 12:14-12:36 IST)

- Aircraft per query, adsb.fi / adsb.lol / union: Amritsar 250 NM 42/18/44, J&K 150 NM 2/1/3, Delhi 150 NM 50/12/51, Mumbai 10/23/23, Chennai 22/27/30.
- 10-min windows at H3 res 3: ~28 occupied cells, ~10 with >= 3 aircraft. The busiest cell was the Delhi approach (~30 aircraft); a 60 km jammer at Amritsar covered 3 cells with at most 2 aircraft each, so it would show **nothing**. Demo jammers go where `inspect_recording.py` says traffic is.
- Real event caught in the first 12 minutes: FDX5384 (B77L, N857FD) at FL370 near 33.5N 72.9E (near Islamabad, about 100 km west of the Line of Control) reported NIC 0 / NACp 0, and adsb.fi set `gpsOkBefore`. One aircraft is not proof of jamming; it is exactly the signal the crowd method aggregates.
- Both APIs return `now` in milliseconds and the ADSBx-v2 shape `{ac, msg, now, total, ctime, ptime}`. airplanes.live returned 403 from a cloud IP.

## Git workflow

- `main` stays runnable. Work on `feat/<thing>` branches, run `pytest`, push, open a PR. Rakesh merges (Claude in the claude.ai project chat can review and merge on request).
- Small commits with clear messages. Never commit recordings, `.env`, or `data/*.db`.
