"""Live poller: every sweep asks each source about each query circle.

Feeds Runtime.on_live_answer(), which normalises, injects simulated attacks,
adds to the window and (by default) appends the raw answer to a recording in
the same format as scripts/record.py. So when the app runs in live mode,
stop the standalone recorder: one poller is enough and halves the API load.
"""
from __future__ import annotations

import asyncio
import logging
import time

import httpx

from app.ingest.sources import USER_AGENT, build_url, due
from app.regions import SWEEP_INTERVAL_S

log = logging.getLogger("gaw.poller")


class LivePoller:
    def __init__(self, rt) -> None:
        self.rt = rt
        self.cooldown_until: dict[str, float] = {}
        self.fail_streak: dict[str, int] = {}
        self.sweeps = 0

    def _backoff(self, source: str, status: int) -> None:
        if status == 200:
            self.fail_streak[source] = 0
            return
        streak = self.fail_streak.get(source, 0) + 1
        self.fail_streak[source] = streak
        if status == 429:
            self.cooldown_until[source] = time.monotonic() + 120
        elif streak >= 3:
            self.cooldown_until[source] = time.monotonic() + min(600, 30 * 2 ** (streak - 3))
        log.warning("%s failed (status %s, streak %s)", source, status, streak)

    async def run(self) -> None:
        s = self.rt.settings
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=s.http_timeout_s, headers=headers) as client:
            while True:
                sweep_start = time.monotonic()
                self.sweeps += 1
                for point in list(self.rt.points):
                    for source in list(self.rt.sources):
                        if self.cooldown_until.get(source, 0.0) > time.monotonic() or not due(source, self.sweeps):
                            continue
                        t0 = time.monotonic()
                        try:
                            resp = await client.get(build_url(source, point))
                            status = resp.status_code
                            data = resp.json() if status == 200 else None
                            err = None if status == 200 else f"HTTP {status}"
                        except Exception as e:  # network errors, bad JSON
                            status, data, err = 0, None, f"{type(e).__name__}: {e}"
                        ms = (time.monotonic() - t0) * 1000
                        ok = status == 200 and isinstance(data, dict)
                        if status == 200 and not ok:
                            data, err = None, "unexpected JSON shape"
                        self.rt.on_live_answer(time.time(), source, point, status, ms, err, data)
                        self._backoff(source, 200 if ok else (status if status != 200 else 0))
                        await asyncio.sleep(s.request_spacing_s)
                interval = s.sweep_interval_s or SWEEP_INTERVAL_S.get(self.rt.region_name, 10.0)
                await asyncio.sleep(max(0.0, interval - (time.monotonic() - sweep_start)))
