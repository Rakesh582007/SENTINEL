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

Startup mode comes from `GAW_MODE` (default `replay`: the newest 3 h of `data/recordings`, or the bundled `data/sample` if there are none). Switch at runtime with `POST /api/mode {"mode": "live"}`. Stop `record.py` while the app runs live: the live poller writes recordings itself (`GAW_RECORD_LIVE`).

## Status (end of 11 Oct)

| Area | Status |
|---|---|
| `scripts/record.py`, `ingest/recording.py`, `ingest/sources.py`, `regions.py` | done; recorder tested live |
| `scripts/inspect_recording.py` | done; coverage, GPS health, detectability, busiest cells |
| `ingest/normalize.py`, `records.py` | done + tests (every gotcha below) |
| `state.py` (window), `clock.py`, `runtime.py`, `db.py` | done |
| `ingest/poller.py` (live), `ingest/replay.py` | done; smoke-tested end to end on real data |
| `ingest/injector.py` (Attack Simulator) | done + tests |
| `detect/jamming.py` | done + tests |
| `api/routes.py`, `main.py` (`/ws`) | done; endpoints of TODO modules return `[]` or 501 |
| `detect/spoofing.py` | **TODO**, contract in its docstring, already called every tick |
| `detect/warning.py` | **TODO**, same |
| `detect/incidents.py`, `report/pdf.py` | **TODO**, same |
| `detect/evaluate.py` | **TODO**, same |
| `sentinel.py` server-side re-check | **TODO** (rules in its docstring) |
| scenario runner for `scenarios/*.json` | TODO (optional) |
| `web/` | not started (see `web/README.md`) |
| `firmware/` | not started here (see `firmware/README.md`) |

## Next tasks, in order

1. `detect/spoofing.py`: impossible jump + altitude-offset outlier first, then co-location cluster. Tests first.
2. `detect/warning.py`: 15-min projection alerts.
3. `detect/incidents.py` + `report/pdf.py`. For the jammer area, prefer `Record.gps_ok_lat/lon` (readsb's last-good position) when present, else the first bad position.
4. `detect/evaluate.py`: report `undetectable` separately (`Attack.max_aircraft_inside` is already tracked).
5. Sentinel re-check rules; then the scenario runner if time allows.
6. Frontend in `web/` against the tick payload below.

## Architecture in one picture

```
adsb.fi + adsb.lol --> LivePoller --+                      +--> jamming.classify_cells --> cells (GeoJSON)
                                    +--> Injector.apply --> Window (memory, 30 min) --+--> spoofing / warning / incidents (TODO)
data/recordings ---> Replayer ------+   (simulated attacks)                          +--> tick payload --> /ws (every 5 s)
                       (Clock follows replay time)          SQLite: ground truth, sentinel, incidents
```

## Tick payload (`/ws`, one JSON message per tick; newest tick sent on connect)

```
{type:"tick", ts, mode, region, h3_res, window_s,
 cells: GeoJSON FeatureCollection; properties {h3, state, n_aircraft, n_bad, frac_bad, lower_bound, n_injected, reasons},
 aircraft: [{hex, flight, lat, lon, pos_lost, alt_baro, alt_geom, on_ground, gs, track, nic, nac_p, source, age_s,
             bad (reason or null), spoof ([reasons]), injected (attack ids or null)}],
 alerts: [...]  (warning.py), incidents_summary: [...] (incidents.py),
 attacks: [{id, kind, live, remaining_s, center, radius_km, strength, position_loss, hex, offset_km, alt_offset_ft, label, max_aircraft_inside, ...}],
 sentinel: [{id, status, age_s, avg_snr, sats_used, ...}], replay: {t_start, t_end, ts, progress, speed, paused, ...} | null,
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

## Measured facts (Sun 11 Oct 2026, 12:14-12:36 IST)

- Aircraft per query, adsb.fi / adsb.lol / union: Amritsar 250 NM 42/18/44, J&K 150 NM 2/1/3, Delhi 150 NM 50/12/51, Mumbai 10/23/23, Chennai 22/27/30.
- 10-min windows at H3 res 3: ~28 occupied cells, ~10 with >= 3 aircraft. The busiest cell was the Delhi approach (~30 aircraft); a 60 km jammer at Amritsar covered 3 cells with at most 2 aircraft each, so it would show **nothing**. Demo jammers go where `inspect_recording.py` says traffic is.
- Real event caught in the first 12 minutes: FDX5384 (B77L, N857FD) at FL370 near 33.5N 72.9E (near Islamabad, about 100 km west of the Line of Control) reported NIC 0 / NACp 0, and adsb.fi set `gpsOkBefore`. One aircraft is not proof of jamming; it is exactly the signal the crowd method aggregates.
- Both APIs return `now` in milliseconds and the ADSBx-v2 shape `{ac, msg, now, total, ctime, ptime}`. airplanes.live returned 403 from a cloud IP.

## Git workflow

- `main` stays runnable. Work on `feat/<thing>` branches, run `pytest`, push, open a PR. Rakesh merges (Claude in the claude.ai project chat can review and merge on request).
- Small commits with clear messages. Never commit recordings, `.env`, or `data/*.db`.
