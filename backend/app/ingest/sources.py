"""ADS-B aggregator endpoints and a stdlib HTTP fetch.

Stdlib only: the standalone recorder uses this before any `pip install`.
The FastAPI live poller builds the same URLs but fetches with httpx.

Measured 11 Oct 2026 ~12:14 IST (Sunday midday), aircraft per query:

    point             adsb.fi  adsb.lol  union
    Amritsar 250 NM      42        18      44
    J&K      150 NM       2         1       3
    Delhi    150 NM      50        12      51
    Mumbai   150 NM      10        23      23
    Chennai  150 NM      22        27      30

The two aggregators are fed by different receivers, so the backend polls
BOTH and merges by aircraft hex (freshest position wins). In North India
adsb.fi sees 2-4x more aircraft than adsb.lol.

Facts checked the same day:
- Both return the ADSBexchange-v2 shape: {ac, msg, now, total, ctime, ptime}.
- `now` is in MILLISECONDS for both.
- adsb.fi: use v3 (/api/v3/lat/../lon/../dist/..). The v2 lat/lon/dist
  endpoint is deprecated and returns a different shape. Public limit is
  1 request/second; 4xx responses count against it. Terms: personal,
  non-commercial use, and the UI must credit adsb.fi with a link.
- adsb.lol: rate limits are dynamic; the project says an API key (obtained
  by feeding) will be required "in the future" -> keep adsb.fi working.
- airplanes.live returned HTTP 403 from a cloud sandbox; may work from a
  home connection, so it is available but off by default.
"""
from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.request

from app.regions import QueryPoint

SOURCES: dict[str, str] = {
    "adsb.fi": "https://opendata.adsb.fi/api/v3/lat/{lat}/lon/{lon}/dist/{radius}",
    "adsb.lol": "https://api.adsb.lol/v2/point/{lat}/{lon}/{radius}",
    "airplanes.live": "https://api.airplanes.live/v2/point/{lat}/{lon}/{radius}",
}
DEFAULT_SOURCES: tuple[str, ...] = ("adsb.fi", "adsb.lol")

ATTRIBUTION: dict[str, str] = {
    "adsb.fi": "https://adsb.fi",
    "adsb.lol": "https://adsb.lol",
    "airplanes.live": "https://airplanes.live",
}

USER_AGENT = "gps-attack-watch/0.1 (SEDHACKS26 Team Ethicals; student project; receive-only)"


def build_url(source: str, point: QueryPoint) -> str:
    try:
        template = SOURCES[source]
    except KeyError:
        raise KeyError(f"unknown source {source!r}; choose from {sorted(SOURCES)}") from None
    return template.format(lat=f"{point.lat:.4f}", lon=f"{point.lon:.4f}", radius=int(point.radius_nm))


def fetch_json(url: str, timeout: float = 15.0, user_agent: str = USER_AGENT) -> tuple[int, dict | None, str | None, float]:
    """GET a JSON document with the standard library.

    Returns (http_status, parsed_json_or_None, error_or_None, elapsed_ms).
    http_status is 0 when the request never got an HTTP answer (DNS, timeout, offline).
    """
    t0 = time.monotonic()
    req = urllib.request.Request(
        url, headers={"User-Agent": user_agent, "Accept": "application/json", "Accept-Encoding": "gzip"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            if resp.headers.get("Content-Encoding", "").lower() == "gzip":
                body = gzip.decompress(body)
            status = resp.status
    except urllib.error.HTTPError as e:
        return e.code, None, f"HTTP {e.code}", (time.monotonic() - t0) * 1000
    except Exception as e:  # URLError, timeout, connection reset ...
        return 0, None, f"{type(e).__name__}: {e}", (time.monotonic() - t0) * 1000
    elapsed = (time.monotonic() - t0) * 1000
    try:
        return status, json.loads(body), None, elapsed
    except ValueError as e:
        return status, None, f"bad JSON: {e}", elapsed
