# FRONTEND HANDOVER — SENTINEL / GPS Attack Watch

**Team Ethicals · SEDHACKS'26 · written Sun 11 Oct 2026, 20:35 IST**

Give this whole file to a new chat or to Claude Code before building the frontend. It is self-contained. The backend is finished and running; the frontend talks to it and nothing else.

---

## 0. TL;DR

- **Build:** a React dashboard in `web/` (Vite + React + Tailwind + react-leaflet + zustand).
- **Data:** one WebSocket, `ws://localhost:8000/ws`, sends the whole picture every 5 s (§4). Buttons and sliders call REST endpoints on `http://localhost:8000/api/...` (§5). Interactive API docs: http://localhost:8000/docs.
- **Three sections:** Live Airspace, Attack Simulator, Ground Sentinel (§6).
- **The backend does all the maths.** Hexagons arrive as ready-to-draw GeoJSON; the browser never computes H3 or detection.
- **Workflow:** branch `feat/web`, push, then in the claude.ai project chat ask for "review feat/web"; it gets reviewed and merged.
- **Hard rules (§9):** state colours always paired with text, an "INJECTED TEST ATTACK" badge on anything injected, adsb.fi + adsb.lol credits visible, and the map must work if tiles fail.

---

## 1. What the product is (60-second version)

Planes broadcast their position and **how much they trust their GPS** every second (ADS-B: the NIC/NACp scores). Hobbyist antennas share this publicly (adsb.fi, adsb.lol). When **several different planes** in one area report bad GPS at the same time, that area is being **jammed**; when planes report **physically impossible** positions, it may be **spoofed**. We:

1. paint the map in hexagons: clear / degraded / **jammed (red)** / **spoofing (purple)** / insufficient data (grey)
2. **warn** flights heading into red/purple areas 5–15 min ahead (to controllers; we never transmit)
3. auto-file an **incident report** (PDF)
4. let judges **inject fake attacks** (Attack Simulator) and measure detection
5. read a **Ground Sentinel** box (ESP32 + GPS) on the table that detects signal loss when its antenna is covered

Receive-only. No AI. Statistics + physics rules, so every alarm can be explained.

---

## 2. Status (end of 11 Oct)

| Part | Status |
|---|---|
| Backend: ingest, replay, detectors, incidents, PDF, evaluation, sentinel, database, API | ✅ done, 72 tests, on GitHub `main` |
| Recorder (`backend/scripts/record.py`) | ✅ running on the demo laptop overnight |
| Real-data result | ✅ flagged GPS degradation on 4 aircraft near Islamabad on 11 Oct; GPSJam's 10 Oct map shows high interference in the same area |
| **Frontend `web/`** | ❌ **not started: this handover is for it** |
| ESP32 sentinel | hardware teammate; not yet connected to the backend |
| Pitch | script exists (§10); needs the GPSJam slide and the Islamabad result |

Repo: https://github.com/Rakesh582007/SENTINEL. Backend docs: `CLAUDE.md` (decisions, measured facts), `docs/HANDOVER.md` (original spec).

---

## 3. Running the backend locally (needed while building the frontend)

```bash
# terminal 1 - recorder (from the repo root; don't click inside this window)
python backend/scripts/record.py

# terminal 2 - backend (from backend/)
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# terminal 3 - frontend (from web/)
npm run dev        # http://localhost:5173 (already allowed by the backend's CORS)
```

- The backend starts in **replay** mode (plays recorded real traffic in a loop). Switch with `POST /api/mode {"mode":"live"}` / `{"mode":"replay"}`.
- Replay loads recordings **once at startup**; restart uvicorn to include newer recordings.
- Replay loops; each loop clears incidents and they re-open (that's why the log shows the same Islamabad incident about every 17 min). That's expected.

---

## 4. The live feed: `ws://localhost:8000/ws`

One JSON message per detector tick (every 5 s). **The newest tick is sent immediately on connect.** Clients don't need to send anything. On disconnect, reconnect with backoff (1 s, 2 s, 4 s, max 10 s) and show a "Reconnecting…" badge.

```jsonc
{
  "type": "tick",
  "ts": 1791707467.57,            // unix seconds (replay = recording time)
  "mode": "replay",               // "live" | "replay"
  "region": "north_india",
  "h3_res": 3,
  "window_s": 1200,               // detection window (20 min)

  "cells": {                      // GeoJSON FeatureCollection, draw directly
    "type": "FeatureCollection",
    "features": [{
      "type": "Feature", "id": "834269fffffffff",
      "geometry": { "type": "Polygon", "coordinates": [[[lon,lat], ... , [lon,lat]]] },
      "properties": {
        "h3": "834269fffffffff",
        "state": "jammed",        // insufficient | clear | degraded | jammed | spoofing
        "n_aircraft": 4, "n_bad": 2, "frac_bad": 0.5, "lower_bound": 0.15,
        "n_injected": 0,          // bad aircraft caused by simulated attacks
        "reasons": { "low_nacp": 2 }
      }
    }]
  },

  "aircraft": [{
    "hex": "801460", "flight": "IGO2317", "lat": 28.79, "lon": 75.85,
    "pos_lost": false,            // true = showing LAST KNOWN position
    "alt_baro": 32000, "alt_geom": 33575, "on_ground": false,
    "gs": 417.3, "track": 328.0,  // knots, degrees (rotate the icon by track)
    "nic": 8, "nac_p": 10, "source": "adsb.fi", "age_s": 3.2,
    "bad": null,                  // null or "low_nacp" | "low_nic" | "position_lost" | "gps_lost_flag"
    "spoof": [],                  // e.g. ["impossible_jump"], ["recovery_jump"] (recovery = info only)
    "injected": null              // null or "jam-1,spoof-2" -> show INJECTED badge
  }],

  "alerts": [{
    "id": "ew-801460-834269fffffffff",
    "kind": "early_warning",      // | "sentinel_jamming" | "sentinel_spoof"
    "hex": "801460", "flight": "IGO2317", "h3": "834269fffffffff",
    "cell_state": "jammed", "eta_s": 480,
    "entry": [33.1, 72.9],        // where it enters the zone
    "path": [[lat,lon], ...],     // projected path, draw dashed to `entry`
    "injected": false, "severity": "high",   // high (<=5 min) | medium
    "message": "IGO2317 enters a GPS-jammed area in ~8 min. Prepare backup navigation.",
    "label": "SIGNAL TEST (antenna covered)" // only on sentinel_* alerts
  }],

  "incidents_summary": [{
    "id": "inc-3", "kind": "jamming",          // | "spoofing"
    "opened_ts": 1791707467.5, "closed_ts": null, "open": true,
    "cells": ["834269fffffffff"], "n_aircraft": 3,
    "est_lat": 33.29, "est_lon": 72.99, "est_radius_km": 46.7,   // jamming only; draw a DASHED circle
    "max_frac_bad": 0.5, "injected": false
  }],

  "attacks": [{
    "id": "jam-1", "kind": "jamming", "live": true, "remaining_s": null,
    "center": [28.47, 77.2], "radius_km": 60, "strength": 0.8, "position_loss": 0.3,
    "hex": null, "offset_km": 25, "bearing_deg": 45, "alt_offset_ft": 0,
    "max_aircraft_inside": 16, "label": "INJECTED TEST ATTACK"
  }],

  "sentinel": [{
    "id": "sentinel-1",
    "status": "OK",               // what the device says
    "server_status": "OK",        // what the server concluded: OK | SEARCHING | JAMMING | SPOOF | OFFLINE  <- show THIS
    "server_reason": null,        // e.g. "signal 14 dB below baseline"
    "baseline_snr": 39.5, "avg_snr": 38.5, "sats_used": 8, "sats_in_view": 11,
    "lat": 13.0, "lon": 80.2, "fix": true, "age_s": 1.2, "snr_list": [41, 38, ...]
  }],

  "replay": { "t_start": 0, "t_end": 0, "ts": 0, "progress": 0.46, "speed": 1,
              "paused": false, "finished": false, "frames": 498, "records": 9886,
              "segments": 1, "sample": false, "files": ["rec_...jsonl.gz"] },   // null in live mode
  "scenario": null,               // {id, fired:[...], remaining, next_ts} while a scripted demo runs
  "stats": { "aircraft": 44, "cells": { "clear": 10, "insufficient": 17, "jammed": 1 }, "window_records": 4118 },
  "credits": { "adsb.fi": "https://adsb.fi", "adsb.lol": "https://adsb.lol", "airplanes.live": "..." }
}
```

Display time in **IST** (`ts` + 5.5 h).

---

## 5. REST API (`http://localhost:8000/api`)

| Method | Path | Body / params | Use in UI |
|---|---|---|---|
| GET | `/health` | | header status, mode, aircraft count, source stats |
| GET | `/aircraft`, `/cells`, `/alerts` | | same as the tick (fallback if the WS is down) |
| POST | `/mode` | `{"mode":"live"\|"replay", "speed"?, "recordings"?:[names], "start_ts"?}` | LIVE / REPLAY toggle (clears attacks + incidents) |
| GET | `/regions` · POST `/region` | `{"name":"north_india"\|"nw_border"\|"delhi"\|"all_india"}` | region picker (live mode only) |
| GET | `/recordings` | | replay file list |
| GET | `/replay` | | replay status |
| POST | `/replay/seek` | `{"ts": unix_seconds}` | timeline scrubber (attacks survive seeks) |
| POST | `/replay/speed` | `{"speed": 0.1–20}` | speed slider |
| POST | `/replay/pause` · `/replay/play` | | play/pause |
| GET / PATCH / DELETE | `/config/detection` | PATCH partial JSON, e.g. `{"nacp_bad":6}` | **sensitivity sliders**; DELETE = reset defaults; 422 if out of range |
| GET | `/attacks` | | list |
| GET | `/attacks/preview` | `?lat=&lon=&radius_km=` | **while dragging the jammer**: `busiest_cell_aircraft`, `likely_detectable`, `hint` |
| POST | `/attacks` | jamming: `{"kind":"jamming","center":[lat,lon],"radius_km":10–150,"strength":0–1,"position_loss":0–1,"duration_s":60–1800\|null}` · spoof: `{"kind":"spoof","hex":"random"\|hex,"offset_km":0–80,"bearing_deg":0–359,"alt_offset_ft":-4000–4000,"duration_s":30–1800\|null}` | create attack; 409 if no aircraft to spoof |
| PATCH | `/attacks/{id}` | any of `active, duration_s, center, radius_km, strength, position_loss, hex, offset_km, bearing_deg, alt_offset_ft` | slider moves (debounce 300 ms) |
| DELETE | `/attacks/{id}` · `/attacks` | | remove one / **Reset** all (map clears immediately) |
| GET | `/incidents` · `/incidents/{id}` | | list / detail incl. aircraft table |
| GET | `/incidents/{id}/report.pdf` | | **Download report** button (open as link) |
| GET | `/evaluation` | | `{events, detected, missed, undetectable, pending, detection_rate, unexplained_alarms, median_time_to_detect_s, per_event[]}` |
| GET | `/scenarios` · POST `/scenarios/{id}/run` | `demo1` | "Run scripted demo" button |
| POST | `/sentinel` | ESP32 packet | (firmware uses it) |
| GET | `/sentinel/latest` · `/sentinel/history?id=sentinel-1&minutes=5` | | sentinel charts (history for SNR / satellite lines) |

**Detection sliders** (field: range, default): `nacp_bad` 5–9 (7), `min_aircraft` 2–6 (3), `jam_window_s` 300–1800 (1200), `h3_res` 2–4 (3), `spoof_cell_min_flags` 1–5 (2).

**Behaviours the UI must respect:**
- Attacks only affect data arriving **after** they're created, so effects appear within ~10 s. In replay, keep playing during the simulator demo.
- `PATCH active:false` = jammer "switched off" (the area recovers over the 20-min window, realistically). `DELETE` = undo (clears at once). Offer both: **Switch off** and **Remove**.
- A spoof with `offset_km` > 0 turns its hexagon purple. An **altitude-only** spoof flags just the aircraft (by design: one aircraft with weak evidence isn't enough).
- Changing `h3_res` changes hexagon size on the next tick; redraw from the tick.

---

## 6. Screens

### Global layout (desktop, 1366×768 minimum; projector-friendly)
- **Top bar:** product name · LIVE/REPLAY badge (+ toggle) · clock in IST · aircraft count · connection dot · tabs **Airspace | Attack Simulator | Ground Sentinel** · Evaluation button.
- **Main:** map ~70% width, side panel ~30%.
- **Bottom of map:** legend (colour + text) and data credits.

### 6.1 Live Airspace (default tab)
- **Map layers, in this order:**
  1. hexagons (fill by state, opacity ~0.35; grey `insufficient` only at low opacity, or behind a toggle)
  2. incident jammer circles (dashed, labelled "approximate area for investigation")
  3. early-warning dashed paths to `entry`
  4. aircraft icons rotated by `track`: normal = neutral, `bad` = amber outline, `spoof` (strong reasons) = purple outline, `pos_lost` = hollow icon "last known position", `injected` = small orange "INJECTED" tag
  5. sentinel pin (Chennai)
- **Click an aircraft:** popup with flight, altitude, speed, NIC/NACp, source, age, bad/spoof reason.
- **Click a hexagon:** `n_aircraft`, `n_bad`, share bad, reasons, and the state in words ("Not enough aircraft to decide" for insufficient).
- **Side panel:** alert cards (newest / soonest ETA first): kind tag (EARLY WARNING / SENTINEL), message, ETA countdown, INJECTED badge if `injected`. Below them, the incident list: kind, opened time IST, aircraft count, open/closed, **Download report (PDF)**, and a click to zoom the map to it.
- **Replay controls** (replay mode): play/pause, speed 1–20×, a timeline scrubber (`t_start`…`t_end`, `progress`), and a "Recording: 11 Oct 19:00–22:00 IST" label.

### 6.2 Attack Simulator (the judge-facing centrepiece)
Same map; the side panel becomes controls. Big banner on top: **"Attacks are simulated data only. Nothing is transmitted."**
- **Jamming:** click the map to place the jammer (draggable marker + circle). Sliders: Radius 10–150 km (60), Strength 0–100% (70), Position loss 0–100% (30), Duration 1–30 min or "until switched off". **While dragging, call `/attacks/preview`** and show "Aircraft under jammer: N · busiest hexagon: M", plus the `hint` when it's not detectable. Buttons: **Start**, **Switch off**, **Remove**.
- **Spoofing:** "Pick aircraft" (click a plane) or Random. Sliders: Position offset 0–80 km (25), Direction 0–359° (45), Altitude offset −4000…+4000 ft (0). **Spoof now**.
- **Detection sensitivity** (collapsible): NACp threshold, Min aircraft per hexagon, Window, Cell size, with live readouts so judges see the catch-more vs false-alarm trade-off. "Reset to defaults".
- **Active attacks list** with remaining time, plus **Reset all**.
- **Run scripted demo** (`demo1`).
- Every injected thing on the map carries the orange **INJECTED TEST ATTACK** badge.

### 6.3 Ground Sentinel
- Big status card from `server_status`: OK (green) / SEARCHING (blue-grey, "no satellite fix yet") / JAMMING (red) / SPOOF (purple) / OFFLINE (grey), always with the word, plus `server_reason`.
- Live line charts over the last 5 min (`/sentinel/history`, poll every 2 s or build from ticks): `avg_snr` with a dashed `baseline_snr` line, and `sats_used`. The foil test shows a clear cliff.
- Per-satellite SNR bar list from `snr_list`.
- Event log: "20:41:05 signal 14 dB below baseline: JAMMING (antenna covered test)".
- Label everything "SIGNAL TEST": it's a demo of the method, not a detected real attack.

### 6.4 Evaluation (modal)
Big numbers: **Detected X / Y**, median time to detect, undetectable (too few aircraft), unexplained alarms on real data. Per-event table. Footnote: "Unexplained alarms on live data may be real interference; they are not counted as false alarms."

---

## 7. Visual style

- Matches the pitch deck: **dark navy** UI (e.g. `#0B1B33` / `#0F2440`), **frost-white** cards/text, **one signal-orange accent** (`#F26B1D`) for injected/simulator/CTA.
- State colours (map + chips): clear green `#2EAF6E` · degraded amber `#E8A33C` · jammed red `#E5484D` · spoofing purple `#9B5DE5` · insufficient grey `#6B7A90` (low opacity). **Always paired with a text label.**
- No nested boxes-in-boxes, no gradients-everywhere "AI look" (the team rejected that in the deck). Flat, calm, readable on a projector: large type for numbers, generous spacing.
- **Basemap:** CARTO dark tiles (`https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png`, with attribution). If tiles fail (venue Wi-Fi), the map must still show hexagons and aircraft on the navy background. Check how the basemap draws the J&K boundary before the demo; if it differs from India's official map, hide the basemap (hexagons + a simple outline) or use satellite imagery.
- Initial view: centred ~(30.5, 75.5), zoom 6, so Delhi, Punjab, J&K and Islamabad are visible.

---

## 8. Suggested structure (`web/`)

```
web/
  src/
    main.jsx, App.jsx
    api/client.js          // fetch helpers for /api/*
    api/useLiveFeed.js     // WebSocket hook -> zustand store (reconnect + backoff)
    store.js               // zustand: tick, connection, selected aircraft/cell/incident, ui tab
    components/
      TopBar.jsx, Legend.jsx, Credits.jsx, InjectedBadge.jsx
      map/MapView.jsx, CellsLayer.jsx, AircraftLayer.jsx, WarningPaths.jsx, IncidentCircles.jsx, JammerEditor.jsx
      panels/AlertsPanel.jsx, IncidentsPanel.jsx, ReplayControls.jsx
      simulator/SimulatorPanel.jsx, SensitivityPanel.jsx
      sentinel/SentinelView.jsx
      EvaluationModal.jsx
```
Packages: `react-leaflet leaflet zustand` (+ `recharts` for sentinel charts). Aircraft icon: a small SVG plane rotated with CSS `transform: rotate(track deg)`. Render ~100 aircraft and ~60 hexagons every 5 s; keep the layers memoized by id so the map doesn't flicker.

Build order (stop at any point with something demo-able):
1. WebSocket hook + store + map with hexagons + aircraft + legend.
2. Alerts and incidents panels + PDF link.
3. Attack Simulator (jammer place/drag + preview + sliders + reset).
4. Replay controls + LIVE/REPLAY toggle.
5. Ground Sentinel tab.
6. Evaluation modal, spoof controls, sensitivity sliders, polish.

---

## 9. Hard rules (judges and data licences)

- **Receive-only:** never imply we transmit. Warnings go "to controllers / the dashboard", never "to aircraft".
- Every injected effect shows **INJECTED TEST ATTACK**; the simulator banner says data only.
- Never say who is jamming. The circle is an **"approximate area for investigation"**.
- Colour is never the only signal; always add text.
- **Credits visible:** "Aircraft data: adsb.fi · adsb.lol" with links (adsb.fi terms require it).
- The UI must survive: WS disconnect (reconnect badge), empty data ("Waiting for data…"), map tiles failing.

---

## 10. Demo & pitch (what the frontend must make possible)

**3-minute script:**
1. **Hook (15 s):** 923 GNSS interference reports in India, Feb 2024–Feb 2025, 63% in the Amritsar–Jammu belt; a crew got a false "PULL UP" warning.
2. **Insight (20 s):** every plane broadcasts how much it trusts its GPS; several planes losing trust in one place = interference. "Every aircraft is a sensor for the ones behind it."
3. **Real proof (40 s):** replay of 11 Oct: our system flagged GPS degradation on 4 aircraft near Islamabad (~100 km from the LoC), and the GPSJam 10 Oct map shows the same area red. GPSJam is daily and late; ours took minutes.
4. **Judge attacks (50 s):** they place a jammer (near Delhi, where traffic is dense) → red within seconds → incoming-flight warning with ETA → Download PDF. If they click Amritsar → "Not enough aircraft": the honest limit, which leads into the sentinel.
5. **Ground Sentinel (30 s):** cover the antenna → buzzer + dashboard red. Boxes at border airports cover where aircraft data goes blind.
6. **Close (25 s):** receive-only, evaluation numbers, next step: sentinels at Amritsar/Jammu/Srinagar + NavIC cross-check. "We can't stop jamming, but no pilot should be surprised by it."

**Solution in one sentence:** today interference is discovered by pilots when GPS fails and reported by hand afterwards; we give a live, shared early-warning picture from data aircraft already broadcast, at near-zero cost.

**Judge Q&A:**
- *AI?* No: statistics + physics rules, every alarm explainable.
- *One faulty plane?* A hexagon needs several different planes; fewer than 3 = "not enough data".
- *Why nothing at Amritsar?* Free data is too sparse there; that's why the sentinel exists.
- *vs GPSJam?* Daily and a day late vs minutes; plus jamming vs spoofing, warnings, reports.
- *Did you jam anything?* Never; receive-only, all attacks are labelled fake data.
- *Why the Ground Sentinel?* Aircraft cover the busy sky; sentinels cover border airports, villages, nights, and give our own independent data.
- *Do you alert planes?* We warn controllers/airlines, who tell crews.

**Before judging:** rehearse 3× with a timer · record a backup video of the full demo · freeze code 2 h before · keep the recorder data on a USB stick.

---

## 11. Known limits (say them before judges find them)

- Coverage is thin near the border and in J&K (2–6 aircraft in 150 NM measured), so many hexagons are "insufficient".
- Early warning is a straight-line projection; turning or descending aircraft may not follow it.
- Detection is from public hobbyist data (delays of seconds; feeders can drop out).
- The sentinel is a ₹1,000 prototype on a table in Chennai: it demonstrates the method, not border coverage.
- The jammer area is approximate (tens of km), for investigation only.

---

## 12. Workflow

1. In VS Code (Claude Code): `git checkout main && git pull`, then `git checkout -b feat/web`.
2. Build in `web/`. Never commit `node_modules/` (already in `.gitignore`).
3. `git add -A && git commit -m "..." && git push origin feat/web`.
4. In the claude.ai project chat: **"review feat/web"**. It gets pulled, checked against this file and merged to `main`.
5. Backend changes needed by the frontend (a missing field, an endpoint): ask in the project chat; don't patch the backend from the frontend branch.

---

## 13. Backend additions (12 Oct, branch `fix/backend-audit`)

Nothing was renamed or removed; these fields and endpoints were **added**.

**Tick payload (`/ws`)**
- `cells.features[].properties.injected` (bool): any simulated effect in this hexagon -> show **INJECTED TEST ATTACK**. Use this, not `n_injected == n_bad`.
- `cells.features[].properties.mixed` (bool): simulated and real (non-injected) problems together -> e.g. "INJECTED TEST ATTACK + real degradation".
- `alerts[].mixed` (bool; always `false` on sentinel alerts). `alerts[].injected` is now true whenever the alarm cell has any simulated effect (spoof-caused warnings included).
- `incidents_summary[].mixed` (bool). `incidents_summary[].injected` is now true if any affected aircraft was simulated.
- `aircraft[].spoof` can contain `"feed_glitch"`: info only, like `"recovery_jump"` (a data-feed hiccup, not spoofing). Outline purple only for the strong reasons.
- `replay.last_error`, `replay.last_error_ts`: the newest error inside playback (playback carried on). Show it small, e.g. in the replay bar.
- Incident ids now look like `inc-r044537-1` (run id inside); treat them as opaque strings.

**REST**
- `GET /api/cells/{h3}/summary` and `GET /api/incidents/{id}/summary` -> `{id, summary, source: "ai"|"template", model, label, generated_ts, cached, facts}`. Show `summary` with `label` ("AI-written summary" or "Auto summary") as a caption, e.g. in the hexagon popup and the incident card. 404 = not in the current state. Can take a few seconds when the AI answers: show a spinner, call it on click (not every tick).
- `GET /api/alerts?active=false` -> alerts that have ended (`first_ts`, `last_ts`, `ended_ts`); `active=true` (default) = current alerts.
- `GET /api/health` gains `last_error`, `last_error_ts` (ingest) and `ai: {enabled, key_present, models, last_model_used, last_error}`.
- `PATCH /api/attacks/{id}` with `"hex": "random"` now picks a real airborne aircraft (409 if none). A `null` value leaves the field unchanged (except `duration_s`: null = until switched off); NaN/inf -> 422.
- `GET /api/attacks/preview` needs `radius_km` 10-150 and a valid lat/lon (422 otherwise), like the jammer slider.
- `POST /api/scenarios/{id}/run`: a broken scenario file or event -> 422 with a message naming the event and field.
- The incident PDF now has the summary (with its label) under the title, and the "Also contains real (non-injected) degradation" line when `mixed`.
