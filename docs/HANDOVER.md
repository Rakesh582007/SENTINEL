# HANDOVER — GPS Attack Watch (Team Ethicals, SEDHACKS'26)

> Paste this whole file into a fresh Claude Code session, or save it in the repo as `CLAUDE.md` / `docs/HANDOVER.md`.
> Everything a new session needs is in here; it does not depend on any earlier chat.

---

## 0. TL;DR for Claude Code

Build a **local web app** that detects **GPS jamming and spoofing over North-West India** from free public aircraft (ADS-B) data, **warns flights heading into affected areas**, and **auto-generates incident reports**.

- **Backend:** Python 3.11 + FastAPI + SQLite + `h3` + `numpy`/`pandas` + `reportlab`
- **Frontend:** React (Vite) + Tailwind CSS + `react-leaflet`
- **Runs on:** ONE laptop (RTX 3050, Windows likely). No cloud. No GPU needed.
- **Timeline:** 24-hour hackathon starts **Mon 12 Oct 2026, 08:00 IST**. Before that: backend core + data recording + a minimal frontend shell (only if pre-built code is allowed — team must confirm the rules).
- **The app has THREE sections** (tabs or a 3-part layout):
  1. **Live Airspace** — real ADS-B data over North India (adsb.lol / adsb.fi).
  2. **Attack Simulator** — same pipeline, judges inject jamming/spoofing with sliders (§7.1), live or on replay.
  3. **Ground Sentinel** — live data from the team's ESP32 + NEO-6M GPS box on the demo table (§9.1). Foil over the antenna = real, physical signal loss the system detects.

---

## 1. The problem (context for decisions)

- Planes navigate by GPS. **Jamming** = noise drowns GPS → receiver loses position. **Spoofing** = fake signals → receiver computes a wrong position without knowing it.
- India reported **923 GNSS interference incidents (Feb 2024–Feb 2025), 63% near Amritsar/Jammu** (Govt of India presentation to ICAO, 2025). Crews have received false terrain ("PULL UP") warnings.
- Every aircraft broadcasts ADS-B ~1/sec: position, barometric altitude, GPS altitude, and **GPS-integrity fields (`nic`, `nac_p`)**. When GPS is jammed, those values drop or the position disappears. Aggregating many aircraft by area reveals interference zones.
- Existing tool **GPSJam.org** only shows a daily map and does not separate jamming from spoofing or warn anyone. **Our differentiators:** minutes-level updates, jamming vs spoofing classification, early warning for incoming flights, auto incident report, measured accuracy.

## 2. Verified facts (checked 11 Oct 2026 — do not re-derive)

- `GET https://api.adsb.lol/v2/point/31.6/74.9/250` (lat, lon, radius in **nautical miles**) returned **19 aircraft**. No API key.
- Aircraft objects contain: `hex, type, flight, r, t, alt_baro, alt_geom, gs, track, baro_rate, squawk, category, lat, lon, nic, rc, seen_pos, version, nac_p, nac_v, sil, sil_type, alert, spi, mlat, tisb, messages, seen, rssi` (+ sometimes `calc_track`, `nic_baro`, `gva`, `sda`, `true_heading`, …).
- **Gotchas observed:**
  - Some aircraft lack `gs`, `flight`, `alt_geom`, or have `calc_track` instead of `track` → every field is optional.
  - `alt_baro` can be the **string `"ground"`** for aircraft on the ground → treat as on-ground, exclude from airborne logic.
  - `alt_geom − alt_baro` is **normally non-zero** (example: 36,550 vs 35,000 ft = +1,550 ft) because of temperature/pressure. **Never** flag spoofing on the raw difference; compare against nearby aircraft (see §6.2).
  - **Coverage near the border is thin** (19 aircraft in a 250 NM radius). Detection must aggregate over larger cells and longer windows (see §6.1).
- Response top-level also has `total`, `now` (epoch ms or s — check), `ac` (array).

**VERIFY (not yet confirmed):**
- adsb.fi fallback endpoint: `https://opendata.adsb.fi/api/v2/lat/{lat}/lon/{lon}/dist/{nm}` (rate limit ~1 req/s).
- Whether `now` is seconds or ms; whether adsb.lol has a rate limit (be polite: ≥10 s between polls per query point).

## 3. Architecture

```
 adsb.lol (+ adsb.fi fallback) ──► ingest/poller.py ─┐
 data/recordings/*.jsonl.gz ─────► ingest/replay.py ─┤  (identical normalized records)
 scenarios/*.json ───────────────► ingest/injector.py┘  (mutates records + logs ground truth)
                                        │
                                        ▼
                               store: SQLite (data/app.db)
                                        │
                     detect/ (runs every 30 s on a sliding window)
                       ├── jamming.py   → per-H3-cell status
                       ├── spoofing.py  → per-aircraft flags
                       ├── warning.py   → 15-min path projection alerts
                       ├── incidents.py → open/close incidents, jammer estimate
                       └── evaluate.py  → precision/recall vs injected ground truth
                                        │
                     api/ (FastAPI): REST + WebSocket /ws
                                        │
                     web/ (React + Tailwind + react-leaflet)
```

**Single process** is fine: FastAPI app with background asyncio tasks (poller/replayer + detector loop). Keep a `MODE` = `live | replay` switch.

## 4. Repo layout

```
gps-attack-watch/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app, startup tasks, CORS for localhost:5173
│   │   ├── config.py          # all thresholds & settings (pydantic-settings, .env overrides)
│   │   ├── models.py          # pydantic schemas (Record, CellStatus, Alert, Incident…)
│   │   ├── db.py              # SQLite (sqlite3 or SQLModel), WAL mode
│   │   ├── ingest/{poller.py, replay.py, injector.py, normalize.py}
│   │   ├── detect/{jamming.py, spoofing.py, warning.py, incidents.py, evaluate.py, geo.py}
│   │   ├── report/pdf.py      # ReportLab incident PDF
│   │   └── api/{routes.py, ws.py}
│   ├── scripts/record.py      # standalone recorder (run tonight!)
│   ├── tests/                 # pytest with fixture JSON
│   └── requirements.txt
├── web/                       # Vite + React + Tailwind
├── data/recordings/           # *.jsonl.gz (gitignored if large)
├── scenarios/                 # demo attack scenarios (json)
└── README.md
```

## 5. Data model

### 5.1 Normalized record (one per aircraft per poll)
```python
class Record(BaseModel):
    ts: float            # unix seconds (poll time minus `seen_pos` for position time)
    hex: str             # ICAO 24-bit id (unique aircraft key)
    flight: str | None
    lat: float | None    # None = position missing
    lon: float | None
    alt_baro: int | None # None if missing; on_ground=True if "ground"
    alt_geom: int | None
    on_ground: bool
    gs: float | None     # knots
    track: float | None  # degrees (fallback calc_track)
    nic: int | None
    nac_p: int | None
    seen: float | None   # s since any message
    seen_pos: float | None  # s since last position
    source: str          # "adsb.lol" | "adsb.fi" | "replay"
    injected: str | None # scenario id if mutated by injector
```

### 5.2 SQLite tables
- `positions(ts, hex, flight, lat, lon, alt_baro, alt_geom, on_ground, gs, track, nic, nac_p, seen, seen_pos, source, injected)` — index `(ts)`, `(hex, ts)`. Prune rows older than 2 h in live mode.
- `cell_status(ts, h3, n_aircraft, n_bad, frac_bad, lower_bound, state)` — latest snapshot per cell is enough.
- `alerts(id, ts, kind, hex, flight, h3, eta_s, message, severity, ack)`
- `incidents(id, kind, opened_ts, closed_ts, cells_json, aircraft_json, est_lat, est_lon, est_radius_km, max_frac_bad)`
- `ground_truth(scenario_id, kind, start_ts, end_ts, geom_json, targets_json)` (from injector)

## 6. Detection logic (all numbers live in `config.py`, tune on recorded data)

### 6.1 Jamming (per H3 cell)
- Window: last **20 min** (`JAM_WINDOW_S=1200`). Cells: **H3 resolution 3** (~60 km edge) default; allow res 4 for zoomed view.
- Consider only airborne records (`on_ground=False`).
- An aircraft is **bad** in a cell if, in the window, any of:
  - `nac_p is not None and nac_p <= NACP_BAD` (start: **7**), or
  - `nic is not None and nic <= NIC_BAD` (start: **5**), or
  - **position loss:** `seen < 10` but `seen_pos > 60` (still transmitting, no position) — attribute to its last known cell.
- Count **unique aircraft** (`hex`) per cell, not records.
- `frac_bad = n_bad / n_aircraft`; also compute **Wilson lower bound** (95%) to avoid small-sample noise.
- State:
  - `insufficient` if `n_aircraft < 3`
  - `jammed` if `n_bad >= 2` and `lower_bound >= 0.15` (≈ visibly high share)
  - `degraded` if `n_bad >= 1` and `frac_bad >= 0.10`
  - else `clear`
- Output GeoJSON polygons (use `h3.cell_to_boundary`) so the frontend does no H3 math.

### 6.2 Spoofing (per aircraft) → `spoof_suspected` with reason codes
1. **Impossible jump:** consecutive positions of same `hex` with implied speed > **1,000 kt** and distance > **5 km**. (`haversine`)
2. **Altitude-offset outlier:** `off = alt_geom − alt_baro`. Compute robust median & MAD of `off` for all aircraft within **300 km** in the last **10 min** (need ≥ 4 peers). Flag if `|off − median| > max(1000 ft, 4×MAD)`.
3. **Co-location cluster:** ≥ 3 distinct airborne `hex` within **1 km** of each other at the same time (±10 s) and altitude difference > 3,000 ft (real aircraft can't stack like that).
4. **Track mismatch (optional):** reported `track` vs bearing between consecutive positions differs > 60° while `gs > 150`.
- A cell becomes `spoofing` (purple) if ≥ 1 aircraft in it has ≥ 1 flag in the window (≥ 2 for high confidence).

### 6.3 Early warning
- For each airborne aircraft **not** currently in a jammed/spoofing cell with `gs` and `track` present:
  project along great-circle: every 30 s up to **15 min** (`dist = gs_kt × 1.852 × t_h`).
- First projected point inside a `jammed`/`spoofing` cell → alert `{hex, flight, h3, eta_s, kind}`.
- De-duplicate: one active alert per (hex, cell); expire when aircraft passes or cell clears.

### 6.4 Incidents & jammer estimate
- Open an incident when a cell first becomes `jammed`/`spoofing`; merge neighbouring affected cells (`h3.grid_disk(c,1)`) into the same incident; close after **10 min** all-clear.
- **Approximate jammer area** (jamming only): take each bad aircraft's **first bad position** in the incident; centre = mean of those points; radius = 80th-percentile distance from centre (min 15 km). Always label "approximate area", never a pinpoint.
- `GET /api/incidents/{id}/report.pdf` → ReportLab one-pager: title, time window (IST), kind, affected cells, list of aircraft (hex/flight/first-bad time), estimated area, map-less text summary, disclaimer "auto-generated, for analyst review".

### 6.5 Evaluation (key demo slide)
- Match detections to `ground_truth` events: a jamming event counts as detected if any overlapping cell becomes `jammed` within 5 min of its start; spoof event detected if the target hex gets flagged.
- Report: detected / total events, false-alarm incidents (no matching ground truth), mean time-to-detect. Expose `GET /api/evaluation`.

## 7. Replay + attack injector

- **Recorder (`scripts/record.py`) — run TONIGHT for as many hours as possible:** poll 2–3 query points every 10 s, append raw JSON lines (gzip) with poll timestamp. Suggested points (radius NM): `(31.6, 74.9, 250)` Amritsar/Punjab, `(33.6, 75.0, 150)` J&K, `(28.6, 77.2, 150)` Delhi (control area). Do not hammer the API.
- **Replay:** stream a recording at `speed` × real time (1–20×) through the same pipeline; frontend shows a time slider/clock.
- **Scenario file** (`scenarios/demo1.json`):
```json
{
  "id": "demo1",
  "events": [
    {"kind": "jamming", "center": [31.72, 74.98], "radius_km": 60,
     "start_offset_s": 600, "duration_s": 1500,
     "effect": {"nac_p": 0, "nic": 0, "drop_position_prob": 0.4}},
    {"kind": "spoof_jump", "hex": "AUTO", "start_offset_s": 1200,
     "offset_km": [25, -10], "duration_s": 300},
    {"kind": "spoof_alt", "hex": "AUTO", "start_offset_s": 1500,
     "alt_geom_offset_ft": -2500, "duration_s": 300}
  ]
}
```
  `"AUTO"` = injector picks an aircraft present at that time. Injector writes `ground_truth` rows and sets `record.injected`.
- UI must clearly label injected scenarios ("Test scenario: attacks injected into real traffic").

## 7.1 Attack Simulator panel (judge-facing, HIGH PRIORITY for the demo)

The centrepiece of the demo: judges move sliders and watch the system react in real time on live OR replay data.

**Frontend panel "Attack Simulator" (collapsible, right side or bottom drawer):**
- **Jamming controls**
  - "Place jammer": click on the map to set the centre (show a draggable marker).
  - Slider **Radius**: 10–150 km (default 60).
  - Slider **Strength**: 0–100% = share of aircraft inside the radius that get `nac_p/nic` forced to 0 (default 70%).
  - Slider **Position-loss**: 0–100% = chance an affected aircraft's position is dropped entirely (default 30%).
  - Toggle **Active** (on/off) + Slider **Duration**: 1–30 min or "until switched off".
- **Spoofing controls**
  - "Pick aircraft": click an aircraft on the map (or "random").
  - Slider **Position offset**: 0–80 km (jump size).
  - Slider **Altitude offset**: −4000 to +4000 ft (GPS altitude vs barometer).
  - Button **Spoof now**.
- **Detection sensitivity** (shows judges the trade-off)
  - Slider **NACp threshold** (5–9), **Min aircraft per cell** (2–6), **Window** (5–30 min), **Cell size** (H3 res 3 / 4).
  - Live readout: current detected / injected events, false alarms.
- **Time controls (replay mode):** play/pause, speed slider 1–20×, timeline scrubber to jump to any moment of the recording.
- **Reset** button: clear all injected attacks.

**Backend support:**
- Injector keeps a list of **active live attacks** in memory, applied to every incoming record (live poll or replay) before storage; each change also writes a `ground_truth` row so evaluation still works.
- `POST /api/attacks` body `{kind:"jamming", center:[lat,lon], radius_km, strength, position_loss, duration_s|null}` or `{kind:"spoof", hex|"random", offset_km, alt_offset_ft}` → returns `{attack_id}`.
- `PATCH /api/attacks/{id}` (slider moves update live), `DELETE /api/attacks/{id}`, `DELETE /api/attacks` (reset), `GET /api/attacks`.
- `PATCH /api/config/detection` → updates thresholds at runtime (validated ranges); detector uses new values on next tick.
- `POST /api/replay/seek {ts}` and `POST /api/replay/speed {speed}` for the timeline.
- Slider changes: debounce 300 ms on the frontend before sending.
- Detector tick for the demo: every **5 s** (configurable) so reactions feel instant.
- Everything injected is shown with an "INJECTED TEST ATTACK" badge on the map and in alerts.

## 8. API contract

| Method | Path | Returns |
|---|---|---|
| GET | `/api/health` | `{mode, last_poll_ts, n_aircraft}` |
| GET | `/api/aircraft` | latest position per hex + flags |
| GET | `/api/cells` | GeoJSON FeatureCollection; props `{h3, state, n_aircraft, n_bad, frac_bad}` |
| GET | `/api/alerts?active=true` | list of alerts |
| GET | `/api/incidents` | list; `/api/incidents/{id}` detail; `/api/incidents/{id}/report.pdf` |
| GET | `/api/evaluation` | metrics vs ground truth |
| POST | `/api/mode` | `{mode: "live"|"replay", recording?, speed?, scenario?}` |
| POST | `/api/sentinel` | optional ESP32 status `{id, lat, lon, sats, avg_snr, fix, flags}` |
| WS | `/ws` | every detector tick: `{type:"tick", ts, cells, aircraft, alerts, incidents_summary}` |

CORS: allow `http://localhost:5173`.

## 9. Frontend (React + Vite + Tailwind + react-leaflet)

- **Layout:** top bar (name, LIVE/REPLAY badge, clock, speed control) · left: map (≈70%) · right: alerts panel + incident list · bottom of map: legend.
- **Map layers:** H3 cell polygons coloured by state (clear green, degraded amber, jammed red, spoofing purple — always paired with text labels/legend, never colour alone); aircraft markers rotated by `track`; flagged aircraft outlined; early-warning dashed projection line to the entry point; incident jammer circle (dashed).
- **Alerts panel:** cards with kind tag (JAMMING / SPOOF SUSPECTED / EARLY WARNING), place, counts, ETA; "Download report (PDF)" per incident.
- **Evaluation view:** small panel/modal with detected/total, false alarms, time-to-detect.
- **Data flow:** one WebSocket hook (`useLiveFeed`) → global state (Zustand or React context); REST only for incidents/PDF/evaluation.
- **Basemap:** needs internet (CARTO dark or OSM). Risks:
  1. Venue Wi-Fi may fail → app must still render cells/aircraft on a plain dark background if tiles fail.
  2. Some basemaps draw international boundaries in J&K differently from India's official map — check before the demo; if in doubt use satellite imagery tiles (no political lines) or no basemap.
- Visual style matches the deck: dark navy UI, frost-white cards, one signal-orange accent.

## 9.1 Ground Sentinel (section 3) — ESP32 + NEO-6M + 0.96" OLED + buzzer

**Hardware:** ESP32 DevKit V1, u-blox NEO-6M (GPS L1 only, no NavIC), SSD1306 OLED (I2C), buzzer, LED. Box sits still on the demo table near a window.

**Firmware (Arduino IDE / PlatformIO, C++):**
- Read NMEA from NEO-6M over UART2 (9600 baud). Use TinyGPSPlus + `TinyGPSCustom` to read **GSV** fields (satellites in view + per-satellite SNR) and GGA (fix quality, sats used, HDOP).
- Compute every 1 s: `sats_in_view`, `sats_used`, `avg_snr` (mean of top 4 SNRs), `fix` (bool), `hdop`, `lat`, `lon`, `alt`.
- **Baseline:** after a stable fix for 2 min, store reference position (median of last 60 fixes) and baseline `avg_snr`.
- **Local alarms (work even if laptop/Wi-Fi is down):**
  - `JAMMING?` if `avg_snr` drops ≥ 10 dB below baseline OR fix lost for > 5 s while it was stable → buzzer + LED + OLED message.
  - `SPOOF?` if position moves > 50 m from the reference (box is stationary) or altitude jumps > 100 m.
- OLED shows: sats used/in view, avg SNR bar, status (OK / JAMMING? / SPOOF?).
- **Wi-Fi:** laptop + ESP32 on the same phone hotspot. ESP32 `HTTP POST` JSON every 2 s to `http://<laptop-ip>:8000/api/sentinel`. Laptop IP + SSID in a `config.h`.
- Payload: `{"id":"sentinel-1","ts":<millis>,"lat":..,"lon":..,"alt":..,"fix":true,"sats_used":8,"sats_in_view":11,"avg_snr":38.5,"hdop":0.9,"status":"OK|JAMMING|SPOOF","snr_list":[..]}`

**Backend:**
- `POST /api/sentinel` stores into table `sentinel(ts, id, lat, lon, alt, fix, sats_used, sats_in_view, avg_snr, hdop, status, raw_json)`; server re-checks the same rules (don't trust device alone) and raises an alert `kind:"sentinel_jamming"|"sentinel_spoof"` with "REAL SIGNAL TEST" label.
- `GET /api/sentinel/latest`, `GET /api/sentinel/history?minutes=10`; sentinel state also included in every `/ws` tick.
- If no packet for 10 s → status `OFFLINE` (show grey, don't crash).

**Frontend section 3:**
- Big status card (OK green / JAMMING? red / SPOOF? purple / OFFLINE grey) — colour + text.
- Live line charts (last 5 min): `avg_snr` and `sats_used` — the foil test shows a clear cliff.
- Small sky plot or bar list of per-satellite SNR.
- Sentinel pin on the main map (Chennai) with the same status.
- Event log: "14:32:05 signal dropped 18 dB — JAMMING suspected (antenna covered)".

**Demo:** "This box is real hardware listening to real GPS satellites right now." Judge covers the antenna with a steel tumbler/foil → within ~5 s buzzer + dashboard turns red → remove it → recovers. Never transmit anything.

## 10. Build order (stop at any point with something demo-able)

**Tonight (only if the rules allow pre-built code; otherwise only step 1):**
1. `scripts/record.py` — start recording immediately, keep it running all night (laptop plugged in, sleep disabled).
2. `normalize.py` + tests with saved sample JSON (handle every gotcha in §2).
3. SQLite + poller + `/api/aircraft` + `/ws`.
4. `jamming.py` + `/api/cells` (GeoJSON).
5. Replay + injector + `scenarios/demo1.json` + live-attack API (§7.1).
6. Frontend shell: map + cells + aircraft via WebSocket + Attack Simulator jamming sliders.

**Hackathon day (24 h):**
7. `spoofing.py` (jump + altitude-offset first, cluster later).
8. `warning.py` + alerts panel + projection lines.
9. `incidents.py` + PDF report.
10. `evaluate.py` + evaluation panel.
10b. Sentinel: firmware (one teammate, in parallel from hour 0) + `/api/sentinel` + section 3 UI.
11. Tune thresholds on recordings; compare one recorded day vs GPSJam.org for sanity.
12. Polish UI, demo script, backup screen recording of the demo.

**Rule:** the demo runs in **replay mode with the demo scenario** by default. Live mode is a bonus.

## 11. Demo script (3 min)

1. Problem (923 incidents, 63% near Amritsar/Jammu) — 20 s.
2. Live map of real aircraft right now — 20 s.
3. Hand the mouse to a judge: "place a jammer anywhere" → they click near Amritsar, drag Strength up → cells turn red within seconds → alert card. Let them drag Radius and see the zone grow.
4. Early warning: an incoming flight gets "enters red zone in ~12 min" with dashed path.
5. Spoof: one aircraft jumps / altitude mismatch → purple flag with reason.
6. Download the auto-generated incident PDF.
7. Evaluation panel: "detected X of Y injected events, Z false alarms".
8. Section 3: judge covers the sentinel antenna → real alarm on the box and dashboard.
9. Close: receive-only, free data; next phase = NavIC cross-check + network of sentinels at border airports.

## 12. Ground rules

- **Receive-only.** Never transmit or simulate RF jamming/spoofing over the air. Attacks exist only as data injection.
- Do not claim to identify who is jamming. Say "approximate area for investigation".
- Label all injected/sample data honestly in the UI.
- Keep every threshold in `config.py`; no magic numbers in logic.
- Write small pytest tests for normalize, jamming state rules, spoof jump, projection math.

## 13. Requirements (starting point)
`backend/requirements.txt`: `fastapi uvicorn[standard] httpx pydantic pydantic-settings h3>=4 numpy pandas reportlab pytest`
`web/`: `npm create vite@latest web -- --template react` → `tailwindcss`, `react-leaflet`, `leaflet`, `zustand`.
