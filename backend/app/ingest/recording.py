"""Raw recording format, shared by scripts/record.py and the live poller.

Stdlib only.

One JSON object per line, and every line is written as its own gzip member,
so a crash or power cut loses at most the line being written:

    {"v": 1, "poll_ts": 1791701082.1, "source": "adsb.fi",
     "point": {"name": "amritsar", "lat": 31.6, "lon": 74.9, "radius_nm": 250},
     "http": 200, "ms": 311, "error": null, "response": {...raw API JSON...}}

`poll_ts` is the local wall clock when the answer arrived (unix seconds).
The API's own `now` (milliseconds) stays inside `response`.

Files rotate every UTC hour and carry a per-process run id, so a restarted
recorder never appends to a file that a crash may have truncated:

    data/recordings/rec_20261011_06_r064512.jsonl.gz
"""
from __future__ import annotations

import gzip
import json
import time
import zlib
from pathlib import Path
from typing import Iterator

FORMAT_VERSION = 1
FILE_GLOB = "rec_*.jsonl.gz"


def new_run_id(ts: float | None = None) -> str:
    return "r" + time.strftime("%H%M%S", time.gmtime(ts if ts is not None else time.time()))


def recording_path(directory: Path, ts: float, run_id: str) -> Path:
    stamp = time.strftime("%Y%m%d_%H", time.gmtime(ts))
    return Path(directory) / f"rec_{stamp}_{run_id}.jsonl.gz"


def make_line(poll_ts: float, source: str, point: dict, http: int, ms: float, error: str | None, response: dict | None) -> dict:
    return {
        "v": FORMAT_VERSION,
        "poll_ts": round(poll_ts, 3),
        "source": source,
        "point": point,
        "http": http,
        "ms": round(ms),
        "error": error,
        "response": response,
    }


def append_line(directory: Path, obj: dict, run_id: str) -> Path:
    """Append one JSON object as a self-contained gzip member. Returns the file written."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = recording_path(directory, obj.get("poll_ts", time.time()), run_id)
    data = (json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
    with open(path, "ab") as f:
        f.write(gzip.compress(data, compresslevel=6))
    return path


def iter_recording(path: Path) -> Iterator[dict]:
    """Yield line objects from one recording file.

    Tolerates a truncated final gzip member (crash mid-write) and skips lines
    that are not valid JSON. Never raises for damaged data; it just stops.
    """
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
    except (EOFError, OSError, zlib.error):
        return


def list_recordings(directory: Path) -> list[Path]:
    directory = Path(directory)
    if not directory.exists():
        return []
    return sorted(p for p in directory.glob(FILE_GLOB) if p.is_file())
