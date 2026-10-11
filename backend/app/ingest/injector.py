"""Attack Simulator back end (HANDOVER §7, §7.1). Data injection only.

Attacks never touch a radio. They alter copies of real aircraft records just
before the records enter the detection window, and every altered record is
tagged (Record.injected) so the UI can badge it "INJECTED TEST ATTACK".

Two rules the sliders depend on:

1. Selection is per aircraft and deterministic. "Strength 70%" means a fixed
   70% of the aircraft inside the circle, chosen by hashing (attack id, hex).
   If every record were re-rolled at random, nearly every aircraft would be
   "bad" at least once inside a 20-minute window and the Strength slider would
   change nothing. Raising the slider only ever adds aircraft (30% is a subset
   of 70%), so the map responds smoothly.
2. Undo is exact. Each altered record keeps its pristine original, so deleting
   an attack (or Reset) restores the stored history and the map clears at once
   (Window.restore_injected). Switching an attack to active=false instead stops
   new injection and lets the window age out, which is what a real jammer
   switching off looks like.
"""
from __future__ import annotations

import hashlib
import itertools
from dataclasses import asdict, dataclass, field, replace
from typing import Iterable

from app.detect.geo import destination_point, haversine_km
from app.records import Record

LABEL = "INJECTED TEST ATTACK"


def selected(attack_id: str, hex_id: str, share: float, salt: str = "") -> bool:
    """Deterministic 'is this aircraft in the affected share?' (see rule 1)."""
    if share <= 0:
        return False
    if share >= 1:
        return True
    digest = hashlib.blake2b(f"{attack_id}|{salt}|{hex_id}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") / 2**64 < share


@dataclass
class Attack:
    id: str
    kind: str  # "jamming" | "spoof"
    created_ts: float
    active: bool = True
    activated_ts: float = 0.0
    duration_s: float | None = None  # None = until switched off
    ended_ts: float | None = None
    # jamming
    center: tuple[float, float] | None = None
    radius_km: float = 60.0
    strength: float = 0.7
    position_loss: float = 0.3
    # spoofing
    hex: str | None = None
    offset_km: float = 25.0
    bearing_deg: float = 45.0
    alt_offset_ft: float = 0.0
    # bookkeeping
    max_aircraft_inside: int = 0  # coverage seen during the attack (for "undetectable" in evaluation)
    frozen: dict[str, tuple[float, float, float]] = field(default_factory=dict, repr=False)  # hex -> (lat, lon, ts) where GPS was "lost"

    def live(self, now: float) -> bool:
        if not self.active or self.ended_ts is not None:
            return False
        return self.duration_s is None or now < self.activated_ts + self.duration_s

    def remaining_s(self, now: float) -> float | None:
        if self.duration_s is None or not self.live(now):
            return None
        return max(0.0, self.activated_ts + self.duration_s - now)

    def to_dict(self, now: float | None = None) -> dict:
        d = asdict(self)
        d.pop("frozen", None)
        d["label"] = LABEL
        if now is not None:
            d["live"] = self.live(now)
            d["remaining_s"] = self.remaining_s(now)
        return d


JAMMING_FIELDS = {"center", "radius_km", "strength", "position_loss", "duration_s", "active"}
SPOOF_FIELDS = {"hex", "offset_km", "bearing_deg", "alt_offset_ft", "duration_s", "active"}
GEOMETRY_FIELDS = {"center", "radius_km", "hex"}  # changing these starts a new ground-truth event


class Injector:
    def __init__(self) -> None:
        self.attacks: dict[str, Attack] = {}
        self.ground_truth: list[dict] = []
        self._seq = itertools.count(1)

    # ---- lifecycle -------------------------------------------------------
    def add_jamming(self, center: tuple[float, float], radius_km: float, strength: float, position_loss: float, duration_s: float | None, now: float) -> Attack:
        a = Attack(id=f"jam-{next(self._seq)}", kind="jamming", created_ts=now, activated_ts=now, duration_s=duration_s,
                   center=(float(center[0]), float(center[1])), radius_km=radius_km, strength=strength, position_loss=position_loss)
        self.attacks[a.id] = a
        self._open_event(a, now)
        return a

    def add_spoof(self, hex_id: str, offset_km: float, bearing_deg: float, alt_offset_ft: float, duration_s: float | None, now: float) -> Attack:
        a = Attack(id=f"spoof-{next(self._seq)}", kind="spoof", created_ts=now, activated_ts=now, duration_s=duration_s,
                   hex=hex_id.lower(), offset_km=offset_km, bearing_deg=bearing_deg, alt_offset_ft=alt_offset_ft)
        self.attacks[a.id] = a
        self._open_event(a, now)
        return a

    def update(self, attack_id: str, changes: dict, now: float) -> Attack:
        a = self.attacks[attack_id]
        allowed = JAMMING_FIELDS if a.kind == "jamming" else SPOOF_FIELDS
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"cannot change {sorted(unknown)} on a {a.kind} attack")
        was_live = a.live(now)
        geometry_changed = any(k in GEOMETRY_FIELDS and changes[k] != getattr(a, k) for k in changes)
        for k, v in changes.items():
            if k == "center" and v is not None:
                v = (float(v[0]), float(v[1]))
            if k == "hex" and v is not None:
                v = str(v).lower()
            setattr(a, k, v)
        if changes.get("active") is True and not was_live:
            a.activated_ts = now
            a.ended_ts = None
        if geometry_changed:
            a.frozen.clear()
        is_live = a.live(now)
        if was_live and (not is_live or geometry_changed):
            self._close_event(a.id, now)
        if is_live and (not was_live or geometry_changed):
            self._open_event(a, now)
        elif is_live:
            self._refresh_event(a)
        return a

    def remove(self, attack_id: str, now: float) -> Attack | None:
        a = self.attacks.pop(attack_id, None)
        if a is not None:
            a.ended_ts = now
            self._close_event(attack_id, now)
        return a

    def reset(self, now: float) -> list[str]:
        ids = list(self.attacks)
        for attack_id in ids:
            self.remove(attack_id, now)
        return ids

    def rebase(self, old_now: float, new_now: float) -> None:
        """Replay jumped in time: shift attack timers, close/reopen live ground-truth events."""
        delta = new_now - old_now
        for a in self.attacks.values():
            was_live = a.live(old_now)
            a.created_ts += delta
            a.activated_ts += delta
            if a.ended_ts is not None:
                a.ended_ts += delta
            a.frozen.clear()
            if was_live:
                self._close_event(a.id, old_now)
                self._open_event(a, new_now)

    def clear_all(self) -> None:
        """Forget attacks AND ground truth (mode switch = a fresh experiment)."""
        self.attacks.clear()
        self.ground_truth.clear()

    def live_attacks(self, now: float) -> list[Attack]:
        for a in self.attacks.values():  # close events of attacks whose duration ran out
            if a.ended_ts is None and a.active and not a.live(now):
                self._close_event(a.id, now)
                a.ended_ts = now
        return [a for a in self.attacks.values() if a.live(now)]

    # ---- the actual injection -------------------------------------------
    def apply(self, records: Iterable[Record], now: float) -> list[Record]:
        live = self.live_attacks(now)
        records = list(records)
        if not live:
            return records
        out = []
        for pristine in records:
            cur = pristine
            for a in live:
                changed = self._jam(cur, pristine, a, now) if a.kind == "jamming" else self._spoof(cur, pristine, a)
                if changed is not None:
                    cur = changed
            out.append(cur)
        return out

    def _jam(self, cur: Record, pristine: Record, a: Attack, now: float) -> Record | None:
        if pristine.on_ground or a.center is None:
            return None
        pos = pristine.best_position()
        if pos is None:
            return None
        if haversine_km(pos[0], pos[1], a.center[0], a.center[1]) > a.radius_km:
            a.frozen.pop(pristine.hex, None)  # left the circle: GPS "recovers"
            return None
        if not selected(a.id, pristine.hex, a.strength):
            return None
        changes: dict = {"nac_p": 0, "nic": 0}
        if pristine.has_position and selected(a.id, pristine.hex, a.position_loss, salt="pos"):
            lat0, lon0, t0 = a.frozen.setdefault(pristine.hex, (pristine.lat, pristine.lon, now))
            changes.update(lat=None, lon=None, last_lat=lat0, last_lon=lon0,
                           seen_pos=max(pristine.seen_pos or 0.0, now - t0))
        return _tag(cur, pristine, a.id, changes)

    def _spoof(self, cur: Record, pristine: Record, a: Attack) -> Record | None:
        if pristine.hex != a.hex or not pristine.has_position or not cur.has_position:
            return None
        lat, lon = destination_point(pristine.lat, pristine.lon, a.bearing_deg, a.offset_km)
        changes: dict = {"lat": lat, "lon": lon}
        if a.alt_offset_ft:
            base = pristine.alt_geom if pristine.alt_geom is not None else pristine.alt_baro
            if base is not None:
                changes["alt_geom"] = int(round(base + a.alt_offset_ft))
        return _tag(cur, pristine, a.id, changes)

    # ---- helpers ---------------------------------------------------------
    def aircraft_inside(self, a: Attack, latest: Iterable[Record]) -> int:
        """Airborne aircraft currently inside a jamming circle (simulator preview + coverage)."""
        if a.kind != "jamming" or a.center is None:
            return 0
        return count_inside(a.center, a.radius_km, latest)

    def _open_event(self, a: Attack, now: float) -> None:
        self.ground_truth.append({
            "attack_id": a.id, "kind": a.kind, "start_ts": now, "end_ts": None,
            "center": a.center, "radius_km": a.radius_km, "strength": a.strength,
            "position_loss": a.position_loss, "hex": a.hex, "offset_km": a.offset_km,
            "bearing_deg": a.bearing_deg, "alt_offset_ft": a.alt_offset_ft,
        })

    def _refresh_event(self, a: Attack) -> None:
        for g in reversed(self.ground_truth):
            if g["attack_id"] == a.id and g["end_ts"] is None:
                g.update(strength=a.strength, position_loss=a.position_loss, offset_km=a.offset_km,
                         bearing_deg=a.bearing_deg, alt_offset_ft=a.alt_offset_ft)
                return

    def _close_event(self, attack_id: str, now: float) -> None:
        for g in reversed(self.ground_truth):
            if g["attack_id"] == attack_id and g["end_ts"] is None:
                g["end_ts"] = now
                return


def count_inside(center: tuple[float, float], radius_km: float, records: Iterable[Record]) -> int:
    hexes = set()
    for r in records:
        if r.on_ground:
            continue
        pos = (r.original or r).best_position()
        if pos is not None and haversine_km(pos[0], pos[1], center[0], center[1]) <= radius_km:
            hexes.add(r.hex)
    return len(hexes)


def _tag(cur: Record, pristine: Record, attack_id: str, changes: dict) -> Record:
    ids = cur.injected.split(",") if cur.injected else []
    if attack_id not in ids:
        ids.append(attack_id)
    return replace(cur, **changes, injected=",".join(ids), original=pristine)
