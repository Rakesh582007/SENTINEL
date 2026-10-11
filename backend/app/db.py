"""SQLite: what must survive a restart. Detection itself reads memory (state.py).

Tables follow HANDOVER §5.2 plus `sentinel` (§9.1). `positions` and
`cell_status` exist for optional archiving; raw recordings already keep the
full history, so nothing writes to them by default.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

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


def sync_ground_truth(conn: sqlite3.Connection, session: str, events: list[dict]) -> None:
    """Replace this session's ground-truth rows with the current list (it is small)."""
    with conn:
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
    with conn:
        conn.execute(
            "INSERT INTO sentinel VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry.get("recv_ts"), entry.get("id"), entry.get("lat"), entry.get("lon"), entry.get("alt"),
                int(bool(entry.get("fix"))), entry.get("sats_used"), entry.get("sats_in_view"),
                entry.get("avg_snr"), entry.get("hdop"), entry.get("status"), json.dumps(entry, default=str),
            ),
        )
