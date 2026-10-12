"""SQLite: what must survive a restart. Detection itself reads memory (state.py).

Tables follow HANDOVER §5.2 plus `sentinel` (§9.1). `positions` and
`cell_status` exist for optional archiving; raw recordings already keep the
full history, so nothing writes to them by default.

Nobody touches the connection directly: the tick and the routes queue writes on
DbWriter, and a background task (main.db_flush_loop) flushes them from a worker
thread. So the tick never waits on the disk, and one lock guards every use of
the connection.
"""
from __future__ import annotations

import itertools
import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Callable, Hashable

log = logging.getLogger("gaw.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    ts REAL, hex TEXT, flight TEXT, lat REAL, lon REAL, alt_baro INTEGER, alt_geom INTEGER,
    on_ground INTEGER, gs REAL, track REAL, nic INTEGER, nac_p INTEGER, seen REAL, seen_pos REAL,
    source TEXT, injected TEXT
);
CREATE INDEX IF NOT EXISTS idx_positions_ts ON positions(ts);
CREATE INDEX IF NOT EXISTS idx_positions_hex_ts ON positions(hex, ts);

CREATE TABLE IF NOT EXISTS cell_status (
    ts REAL, h3 TEXT, n_aircraft INTEGER, n_bad INTEGER, frac_bad REAL, lower_bound REAL, state TEXT
);

CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY, ts REAL, kind TEXT, hex TEXT, flight TEXT, h3 TEXT, eta_s REAL,
    message TEXT, severity TEXT, ack INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY, kind TEXT, opened_ts REAL, closed_ts REAL, cells_json TEXT, aircraft_json TEXT,
    est_lat REAL, est_lon REAL, est_radius_km REAL, max_frac_bad REAL, injected INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ground_truth (
    session TEXT, attack_id TEXT, kind TEXT, start_ts REAL, end_ts REAL, params_json TEXT,
    PRIMARY KEY (session, attack_id, start_ts)
);

CREATE TABLE IF NOT EXISTS sentinel (
    recv_ts REAL, id TEXT, lat REAL, lon REAL, alt REAL, fix INTEGER, sats_used INTEGER,
    sats_in_view INTEGER, avg_snr REAL, hdop REAL, status TEXT, raw_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_sentinel_id_ts ON sentinel(id, recv_ts);
"""


def connect(path: Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


class DbWriter:
    """Queue of SQLite writes, flushed in one go (each write in its own transaction).

    submit() only queues, so it is safe and cheap inside the tick and the routes. A write
    queued with a key replaces an older queued write with the same key: an incident
    upserted every tick is written once per flush. flush() runs in a worker thread
    (main.db_flush_loop) and at shutdown.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.lock = threading.Lock()  # guards every use of the connection
        self._qlock = threading.Lock()  # guards only the queue, so submit() never waits on the disk
        self._pending: dict[Hashable, Callable[[sqlite3.Connection], object]] = {}
        self._anon = itertools.count()
        self.written = 0
        self.errors = 0

    def submit(self, write: Callable[[sqlite3.Connection], object], key: Hashable | None = None) -> None:
        with self._qlock:
            k = ("anon", next(self._anon)) if key is None else key
            self._pending.pop(k, None)  # a newer write with the same key wins and moves to the back
            self._pending[k] = write

    def pending(self) -> int:
        with self._qlock:
            return len(self._pending)

    def flush(self) -> int:
        with self._qlock:
            work, self._pending = list(self._pending.values()), {}
        if not work:
            return 0
        with self.lock:
            for write in work:
                try:
                    with self.conn:
                        write(self.conn)
                    self.written += 1
                except Exception:  # one bad row must not lose the others
                    self.errors += 1
                    log.exception("SQLite write failed")
        return len(work)

    def close(self) -> None:
        self.flush()
        with self.lock:
            self.conn.close()


def sync_ground_truth(conn: sqlite3.Connection, session: str, events: list[dict]) -> None:
    """Replace this session's ground-truth rows with the current list (it is small).
    Runs inside DbWriter's transaction."""
    conn.execute("DELETE FROM ground_truth WHERE session = ?", (session,))
    conn.executemany(
        "INSERT OR REPLACE INTO ground_truth VALUES (?, ?, ?, ?, ?, ?)",
        [
            (session, e["attack_id"], e["kind"], e["start_ts"], e["end_ts"],
             json.dumps({k: v for k, v in e.items() if k not in ("attack_id", "kind", "start_ts", "end_ts")}))
            for e in events
        ],
    )


def insert_sentinel(conn: sqlite3.Connection, entry: dict) -> None:
    """Runs inside DbWriter's transaction."""
    conn.execute(
        "INSERT INTO sentinel VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            entry.get("recv_ts"), entry.get("id"), entry.get("lat"), entry.get("lon"), entry.get("alt"),
            int(bool(entry.get("fix"))), entry.get("sats_used"), entry.get("sats_in_view"),
            entry.get("avg_snr"), entry.get("hdop"), entry.get("status"), json.dumps(entry, default=str),
        ),
    )


UPSERT_INCIDENT = "INSERT OR REPLACE INTO incidents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
