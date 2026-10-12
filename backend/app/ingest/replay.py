"""Replay: stream recorded API answers through the exact same pipeline as live.

Load hourly recording files -> normalise -> sort by poll time -> emit frames
as replay time advances at `speed` x real time. The Runtime clock follows the
replay time, so every detector, attack duration and ETA runs on recording time.

Seek (timeline scrubber, or the loop back to the start): the window and
incidents are cleared and refilled from the recording's previous
`window_keep_s`, so the map is never empty after a jump. Simulated attacks
stay on: their timers are shifted to the new time and their ground-truth
events are closed and reopened, so evaluation stays consistent.
Attacks only alter records that arrive after they are created; while replay
is paused nothing new arrives, so keep it playing during the simulator demo.
"""
from __future__ import annotations

import asyncio
import bisect
import logging
import time
from pathlib import Path

from app.config import get_detection
from app.ingest.normalize import normalize_line
from app.ingest.recording import iter_recording, list_recordings
from app.records import Record

log = logging.getLogger("gaw.replay")

SAMPLE_DIR = Path(__file__).resolve().parents[3] / "data" / "sample"


def stamp_of(path: Path) -> str:
    """'rec_20261011_06_r064512.jsonl.gz' -> '20261011_06' (UTC hour)."""
    parts = path.name.split("_")
    return f"{parts[1]}_{parts[2]}" if len(parts) >= 4 else path.name


def choose_files(directory: Path, names: list[str] | None, newest_hours: float) -> list[Path]:
    """Explicit names (inside directory), else the newest N hours, else the bundled sample."""
    available = list_recordings(directory)
    if names:
        by_name = {p.name: p for p in available}
        missing = [n for n in names if n not in by_name]
        if missing:
            raise FileNotFoundError(f"not in {directory}: {missing}")
        return [by_name[n] for n in names]
    if available:
        stamps = sorted({stamp_of(p) for p in available})
        keep = set(stamps[-max(1, int(round(newest_hours))):])
        return [p for p in available if stamp_of(p) in keep]
    return list_recordings(SAMPLE_DIR)


class Replayer:
    def __init__(self, rt, files: list[Path], speed: float = 1.0, start_ts: float | None = None, loop: bool = True) -> None:
        self.rt = rt
        self.files = files
        self.speed = speed
        self.start_ts = start_ts
        self.loop = loop
        self.paused = False
        self.finished = False
        self.loaded = False
        self.error: str | None = None  # loading failed: nothing to play
        self.last_error: str | None = None  # the newest error inside playback (playback carried on)
        self.last_error_ts: float | None = None
        self.frames: list[tuple[float, list[Record]]] = []
        self.times: list[float] = []
        self.idx = 0
        self.n_records = 0

    @property
    def t_start(self) -> float:
        return self.times[0] if self.times else 0.0

    @property
    def t_end(self) -> float:
        return self.times[-1] if self.times else 0.0

    def load(self) -> None:
        frames = []
        for path in self.files:
            for line in iter_recording(path):
                recs = normalize_line(line)
                if recs:
                    frames.append((float(line["poll_ts"]), recs))
        frames.sort(key=lambda f: f[0])
        self.frames = frames
        self.times = [f[0] for f in frames]
        self.n_records = sum(len(f[1]) for f in frames)
        self.loaded = True
        if not frames:
            self.error = "no usable data in the chosen recordings (run backend/scripts/record.py first)"

    def segments(self) -> list[tuple[float, float]]:
        """Continuous stretches of data (a recorder test run, a restart or a frozen window leaves gaps)."""
        segs, start = [], None
        gap_s = get_detection().replay_gap_s
        for i, t in enumerate(self.times):
            if start is None:
                start = t
            elif t - self.times[i - 1] > gap_s:
                segs.append((start, self.times[i - 1]))
                start = t
        if start is not None:
            segs.append((start, self.times[-1]))
        return segs

    def default_start(self) -> float:
        """Inside the longest stretch of data: after a full detection window, leaving at least 60% to play."""
        s0, s1 = max(self.segments(), key=lambda s: s[1] - s[0], default=(self.t_start, self.t_end))
        return s0 + min(1200.0, self.rt.settings.window_keep_s, (s1 - s0) * 0.4)

    def seek(self, ts: float) -> float:
        if not self.frames:
            return ts
        ts = max(self.t_start, min(float(ts), self.t_end))
        old = self.rt.clock.now()
        self.rt.clear_for_time_jump(old)
        self.rt.injector.rebase(old, ts)
        self.rt.clock.use_replay(ts)
        lo = bisect.bisect_left(self.times, ts - self.rt.settings.window_keep_s)
        hi = bisect.bisect_right(self.times, ts)
        for i in range(lo, hi):
            self.rt.window.add(self.frames[i][1])
        self.idx = hi
        self.finished = False
        return ts

    def set_speed(self, speed: float) -> None:
        self.speed = max(0.1, min(float(speed), self.rt.settings.replay_max_speed))

    def _emit_until(self, target: float) -> None:
        while self.idx < len(self.frames) and self.frames[self.idx][0] <= target:
            ts, recs = self.frames[self.idx]
            self.idx += 1  # before ingesting: a frame that raises is skipped, not retried forever
            self.rt.ingest_records(recs, now=ts)

    def _advance(self, dt: float) -> None:
        """Play dt wall-clock seconds (x speed) of the recording."""
        if self.paused or self.finished or not self.frames:
            return
        target = self.rt.clock.now() + dt * self.speed
        if self.idx < len(self.frames) and self.frames[self.idx][0] - target > get_detection().replay_gap_s:
            # Skip dead air in the recording; running attacks keep their remaining duration.
            self.rt.injector.shift(self.frames[self.idx][0] - target)
            target = self.frames[self.idx][0]
        try:
            self._emit_until(target)
        finally:
            self.rt.clock.set(min(target, self.t_end))  # replay time moves on even if a frame failed
        if self.idx >= len(self.frames):
            if self.loop:
                self.seek(self.default_start())
            else:
                self.finished = True

    def step(self, dt: float) -> bool:
        """One iteration of the playback loop. An error is logged and kept in last_error;
        playback carries on with the next iteration instead of silently ending."""
        try:
            self._advance(dt)
            return True
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            self.last_error_ts = self.rt.clock.now()
            log.exception("replay step failed; replay continues")
            return False

    async def run(self) -> None:
        try:
            await asyncio.to_thread(self.load)
            if self.frames:
                self.seek(self.start_ts if self.start_ts is not None else self.default_start())
        except Exception as e:
            self.error = f"replay could not start: {type(e).__name__}: {e}"
            log.exception("replay could not start")
            return
        if not self.frames:
            log.warning(self.error)
            return
        last = time.monotonic()
        while True:
            await asyncio.sleep(0.2)
            t = time.monotonic()
            dt, last = t - last, t
            self.step(dt)

    def status(self) -> dict:
        now = self.rt.clock.now()
        span = max(1e-9, self.t_end - self.t_start)
        return {
            "files": [p.name for p in self.files],
            "sample": bool(self.files) and self.files[0].parent == SAMPLE_DIR,
            "loaded": self.loaded,
            "error": self.error,
            "last_error": self.last_error,
            "last_error_ts": self.last_error_ts,
            "t_start": self.t_start,
            "t_end": self.t_end,
            "ts": now,
            "progress": round((now - self.t_start) / span, 4) if self.frames else 0.0,
            "speed": self.speed,
            "paused": self.paused,
            "finished": self.finished,
            "frames": len(self.frames),
            "segments": len(self.segments()) if self.frames else 0,
            "records": self.n_records,
        }
