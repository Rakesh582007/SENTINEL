# web/ — SENTINEL dashboard

React 18 + Vite 5 + Tailwind 3 + react-leaflet 4 + zustand. Spec: [`docs/FRONTEND_HANDOVER.md`](../docs/FRONTEND_HANDOVER.md).
Light blue + beige, taken from aeronautical charts; orange only ever means "simulated (injected) data".

## Run it

```bash
# backend first (repo root): cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000
cd web
npm install
npm run dev            # http://localhost:5173
```

The dev server proxies `/api` and `/ws` to `http://localhost:8000`, so there is no CORS to configure and a second laptop on the hotspot can open `http://<this-laptop-ip>:5173` (start with `npm run dev -- --host`). Backend elsewhere: `BACKEND_URL=http://192.168.1.20:8000 npm run dev`.

Intro: plays once per browser tab. `?nointro` skips it, `?intro` forces it. Enter or Esc also skip.

## Without the backend (standalone)

```bash
npm run dev:standalone      # same UI, backend copied into the browser
npm run build:standalone    # one self-contained file: dist-standalone/index.html
```

Standalone mode replays the bundled real sample (`data/sample`, 11 Oct 12:21–12:39 IST) through a JavaScript copy of the detectors in `src/standalone/` (same thresholds, same tick shape), with simulated attacks and a simulated Ground Sentinel. A permanent banner says so. No PDF reports, no live data, no AI summary. Use it for UI work and as a backup recording aid, never as the judged demo. Regenerate the sample after changing the normalizer: `python web/scripts/export_sample.py`.

## Where things are

| Screen | Code |
|---|---|
| Intro (plane on final approach, "Enter dashboard") | `src/components/Splash.jsx` |
| Top bar: tabs, Replay/Live (confirms first), IST data clock, connection, Evaluation | `src/components/TopBar.jsx` |
| Map: outline basemap (works offline, India's official boundary), hexagons, aircraft, paths, circles | `src/components/map/*` |
| Live airspace panel: early warnings, incidents + PDF, hexagon detail + AI summary | `src/components/panels/*` |
| Attack simulator: jammer place/drag/preview, spoofing, active attacks, sensitivity, scripted demo | `src/components/simulator/*` |
| Ground sentinel: status, signal charts, per-satellite bars, event log | `src/components/sentinel/*` |
| Evaluation modal | `src/components/EvaluationModal.jsx` |
| Feed + API | `src/api/useLiveFeed.js`, `src/api/client.js`, `src/store.js` |

## Demo notes (measured on the bundled sample with the real backend)

- Default jammer is **80 km / 80 %**. The handover's 60 km / 70 % over the Delhi approach stayed amber (5 of 38 bad) for over two minutes; 80 km / 80 % turned it red in one tick (15 of 28).
- Keep the replay playing while attacking: attacks only change data that arrives after them.
- Spoof targets change from their next report, usually 10–30 s.
- Use **Reset all** between runs, and switch mode once before the evaluation slide so the numbers start clean (each replay loop reopens live attacks as new events).
- The basemap is our own outline (Natural Earth, India point of view). "Streets" tiles need internet and draw the provider's boundaries; keep them off for the judged demo.

## AI summary (backend still to build)

The hexagon detail calls `GET /api/cells/{h3}/summary` and shows "Not connected yet" on 404/405/501. Expected answer:

```json
{ "h3": "833da1fffffffff", "summary": "Plain-English note…", "model": "gemini-…", "generated_ts": 1791707467.5 }
```

Give the model only the facts the UI already shows (cell stats, reasons, aircraft, linked incident), tell it never to name a cause or a country, and fall back to a template sentence when the API is unreachable (venue Wi-Fi). Detection itself stays rule-based.

## Backend gaps found while building (for the backend chat)

1. Purple (spoof) hexagons report `n_injected: 0`, and their early warnings `injected: false`, because `n_injected` only counts jamming-style bad aircraft. The UI works around it (a hexagon is injected if a spoofed aircraft with an attack id is inside it).
2. `compute_tick` overwrites a jammed hexagon with `spoofing` when a spoofed aircraft is in it, so that jammer logs no "entered jammed" detection while the spoof lasts.
3. Spoof incidents take the aircraft's earliest record in the hexagon, so `first_bad_ts` can be before the attack started.
4. `likely_detectable` only checks the busiest hexagon has `min_aircraft`; it ignores dilution by the 20-minute window, so a weak jammer can stay amber while the preview says detectable.
5. Detections are logged on state changes only: removing and re-creating a jammer within one 5 s tick leaves no new "entered jammed" event.
6. Evaluation coverage reads current attacks only, so a removed jammer loses `max_aircraft_inside`.
7. `scenarios/demo1.json` still says the scenario runner is TODO; it works.

## Ground sentinel: Live and Attack

- **Live** reads the real box through the backend (`tick.sentinel`, `GET /api/sentinel/history`). Bars are green (35 dB-Hz or more), yellow (28 to 35) or red (under 28), always with the word Strong / Medium / Weak.
- Satellite names (GPS G12, Galileo E11, ...) need the firmware to add `sat_ids` next to `snr_list`: either strings like `"G12"` or NMEA PRN numbers (1-32 GPS, 65-96 GLONASS, 201-237 BeiDou, 301-336 Galileo), same order as `snr_list`. The backend keeps extra fields (`extra="allow"`). Without it the bars are numbered "Satellite 1..N".
- **Attack** is a browser-only simulator (`simStore.js`): per-satellite dB sliders, same rules as `backend/app/sentinel.py` (10 dB under normal, or fix lost for more than 5 s). A fix needs 4 satellites above 20 dB-Hz (our assumption). Nothing is sent to the backend; everything is tagged INJECTED TEST ATTACK. Spoofing is not simulated there.
