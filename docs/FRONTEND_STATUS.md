# Frontend status and handover (web/), 12 Oct 2026

Read this first when continuing the frontend in a new chat. The original spec is `docs/FRONTEND_HANDOVER.md`; this file says what was actually built, what changed from it, and what is left. Where they disagree, this file wins.

## 1. State of play

- Built by Claude (claude.ai project chat) and merged to `main` as PR #1 (merge `51f2228`). Everything lives in `web/`; the backend was not touched.
- Stack (pinned): React 18.3.1, Vite 5.4.21, Tailwind 3.4.19, react-leaflet 4.2.1, leaflet 1.9.4, zustand 4.5.7, h3-js 4.5.0, vite-plugin-singlefile 2.3.3, Mukta + B612 fonts via @fontsource (offline).
- `npm run build` passes. There are no automated frontend tests; it was checked by driving it in a real browser (Playwright) at desktop and phone width.
- Tested against the backend as it was before the audit merge (`8f21a5e`, D19-D22). **Not yet re-tested against the merged backend**: do that first (section 8).
- Preview without a laptop: artifact "SENTINEL Dashboard" (single HTML file, standalone mode).

## 2. Run

```bash
cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000     # backend first
cd web && npm install && npm run dev                                # http://localhost:5173
npm run dev -- --host                                               # second laptop on the hotspot
BACKEND_URL=http://192.168.1.20:8000 npm run dev                    # backend elsewhere
npm run dev:standalone   /   npm run build:standalone               # no backend: dist-standalone/index.html
```

The dev server proxies `/api` and `/ws`. `?nointro` skips the intro, `?intro` forces it.

## 3. What the user sees (flow)

1. **Intro** (`Splash.jsx`): rabbit-light runway, a plane parked far away. Nothing moves until the user clicks **Enter dashboard** (or presses Enter); then the plane flies toward the viewer (2.4 s) and the dashboard opens. **Skip intro** / Esc skip it. Plays once per browser tab (sessionStorage `sentinel:intro-seen`).
2. **Main dashboard** (`HomeView.jsx`): three boxes, Live airspace, Attack simulator, Ground sentinel, each with a live status line. The **SENTINEL** wordmark (top left) always returns here. **Log out** shows the intro again (there are no accounts; it only closes the dashboard).
3. **Live airspace**: map + side panel. Hexagons coloured by state with word labels; aircraft; early-warning paths; incident circles. Click a hexagon: plain-language header ("about 15 km south of Gurdaspur, Punjab", how wide it is, what the state means), facts, aircraft, linked incident + PDF, **Summary** button. Under the map: replay play/pause, speed 1/2/5/10/20x, timeline scrubber (or live source status and region picker if the backend runs live).
4. **Attack simulator**: jammer (click map or drag; default 80 km / 80 %, preview, debounced updates), spoofing, active attacks (switch off / remove), sensitivity sliders, scripted demo runner.
5. **Ground sentinel**: **Live / Attack** switch.
   - *Live*: real box via the backend. Status card (server's own check), facts, 5-minute charts (average signal with normal and alarm lines, satellites used), per-satellite bars, event log. Bars are **green >= 35 dB-Hz (Strong), yellow 28-35 (Medium), red < 28 (Weak)**, always with the word.
   - *Attack*: browser-only simulator, never sent to the backend. 9 named example satellites (GPS G05/G12/G25, Galileo E11/E24, GLONASS R07/R18, BeiDou C21/C34) with a slider each, a "lower every satellite by" slider and presets (Healthy, Weaker by 10 dB, Jam: 20 dB down). Same rule as `backend/app/sentinel.py` (average signal below 22 dB-Hz = jamming; a lost fix alone is not). A fix needs >= 4 satellites above 20 dB-Hz (our assumption). Tagged INJECTED TEST ATTACK. Spoofing is not simulated here.
6. **Evaluation** modal (top bar): detected / missed / undetectable / pending / unexplained.

## 4. Where things are

| Area | Files |
|---|---|
| Shell, intro, routing by `tab` in the store | `src/App.jsx`, `src/components/Splash.jsx`, `TopBar.jsx`, `HomeView.jsx` |
| Feed and API | `src/api/useLiveFeed.js` (WS `/ws`, backoff reconnect), `src/api/client.js` (every REST call, `setTransport` for standalone) |
| State | `src/store.js` (zustand; per-tick memoised `derive()`; `replayOverride` for instant speed/pause; toasts; selection; detection config) |
| Map | `src/components/map/*` (own offline outline `src/data/south-asia.json` = Natural Earth 10m, India point of view; optional CARTO "Streets" tiles toggle) |
| Panels | `src/components/panels/*` (AirspacePanel, AlertsPanel, IncidentsPanel, CellDetail, ReplayControls, `useDataClock.js`) |
| Simulator | `src/components/simulator/*` |
| Ground sentinel | `src/components/sentinel/SentinelView.jsx`, `LineChart.jsx` (SVG, no chart library), `simStore.js` (Attack mode) |
| Words, colours, places | `src/lib/states.js` (state colours + labels), `src/lib/satellites.js` (names, bands), `src/lib/geo.js`, `src/lib/time.js`, `src/data/places.js` (~70 towns for plain-language locations), `src/data/airports.js` |
| Standalone (no backend) | `src/standalone/*`: JS copy of the detectors + a replay engine over `sample-records.json.gz`, simulated attacks and a simulated box |

## 5. Rules that must keep holding

Receive-only (never imply transmitting). Every simulated thing carries the orange INJECTED TEST ATTACK badge; orange means simulated and nothing else. State colours are never shown without their word. adsb.fi and adsb.lol are credited. Jammer location is "approximate area for investigation", never a claim of who. The UI must survive WS disconnect, empty data and tile failure. Keep the basemap tiles off for the judged demo (provider boundaries differ).

## 6. Decisions and deviations from FRONTEND_HANDOVER.md

- Main dashboard of three boxes added (not in the spec); tabs still exist in the top bar.
- Replay/Live toggle removed from the UI (user request). Mode is whatever the backend starts in (`GAW_MODE`); `POST /api/mode` still exists but nothing calls it.
- "AI summary" is called just **Summary** in the UI (user request). The small footnote shows the backend's `label` ("AI-written summary" or "Auto summary") so a reader can tell which it is.
- Default jammer 80 km / 80 % (measured: 60 km / 70 % over the Delhi approach stayed amber for minutes).
- Hexagon detail is written for non-experts: place names from `places.js` (display only, not detection), width in km, one-sentence meaning per state.
- Replay speed buttons respond instantly via an optimistic `replayOverride`, cleared when a tick agrees.
- Plain-language wording lives next to the code that shows it (`CellDetail.jsx` `PLAIN`, `states.js`).

### Changes on 12 Oct (branch `feat/airspace-cleanup`)

- **Live airspace never shows simulated attacks.** The backend runs the detectors twice per tick; `tick.real` holds cells, aircraft, alerts and incidents from pristine records (incident ids `air-…`). `store.viewTick(tick, view)` / `useViewTick()` / `useDerived()` pick the view by tab: Attack simulator = full tick, everything else = `tick.real`.
- **Live / Replay switch** is back, inside Live airspace (bottom bar). It calls `POST /api/mode`, which also clears simulator attacks and incident lists (confirm dialog when attacks are running).
- **Click an incident = replay it**: `lib/incidents.replayIncident` zooms to it and seeks to 90 s before it opened (in live mode it switches to replay at that time). A banner on the map counts down to its start. Incident start times are dots on the replay timeline. The backend now continues the same incident when replay re-detects it (no duplicates on seek or loop).
- **Map declutter**: incident = small "Jammed #N" chip (+ dashed circle), details in its tooltip; hexagons inside an open incident get no extra label below zoom 8; amber labels only from zoom 8; grey "too few aircraft" hexagons hidden by default; clear hexagons faint; airports are dots with city names only for major ones at zoom 6; planes smaller at country zoom and healthy ones dimmed; plane symbol key collapsed in the legend.
- **Incident cards**: place name as the title, Started / Lasted / Aircraft hit, Replay + PDF buttons.
- **PDF** redesigned (backend `report/pdf.py`): header band with status, key-number tiles, one summary, plain-language reasons, Real/Injected column, page footer.

## 7. Known limits

- The feed ticks every 5 s, so at 20x each aircraft jump covers about 100 s of flight. Fix needs a backend change (tick sooner after a speed change, or a faster tick); do not patch it in the frontend.
- Real satellite names need the firmware to send `sat_ids` next to `snr_list` (strings like `"G12"` or NMEA PRNs: 1-32 GPS, 65-96 GLONASS, 201-237 BeiDou, 301-336 Galileo; same order). The backend keeps extra fields. Until then Live bars read "Satellite 1..N".
- Place names cover about 70 towns (North India, Pakistan, Nepal); far-away hexagons read "about N km direction of <nearest listed town>".
- `GET /api/incidents/{id}/summary` exists but the UI does not use it yet (PDF already embeds it).
- Sentinel Attack mode is not visible to Home, the map, or backend alerts (by design: server needs 120 s to learn a new box's baseline).
- Standalone build: no PDFs, no live data, no summaries. A teaching and backup tool, not the judged demo.
- Possible hackathon-rule question: code written before the 08:00 start on 12 Oct. Ask the organisers if it matters.

## 8. Next steps, in order

1. Run backend (merged `main`) + `npm run dev`; click through all three sections once. Check: tick arrives, hexagon Summary returns text (set `GEMINI_API_KEY` in `backend/.env` for AI text; without it you get the template), PDF downloads, scenario runner works.
2. With the real ESP32: confirm `sentinel-1` shows in Live, cover the antenna with foil, expect JAMMING within about 2 minutes after the baseline is learned. Ask firmware to add `sat_ids`.
3. Dry-run the judged demo from `README.md` "Demo notes" (Reset all between runs, keep replay playing while attacking).
4. Optional: wire `incidents/{id}/summary` into the incident row; show `feed_glitch` / D20 info if wanted; backend tick-rate fix for high replay speeds.

## 9. Starting a new chat cheaply

Tell Claude: "Read `docs/FRONTEND_STATUS.md`, `CLAUDE.md` and `web/README.md`, then do <one task>." That is enough context; no need to carry the old conversation. Work on a `feat/<thing>` branch, `npm run build` before pushing, Rakesh merges.

## 10. Git

`main` has the frontend (PR #1) and the backend audit merge. Frontend commits start with `web:`. Never commit `web/dist`, `web/dist-standalone` or recordings.
