"""In-memory sliding window of Records: the detectors' only input.

Detection reads from memory, not SQLite: no blocking disk I/O inside the 5 s
tick, and a replay seek is just clear() + refill. SQLite keeps what must
outlive a restart (incidents, ground truth, sentinel history).
"""
from __future__ import annotations

from typing import Iterable

from app.records import Record


class Window:
    def __init__(self, keep_s: float) -> None:
        self.keep_s = keep_s
        self._recs: list[Record] = []
        self._last_pos: dict[tuple[str, str], tuple[float, float, str | None]] = {}  # (hex, source) -> last stored
        self.added_total = 0
        self.skipped_repeats = 0

    def __len__(self) -> int:
        return len(self._recs)

    def add(self, records: Iterable[Record]) -> int:
        """Append records, skipping exact repeats of an aircraft's previous position.

        A position that has not updated between two polls comes back with the
        same lat/lon; storing it twice would double-count it in spoof checks.
        """
        n = 0
        for r in records:
            if r.lat is not None:
                key = (r.lat, r.lon, r.injected)
                slot = (r.hex, r.source)
                if self._last_pos.get(slot) == key:
                    self.skipped_repeats += 1
                    continue
                self._last_pos[slot] = key
            self._recs.append(r)
            n += 1
        self.added_total += n
        return n

    def prune(self, now: float) -> int:
        cutoff = now - self.keep_s
        before = len(self._recs)
        self._recs = [r for r in self._recs if r.ts >= cutoff]
        if len(self._last_pos) > 5000:  # forget aircraft that left long ago
            alive = {r.hex for r in self._recs}
            self._last_pos = {k: v for k, v in self._last_pos.items() if k[0] in alive}
        return before - len(self._recs)

    def since(self, t0: float, t1: float | None = None) -> list[Record]:
        if t1 is None:
            return [r for r in self._recs if r.ts >= t0]
        return [r for r in self._recs if t0 <= r.ts <= t1]

    def all(self) -> list[Record]:
        return list(self._recs)

    def latest_by_hex(self, now: float, max_age_s: float) -> dict[str, Record]:
        """Freshest record per aircraft heard within max_age_s (position or not)."""
        cutoff = now - max_age_s
        best: dict[str, Record] = {}
        for r in self._recs:
            if r.ts < cutoff or r.ts > now + 5:  # ignore records "from the future" after a backward seek
                continue
            cur = best.get(r.hex)
            if cur is None or r.ts > cur.ts or (r.ts == cur.ts and r.has_position and not cur.has_position):
                best[r.hex] = r
        return best

    def restore_injected(self, attack_id: str) -> int:
        """Undo one simulated attack in the stored history (simulator Reset / Delete).

        Records the attack touched go back to their pristine original. If another
        attack also touched the same record, its effect on that record is undone too;
        new records still receive every attack that remains active.
        """
        n = 0
        for i, r in enumerate(self._recs):
            if r.injected and attack_id in r.injected.split(",") and r.original is not None:
                self._recs[i] = r.original
                n += 1
        if n:
            self._last_pos.clear()
        return n

    def clear(self) -> None:
        self._recs.clear()
        self._last_pos.clear()
