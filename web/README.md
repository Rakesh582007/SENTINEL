# web/ — dashboard (not started)

React + Vite + Tailwind + react-leaflet (HANDOVER §9). Build it against the backend that already runs:

- Live feed: `ws://localhost:8000/ws`, one JSON message per detector tick (every 5 s). The shape is in `CLAUDE.md` → "Tick payload". The newest tick arrives the moment you connect.
- REST: `http://localhost:8000/api/...`. Interactive docs: http://localhost:8000/docs.
- Cells arrive as a GeoJSON FeatureCollection with `[lon, lat]` rings, so the browser does no H3 maths.

Must-haves from the spec: state colours always paired with text (clear / degraded / jammed / spoofing / insufficient), the "INJECTED TEST ATTACK" badge on anything with `injected`, data credits for adsb.fi and adsb.lol, and a plain dark background if map tiles fail (venue Wi-Fi). Check how the basemap draws the J&K boundary before the demo.

Attack Simulator: while the judge drags the jammer, call `GET /api/attacks/preview?lat=&lon=&radius_km=` and show `busiest_cell_aircraft` and `hint`, so an empty area explains itself instead of looking broken.
