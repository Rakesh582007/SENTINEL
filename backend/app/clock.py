"""One source of "now" for the whole backend.

Live mode: the wall clock. Replay mode: the timestamp the replay has reached.
Every time-based rule (detection windows, attack durations, incident closing,
ETAs) must call clock.now(); calling time.time() directly breaks replay,
especially at 20x speed or after a seek.
"""
from __future__ import annotations

import time


class Clock:
    def __init__(self) -> None:
        self.mode = "live"
        self._sim_ts: float | None = None

    def now(self) -> float:
        if self.mode == "live" or self._sim_ts is None:
            return time.time()
        return self._sim_ts

    def use_live(self) -> None:
        self.mode = "live"
        self._sim_ts = None

    def use_replay(self, ts: float) -> None:
        self.mode = "replay"
        self._sim_ts = float(ts)

    def set(self, ts: float) -> None:
        """Move replay time (forwards while playing, anywhere on a seek)."""
        self._sim_ts = float(ts)
