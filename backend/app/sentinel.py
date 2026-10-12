"""Ground Sentinel store (HANDOVER §9.1): packets from the ESP32 + GPS box.

The box posts JSON every ~2 s to POST /api/sentinel. This keeps a short
history per device, re-checks the alarm rules on the server (so the dashboard
does not trust the device alone) and reports OFFLINE when packets stop. It
runs on the wall clock even during replay: the box is real hardware.

Statuses: OK | SEARCHING (no fix yet / no sky view) | JAMMING | SPOOF | OFFLINE.
SEARCHING exists so a box that never got a fix indoors does not look like a
jamming alarm (agreed in the hardware session).

Server rules (thresholds below):
- Baseline: once the box has held a fix for BASELINE_S, the median avg_snr and
  the median position of that period become its reference (shown on the
  dashboard; the position is used for SPOOF).
- JAMMING: avg_snr below JAM_SNR_DB (22 dB-Hz), once the box has had a fix at
  least once. A fixed level, not "N dB below baseline": indoors the baseline
  itself sits around 28-30 and small dips raised false alarms. A lost fix with
  a normal signal is not jamming (OK, reason "no fix, signal normal").
- SPOOF: the fixed box "moves" more than MOVE_M from its reference, or its
  altitude jumps more than ALT_JUMP_M.
Alerts from this box are labelled as a signal test (antenna covered), never
as a detected real-world attack.
"""
from __future__ import annotations

import statistics
from collections import deque

from app.config import Settings
from app.detect.geo import haversine_km

STATUSES = ("OK", "SEARCHING", "JAMMING", "SPOOF", "OFFLINE")
# Defaults of the server rules; the numbers live in config.Settings (sentinel_*), override via GAW_SENTINEL_*.
BASELINE_S: float = Settings.model_fields["sentinel_baseline_s"].default
JAM_SNR_DB: float = Settings.model_fields["sentinel_jam_snr_db"].default
MOVE_M: float = Settings.model_fields["sentinel_move_m"].default
ALT_JUMP_M: float = Settings.model_fields["sentinel_alt_jump_m"].default


def normalize_status(raw) -> str:
    s = str(raw or "").strip().upper().rstrip("?")
    if not s:
        return "OK"
    if s in STATUSES:
        return s
    if any(word in s for word in ("SEARCH", "SKY", "FIX")):
        return "SEARCHING"
    return s  # unknown firmware status: show it as-is rather than guess


def _num(x):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


class _DeviceState:
    def __init__(self) -> None:
        self.fix_since: float | None = None
        self.last_fix_ts: float | None = None
        self.calib: list[tuple[float, float | None, float | None, float | None]] = []  # (snr, lat, lon, alt)
        self.baseline_snr: float | None = None
        self.ref: tuple[float, float, float | None] | None = None


class SentinelStore:
    def __init__(self, offline_s: float, max_len: int, baseline_s: float = BASELINE_S, jam_snr_db: float = JAM_SNR_DB,
                 move_m: float = MOVE_M, alt_jump_m: float = ALT_JUMP_M) -> None:
        self.offline_s = offline_s
        self.max_len = max_len
        self.baseline_s, self.jam_snr_db = baseline_s, jam_snr_db
        self.move_m, self.alt_jump_m = move_m, alt_jump_m
        self.packets: dict[str, deque] = {}
        self.state: dict[str, _DeviceState] = {}

    def _check(self, st: _DeviceState, p: dict, now: float) -> tuple[str, str | None]:
        fix = bool(p.get("fix"))
        snr, lat, lon, alt = _num(p.get("avg_snr")), _num(p.get("lat")), _num(p.get("lon")), _num(p.get("alt"))
        jammed = snr is not None and snr < self.jam_snr_db
        if not fix:
            st.fix_since = None
            if st.last_fix_ts is None:  # never had a fix (indoors at start-up): not an alarm
                return "SEARCHING", "no fix yet"
            if jammed:
                return "JAMMING", f"signal {snr:.1f} dB-Hz, below {self.jam_snr_db:.0f}"
            return "OK", "no fix, signal normal"

        st.last_fix_ts = now
        if st.fix_since is None:
            st.fix_since = now
        if st.baseline_snr is None:
            if snr is not None:
                st.calib.append((snr, lat, lon, alt))
            if now - st.fix_since >= self.baseline_s and st.calib:
                st.baseline_snr = statistics.median(c[0] for c in st.calib)
                pos = [c for c in st.calib if c[1] is not None and c[2] is not None]
                if pos:
                    alts = [c[3] for c in pos if c[3] is not None]
                    st.ref = (statistics.median(c[1] for c in pos), statistics.median(c[2] for c in pos),
                              statistics.median(alts) if alts else None)
                st.calib.clear()
            if jammed:
                return "JAMMING", f"signal {snr:.1f} dB-Hz, below {self.jam_snr_db:.0f}"
            return "OK", "learning baseline" if st.baseline_snr is None else None
        if jammed:
            return "JAMMING", f"signal {snr:.1f} dB-Hz, below {self.jam_snr_db:.0f}"
        if st.ref and lat is not None and lon is not None:
            moved_m = haversine_km(lat, lon, st.ref[0], st.ref[1]) * 1000
            if moved_m > self.move_m:
                return "SPOOF", f"fixed box appears to move {moved_m:.0f} m"
            if alt is not None and st.ref[2] is not None and abs(alt - st.ref[2]) > self.alt_jump_m:
                return "SPOOF", f"altitude jumped {abs(alt - st.ref[2]):.0f} m"
        return "OK", None

    def add(self, packet: dict, recv_ts: float) -> dict:
        device = str(packet.get("id") or "sentinel-1")
        st = self.state.setdefault(device, _DeviceState())
        server_status, why = self._check(st, packet, recv_ts)
        entry = {**packet, "id": device, "recv_ts": recv_ts, "status": normalize_status(packet.get("status")),
                 "server_status": server_status, "server_reason": why, "baseline_snr": st.baseline_snr}
        self.packets.setdefault(device, deque(maxlen=self.max_len)).append(entry)
        return entry

    def latest(self, now: float) -> list[dict]:
        out = []
        for q in self.packets.values():
            last = dict(q[-1])
            age = now - last["recv_ts"]
            last["age_s"] = round(age, 1)
            if age > self.offline_s:
                last["status"] = last["server_status"] = "OFFLINE"
            out.append(last)
        return out

    def alerts(self, now: float) -> list[dict]:
        """Server-confirmed JAMMING/SPOOF on a box that is still online."""
        out = []
        for e in self.latest(now):
            if e["server_status"] in ("JAMMING", "SPOOF"):
                out.append({"id": f"sentinel-{e['id']}", "kind": f"sentinel_{e['server_status'].lower()}",
                            "device": e["id"], "lat": e.get("lat"), "lon": e.get("lon"), "severity": "high",
                            "label": "SIGNAL TEST (antenna covered)", "injected": False, "mixed": False,
                            "message": f"{e['id']}: {e['server_status']} - {e['server_reason']}"})
        return out

    def history(self, device: str, minutes: float, now: float) -> list[dict]:
        cutoff = now - minutes * 60
        return [p for p in self.packets.get(device, ()) if p["recv_ts"] >= cutoff]
