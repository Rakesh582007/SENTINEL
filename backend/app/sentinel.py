"""Ground Sentinel store (HANDOVER §9.1): packets from the ESP32 + GPS box.

The box posts JSON every ~2 s to POST /api/sentinel. This keeps a short
history per device and reports OFFLINE when packets stop. It runs on the wall
clock even during replay, because the box is real hardware on the table.

Status values: OK | SEARCHING (no fix / no sky view yet) | JAMMING | SPOOF | OFFLINE.
SEARCHING exists so a box that never got a fix indoors does not look like a
jamming alarm (agreed in the hardware session).

TODO (server-side re-check, so the dashboard does not trust the device alone):
- baseline = median avg_snr over the first 2 min of a stable fix
- JAMMING if avg_snr drops >= 10 dB below baseline, or fix lost > 5 s after
  being stable; SPOOF if the fixed box "moves" > 50 m or altitude jumps > 100 m
- raise alerts kind "sentinel_jamming" / "sentinel_spoof" labelled as a signal
  test (antenna covered), never as a detected real-world attack.
"""
from __future__ import annotations

from collections import deque

STATUSES = ("OK", "SEARCHING", "JAMMING", "SPOOF", "OFFLINE")


def normalize_status(raw) -> str:
    s = str(raw or "").strip().upper().rstrip("?")
    if not s:
        return "OK"
    if s in STATUSES:
        return s
    if any(word in s for word in ("SEARCH", "SKY", "FIX")):
        return "SEARCHING"
    return s  # unknown firmware status: show it as-is rather than guess


class SentinelStore:
    def __init__(self, offline_s: float, max_len: int) -> None:
        self.offline_s = offline_s
        self.max_len = max_len
        self.packets: dict[str, deque] = {}

    def add(self, packet: dict, recv_ts: float) -> dict:
        device = str(packet.get("id") or "sentinel-1")
        entry = {**packet, "id": device, "recv_ts": recv_ts, "status": normalize_status(packet.get("status"))}
        self.packets.setdefault(device, deque(maxlen=self.max_len)).append(entry)
        return entry

    def latest(self, now: float) -> list[dict]:
        out = []
        for q in self.packets.values():
            last = dict(q[-1])
            age = now - last["recv_ts"]
            last["age_s"] = round(age, 1)
            if age > self.offline_s:
                last["status"] = "OFFLINE"
            out.append(last)
        return out

    def history(self, device: str, minutes: float, now: float) -> list[dict]:
        cutoff = now - minutes * 60
        return [p for p in self.packets.get(device, ()) if p["recv_ts"] >= cutoff]
