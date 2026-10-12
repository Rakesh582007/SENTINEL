"""The running backend: one object that owns all live state.

    clock     one source of "now" (wall clock live, recording time in replay)
    window    in-memory sliding window of Records; detectors read only this
    injector  simulated attacks + their ground truth
    ingest    exactly ONE task feeds the window: LivePoller or Replayer
    tick      every settings.tick_s: run detectors, build the payload, broadcast

Routes reach it as request.app.state.rt. Nothing else holds global state
(except config.get_detection(), the runtime-tunable thresholds).
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from pathlib import Path

import h3

from app.clock import Clock
from app.config import Settings, get_detection
from app.db import connect, insert_sentinel, sync_ground_truth
from app.detect import spoofing, warning
from app.detect.spoofing import SPOOF_REASONS
from app.detect.geo import haversine_km
from app.detect.incidents import IncidentTracker
from app.detect.jamming import CellStat, bad_reason, classify_cells, label_injection, to_geojson
from app.ingest.injector import Injector, count_inside
from app.ingest.normalize import normalize_response
from app.ingest.poller import LivePoller
from app.ingest.recording import append_line, make_line, new_run_id
from app.ingest.replay import Replayer, choose_files
from app.ingest.sources import ATTRIBUTION
from app.records import Record
from app.regions import REGIONS, QueryPoint, get_region, parse_points
from app.sentinel import SentinelStore
from app.state import Window

log = logging.getLogger("gaw.runtime")

ALARM_STATES = ("jammed", "spoofing")


class Runtime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.clock = Clock()
        self.window = Window(settings.window_keep_s)
        self.injector = Injector()
        self.incidents = IncidentTracker()
        self.sentinel = SentinelStore(settings.sentinel_offline_s, settings.sentinel_history_max)
        self.mode = settings.mode
        self.region_name = settings.region
        self.points: tuple[QueryPoint, ...] = get_region(settings.region)
        self.sources = list(settings.sources)
        self.run_id = new_run_id()
        self.ingest_task: asyncio.Task | None = None
        self.replayer: Replayer | None = None
        self.poller: LivePoller | None = None
        self.source_stats: dict[str, dict] = {}
        self.last_answer_ts: float | None = None
        self.last_tick: dict | None = None
        self.last_cells: dict[str, CellStat] = {}
        self.detections: list[dict] = []  # cells ENTERING jammed/spoofing; input for evaluate.py
        self.flag_log: list[dict] = []  # aircraft newly flagged by spoofing.py; input for evaluate.py
        self._prev_states: dict[str, str] = {}
        self._prev_flagged: set[str] = set()
        self.scenario: dict | None = None  # {"id", "start_ts", "pending": [(fire_ts, attack_body)], "fired": [...]}
        self.db = None

    # ------------------------------------------------------------------ setup
    def open_db(self) -> None:
        try:
            self.db = connect(self.settings.db_path)
            self.incidents.db = self.db
        except Exception:  # the demo must not die because of a disk problem
            log.exception("SQLite unavailable; continuing without persistence")
            self.db = None

    # -------------------------------------------------------------- ingestion
    def ingest_records(self, records: list[Record], now: float | None = None) -> int:
        """Every record, live or replayed, goes through here: inject attacks, then store."""
        when = self.clock.now() if now is None else now
        return self.window.add(self.injector.apply(records, when))

    def on_live_answer(self, poll_ts: float, source: str, point: QueryPoint, status: int, ms: float, err: str | None, data: dict | None) -> None:
        st = self.source_stats.setdefault(source, {"ok": 0, "fail": 0, "last_ok_ts": None, "last_error": None, "last_ms": None})
        st["last_ms"] = round(ms)
        if self.settings.record_live:
            try:
                append_line(self.settings.recordings_dir, make_line(poll_ts, source, point.as_dict(), status, ms, err, data), self.run_id)
            except OSError:
                log.exception("could not write recording")
        if status == 200 and data is not None:
            st["ok"] += 1
            st["last_ok_ts"] = poll_ts
            self.last_answer_ts = poll_ts
            self.ingest_records(normalize_response(data, source, poll_ts))
        else:
            st["fail"] += 1
            st["last_error"] = err

    # ------------------------------------------------------------------ modes
    async def stop_ingest(self) -> None:
        task, self.ingest_task = self.ingest_task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                log.exception("ingest task ended with an error")
        self.poller = None
        self.replayer = None

    def clear_for_time_jump(self) -> None:
        """Replay seek or loop: drop history that belongs to the old time; keep the attacks."""
        self.window.clear()
        self.incidents.reset()
        self._prev_states.clear()
        self._prev_flagged.clear()
        self.scenario = None  # a time jump cancels a running scenario (its times belong to the old clock)

    def reset_experiment(self) -> None:
        """Fresh start: empty window, no attacks, no ground truth, no incidents."""
        self.window.clear()
        self.injector.clear_all()
        self.incidents.reset()
        self.detections.clear()
        self.flag_log.clear()
        self._prev_states.clear()
        self._prev_flagged.clear()
        self.scenario = None
        self.persist_ground_truth()

    async def start(self, mode: str, files: list[str] | None = None, speed: float | None = None, start_ts: float | None = None) -> None:
        await self.stop_ingest()
        self.reset_experiment()
        self.mode = mode
        if mode == "live":
            self.clock.use_live()
            self.poller = LivePoller(self)
            self.ingest_task = asyncio.create_task(self.poller.run(), name="live-poller")
        else:
            chosen = self.replay_files(files)
            self.replayer = Replayer(self, chosen, speed or self.settings.replay_speed, start_ts, self.settings.replay_loop)
            self.clock.use_replay(time.time())  # placeholder until the first seek
            self.ingest_task = asyncio.create_task(self.replayer.run(), name="replayer")

    def replay_files(self, names: list[str] | None) -> list[Path]:
        """What a replay plays: the names given, else GAW_REPLAY_FILES, else the newest hours
        (or the bundled sample). Unknown names raise FileNotFoundError."""
        pinned = self.settings.replay_file_list
        try:
            return choose_files(self.settings.recordings_dir, names or pinned or None, self.settings.replay_default_hours)
        except FileNotFoundError as e:
            if not names and pinned:
                raise FileNotFoundError(f"GAW_REPLAY_FILES lists recordings that do not exist ({e}); "
                                        "fix the names (GET /api/recordings lists them) or unset it") from e
            raise

    def set_region(self, name: str | None = None, points: str | None = None) -> None:
        if points:
            self.points, self.region_name = parse_points(points), "custom"
        elif name:
            self.points, self.region_name = get_region(name), name
        else:
            raise ValueError("give a region name or custom points")

    # ------------------------------------------------------------------ attacks
    def latest_aircraft(self) -> dict[str, Record]:
        return self.window.latest_by_hex(self.clock.now(), self.settings.aircraft_max_age_s)

    def pick_random_aircraft(self) -> str | None:
        candidates = [r.hex for r in self.latest_aircraft().values() if r.airborne and r.has_position and not r.injected]
        return random.choice(candidates) if candidates else None

    def preview_circle(self, lat: float, lon: float, radius_km: float) -> dict:
        """What a jammer here would touch. Detection is per H3 cell, so the useful
        number is the busiest cell under the circle, not the circle total."""
        now, cfg = self.clock.now(), get_detection()
        window_recs = self.window.since(now - cfg.jam_window_s, now)
        per_cell: dict[str, set] = {}
        for r in window_recs:
            pos = (r.original or r).best_position()
            if r.on_ground or pos is None or haversine_km(pos[0], pos[1], lat, lon) > radius_km:
                continue
            per_cell.setdefault(h3.latlng_to_cell(pos[0], pos[1], cfg.h3_res), set()).add(r.hex)
        best = max((len(v) for v in per_cell.values()), default=0)
        ok = best >= cfg.min_aircraft
        return {
            "aircraft_now": count_inside((lat, lon), radius_km, self.latest_aircraft().values()),
            "aircraft_in_window": count_inside((lat, lon), radius_km, window_recs),
            "cells_under_circle": len(per_cell),
            "busiest_cell_aircraft": best,
            "min_aircraft_per_cell": cfg.min_aircraft,
            "likely_detectable": ok,
            "hint": None if ok else (
                "Too few aircraft per cell here for the crowd method. Try a busier area, a bigger radius, "
                "a longer window, or bigger cells (Cell size: res 2)."),
        }

    def create_attack(self, body: dict) -> dict:
        """One place that turns a POST /api/attacks body (or a scenario event) into an attack."""
        now = self.clock.now()
        if body.get("kind") == "jamming":
            a = self.injector.add_jamming(tuple(body["center"]), body.get("radius_km", 60), body.get("strength", 0.7),
                                          body.get("position_loss", 0.3), body.get("duration_s"), now)
            extra = self.preview_circle(a.center[0], a.center[1], a.radius_km)
        elif body.get("kind") == "spoof":
            hex_id = body.get("hex", "random")
            hex_id = self.pick_random_aircraft() if hex_id == "random" else str(hex_id).lower()
            if not hex_id:
                raise LookupError("no airborne aircraft available to spoof right now")
            a = self.injector.add_spoof(hex_id, body.get("offset_km", 25), body.get("bearing_deg", 45),
                                        body.get("alt_offset_ft", 0), body.get("duration_s", 300), now)
            extra = {}
        else:
            raise ValueError(f"unknown attack kind {body.get('kind')!r}")
        self.refresh_coverage(a)
        self.persist_ground_truth()
        return {"attack_id": a.id, "attack": a.to_dict(now), **extra}

    def update_attack(self, attack_id: str, changes: dict):
        """A slider move (PATCH): update, refresh the coverage of a new/moved event, persist."""
        a = self.injector.update(attack_id, changes, self.clock.now())
        self.refresh_coverage(a)
        self.persist_ground_truth()
        return a

    def refresh_coverage(self, a) -> None:
        if a.kind == "jamming" and a.live(self.clock.now()):
            self.injector.record_coverage(a, self.injector.aircraft_inside(a, self.latest_aircraft().values()))

    def list_scenarios(self) -> list[dict]:
        out = []
        for p in sorted(Path(self.settings.scenarios_dir).glob("*.json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                out.append({"id": d.get("id", p.stem), "file": p.name, "description": d.get("description"),
                            "events": len(d.get("events", []))})
            except (OSError, ValueError):
                continue
        return out

    def start_scenario(self, scenario_id: str) -> dict:
        for p in Path(self.settings.scenarios_dir).glob("*.json"):
            d = json.loads(p.read_text(encoding="utf-8"))
            if d.get("id", p.stem) == scenario_id:
                now = self.clock.now()
                pending = sorted(((now + float(e["at_offset_s"]), e["attack"]) for e in d.get("events", [])), key=lambda x: x[0])
                self.scenario = {"id": scenario_id, "start_ts": now, "pending": pending, "fired": []}
                return self.scenario_status()
        raise KeyError(f"no scenario {scenario_id!r}")

    def scenario_status(self) -> dict | None:
        if not self.scenario:
            return None
        s = self.scenario
        return {"id": s["id"], "start_ts": s["start_ts"], "fired": s["fired"], "remaining": len(s["pending"]),
                "next_ts": s["pending"][0][0] if s["pending"] else None}

    def _fire_scenario_events(self, now: float) -> None:
        if not self.scenario:
            return
        while self.scenario["pending"] and self.scenario["pending"][0][0] <= now:
            _, body = self.scenario["pending"].pop(0)
            try:
                self.scenario["fired"].append(self.create_attack(body)["attack_id"])
            except (LookupError, ValueError) as e:
                self.scenario["fired"].append(f"skipped: {e}")

    def persist_ground_truth(self) -> None:
        if self.db is not None:
            try:
                sync_ground_truth(self.db, self.run_id, self.injector.ground_truth)
            except Exception:
                log.exception("could not save ground truth")

    def add_sentinel(self, packet: dict) -> dict:
        entry = self.sentinel.add(packet, time.time())
        if self.db is not None:
            try:
                insert_sentinel(self.db, entry)
            except Exception:
                log.exception("could not save sentinel packet")
        return entry

    # ------------------------------------------------------------------ tick
    def compute_tick(self) -> dict:
        now = self.clock.now()
        cfg = get_detection()
        self._fire_scenario_events(now)
        self.window.prune(now)
        recs = self.window.since(now - cfg.jam_window_s, now)

        cells = classify_cells(recs, cfg)
        flags = spoofing.flag_aircraft(recs, cfg)
        spoof_flagged = {h for h, why in flags.items() if SPOOF_REASONS.intersection(why)}
        for h in spoof_flagged - self._prev_flagged:
            self.flag_log.append({"ts": now, "hex": h, "reasons": flags[h]})
        self._prev_flagged = spoof_flagged
        for cell, n_flagged in spoofing.spoofed_cells(flags, recs, cfg).items():
            if n_flagged >= 1:  # spoofed_cells already applied the strong/weak rule
                c = cells.get(cell) or CellStat(h3=cell, n_aircraft=n_flagged, n_bad=0, frac_bad=0.0, lower_bound=0.0, state="spoofing")
                c.state = "spoofing"
                cells[cell] = c
        # Injected = ANY simulated effect in the cell; mixed = simulated and real ones together.
        injected_aircraft = {r.hex for r in recs if r.injected}
        flagged = spoofing.flagged_by_cell(flags, recs, cfg)
        for cell, c in cells.items():
            label_injection(c, flagged.get(cell, ()), injected_aircraft)

        for cell, c in cells.items():
            if c.state in ALARM_STATES and self._prev_states.get(cell) != c.state:
                self.detections.append({"ts": now, "h3": cell, "state": c.state, "n_bad": c.n_bad,
                                        "n_aircraft": c.n_aircraft, "n_injected": c.n_injected,
                                        "injected": c.injected, "mixed": c.mixed})
        self._prev_states = {cell: c.state for cell, c in cells.items()}

        latest = self.latest_aircraft()
        alarm_cells = {cell: c.state for cell, c in cells.items() if c.state in ALARM_STATES}
        injected_cells = {cell for cell, c in cells.items() if c.state in ALARM_STATES and c.injected}
        mixed_cells = {cell for cell, c in cells.items() if c.state in ALARM_STATES and c.mixed}
        alerts = warning.early_warnings(latest, alarm_cells, cfg, now, injected_cells, mixed_cells)
        alerts += self.sentinel.alerts(time.time())
        self.incidents.update(cells, recs, cfg, now, flags)

        for a in self.injector.live_attacks(now):
            self.injector.record_coverage(a, self.injector.aircraft_inside(a, latest.values()))

        aircraft = []
        for r in latest.values():
            pos = r.best_position()
            if pos is None:
                continue
            aircraft.append({
                "hex": r.hex, "flight": r.flight, "lat": round(pos[0], 5), "lon": round(pos[1], 5),
                "pos_lost": not r.has_position, "alt_baro": r.alt_baro, "alt_geom": r.alt_geom,
                "on_ground": r.on_ground, "gs": r.gs, "track": r.track, "nic": r.nic, "nac_p": r.nac_p,
                "source": r.source, "age_s": round(now - r.ts, 1), "bad": bad_reason(r, cfg),
                "spoof": flags.get(r.hex, []), "injected": r.injected,
            })

        state_counts: dict[str, int] = {}
        for c in cells.values():
            state_counts[c.state] = state_counts.get(c.state, 0) + 1

        self.last_cells = cells
        payload = {
            "type": "tick",
            "ts": now,
            "mode": self.mode,
            "region": self.region_name,
            "h3_res": cfg.h3_res,
            "window_s": cfg.jam_window_s,
            "cells": to_geojson(cells),
            "aircraft": aircraft,
            "alerts": alerts,
            "incidents_summary": self.incidents.summary(),
            "attacks": [a.to_dict(now) for a in self.injector.attacks.values()],
            "sentinel": self.sentinel.latest(time.time()),
            "replay": self.replayer.status() if self.replayer else None,
            "scenario": self.scenario_status(),
            "stats": {"aircraft": len(aircraft), "cells": state_counts, "window_records": len(self.window)},
            "credits": ATTRIBUTION,
        }
        self.last_tick = payload
        return payload

    # ------------------------------------------------------------------ health
    def health(self) -> dict:
        ingest = self.replayer or self.poller
        return {
            "mode": self.mode,
            "region": self.region_name,
            "points": [p.as_dict() for p in self.points],
            "sources": self.sources,
            "clock_ts": self.clock.now(),
            "last_poll_ts": self.last_answer_ts,
            "n_aircraft": len(self.latest_aircraft()),
            "window_records": len(self.window),
            "source_stats": self.source_stats,
            "replay": self.replayer.status() if self.replayer else None,
            "last_error": getattr(ingest, "last_error", None),  # newest ingest error (ingest carried on)
            "last_error_ts": getattr(ingest, "last_error_ts", None),
            "attacks_live": len(self.injector.live_attacks(self.clock.now())),
            "tick_s": self.settings.tick_s,
            "run_id": self.run_id,
            "regions": sorted(REGIONS),
            "recordings_dir": str(Path(self.settings.recordings_dir)),
        }
