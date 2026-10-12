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
import functools
import json
import logging
import math
import random
import time
from pathlib import Path

import h3
from pydantic import TypeAdapter, ValidationError

from app.ai.summary import Summarizer
from app.clock import Clock
from app.config import Settings, get_detection
from app.db import DbWriter, connect, insert_sentinel, sync_ground_truth
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
from app.models import AttackIn
from app.records import Record
from app.regions import REGIONS, QueryPoint, get_region, parse_points
from app.sentinel import SentinelStore
from app.state import Window

log = logging.getLogger("gaw.runtime")

ALARM_STATES = ("jammed", "spoofing")
ATTACK_BODY = TypeAdapter(AttackIn)


def scenario_event(n: int, event) -> tuple[float, dict]:
    """One scenario event -> (at_offset_s, a validated POST /api/attacks body). ValueError with a
    message that says which event and what is wrong."""
    if not isinstance(event, dict):
        raise ValueError(f"event {n}: must be an object with at_offset_s and attack")
    off = event.get("at_offset_s")
    if off is None:
        raise ValueError(f"event {n}: missing at_offset_s (seconds of replay time after the scenario starts)")
    if isinstance(off, bool) or not isinstance(off, (int, float)) or not math.isfinite(off) or off < 0:
        raise ValueError(f"event {n}: at_offset_s must be a number >= 0, got {off!r}")
    try:
        attack = ATTACK_BODY.validate_python(event.get("attack"))
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(str(x) for x in err['loc']) or 'attack'}: {err['msg']}" for err in e.errors())
        raise ValueError(f"event {n}: invalid attack ({problems})") from None
    return float(off), attack.model_dump()


class Runtime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.clock = Clock()
        self.window = Window(settings.window_keep_s)
        self.injector = Injector()
        self.sentinel = SentinelStore(settings.sentinel_offline_s, settings.sentinel_history_max, settings.sentinel_baseline_s,
                                      settings.sentinel_snr_drop_db, settings.sentinel_fix_loss_s, settings.sentinel_move_m,
                                      settings.sentinel_alt_jump_m)
        self.mode = settings.mode
        self.region_name = settings.region
        self.points: tuple[QueryPoint, ...] = get_region(settings.region)
        self.sources = list(settings.sources)
        self.run_id = new_run_id()
        self.incidents = IncidentTracker(run_id=self.run_id)  # Attack Simulator view: real + injected records
        self.real_incidents = IncidentTracker(run_id=self.run_id, prefix="air")  # Live airspace: real records only
        self.ingest_task: asyncio.Task | None = None
        self.replayer: Replayer | None = None
        self.poller: LivePoller | None = None
        self.source_stats: dict[str, dict] = {}
        self.last_answer_ts: float | None = None
        self.last_tick: dict | None = None
        self.last_cells: dict[str, CellStat] = {}
        self.detections: list[dict] = []  # cells ENTERING jammed/spoofing; input for evaluate.py
        self.flag_log: list[dict] = []  # aircraft newly flagged by spoofing.py; input for evaluate.py
        self.alert_log: dict[str, dict] = {}  # alert id -> newest copy + first_ts/last_ts/active/ended_ts (GET /api/alerts)
        self._prev_states: dict[str, str] = {}
        self._prev_flagged: set[str] = set()
        # +1 on every replay seek or loop. Detections, spoof flags and ground-truth events carry it,
        # and evaluation only matches within one epoch (replay time is not monotonic across a jump).
        self.epoch = 0
        self.scenario: dict | None = None  # {"id", "start_ts", "pending": [(fire_ts, attack_body)], "fired": [...]}
        self.db = None
        self.ai = Summarizer(settings)  # words only, on request; never called from the tick
        self.tick_state: dict | None = None
        self.real_state: dict | None = None  # same shape as tick_state, for the real-only view
        self.dbw: DbWriter | None = None  # every SQLite write is queued here (see db.py)

    # ------------------------------------------------------------------ setup
    def open_db(self) -> None:
        try:
            self.db = connect(self.settings.db_path)
            self.dbw = DbWriter(self.db)
            self.incidents.db = self.dbw
            self.real_incidents.db = self.dbw
        except Exception:  # the demo must not die because of a disk problem
            log.exception("SQLite unavailable; continuing without persistence")
            self.db = self.dbw = None

    def close_db(self) -> None:
        """Shutdown: write what is still queued, then close."""
        if self.dbw is not None:
            try:
                self.dbw.close()
            except Exception:
                log.exception("could not close SQLite")
            self.db = self.dbw = None

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

    def clear_for_time_jump(self, old_now: float | None = None) -> None:
        """Replay seek or loop: drop history that belongs to the old time; keep the attacks,
        and keep the incidents (closed at the moment of the jump)."""
        self.window.clear()
        self.incidents.close_all(self.clock.now() if old_now is None else old_now)
        self.real_incidents.close_all(self.clock.now() if old_now is None else old_now)
        self._end_alerts(set(), self.clock.now() if old_now is None else old_now)
        self.epoch += 1
        self.injector.epoch = self.epoch  # events reopened by injector.rebase() belong to the new epoch
        self._prev_states.clear()
        self._prev_flagged.clear()
        self.scenario = None  # a time jump cancels a running scenario (its times belong to the old clock)

    ALERT_LOG_MAX = 1000

    def _log_alerts(self, alerts: list[dict], now: float) -> None:
        """Alert history for GET /api/alerts?active=false: an alert is active while the tick still
        raises it, and ends when the aircraft passes or the cell clears (HANDOVER §6.3)."""
        for a in alerts:
            prev = self.alert_log.get(a["id"])
            first = prev["first_ts"] if prev and prev["active"] else now
            self.alert_log[a["id"]] = {**a, "first_ts": first, "last_ts": now, "active": True, "ended_ts": None}
        self._end_alerts({a["id"] for a in alerts}, now)
        if len(self.alert_log) > self.ALERT_LOG_MAX:  # forget the oldest ended alerts
            ended = sorted((a for a in self.alert_log.values() if not a["active"]), key=lambda a: a["ended_ts"])
            for a in ended[: len(self.alert_log) - self.ALERT_LOG_MAX]:
                del self.alert_log[a["id"]]

    def _end_alerts(self, still_active: set[str], now: float) -> None:
        for a in self.alert_log.values():
            if a["active"] and a["id"] not in still_active:
                a["active"], a["ended_ts"] = False, now

    def alert_history(self, active: bool) -> list[dict]:
        """Active alerts (as raised by the latest tick) or ended ones, newest first."""
        if active:
            return list((self.last_tick or {}).get("alerts", []))
        return sorted((dict(a) for a in self.alert_log.values() if not a["active"]), key=lambda a: -a["ended_ts"])

    def reset_experiment(self) -> None:
        """Fresh start: empty window, no attacks, no ground truth, no incidents."""
        self.window.clear()
        self.injector.clear_all()
        self.incidents.reset()
        self.real_incidents.reset()
        self.detections.clear()
        self.flag_log.clear()
        self.alert_log.clear()
        self._prev_states.clear()
        self._prev_flagged.clear()
        self.scenario = None
        self.persist_ground_truth()

    async def start(self, mode: str, files: list[str] | None = None, speed: float | None = None, start_ts: float | None = None) -> None:
        # Resolve the recordings BEFORE stopping anything: a bad name must leave the current mode running.
        chosen = self.replay_files(files) if mode == "replay" else None
        await self.stop_ingest()
        self.reset_experiment()
        self.mode = mode
        if mode == "live":
            self.clock.use_live()
            self.poller = LivePoller(self)
            self.ingest_task = asyncio.create_task(self.poller.run(), name="live-poller")
        else:
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
        if str(changes.get("hex") or "").lower() == "random":  # same meaning as in POST /api/attacks
            changes = {**changes, "hex": self.pick_random_aircraft()}
            if not changes["hex"]:
                raise LookupError("no airborne aircraft available to spoof right now")
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
        """Schedule a scenario's events. KeyError: no such scenario. ValueError: the file or one of
        its events is invalid (nothing is scheduled then)."""
        unreadable = []
        for p in sorted(Path(self.settings.scenarios_dir).glob("*.json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                if not isinstance(d, dict):
                    raise ValueError("the top level must be a JSON object")
            except (OSError, ValueError) as e:
                if p.stem == scenario_id:
                    raise ValueError(f"scenario file {p.name} is not valid: {e}") from None
                unreadable.append(p.name)
                continue
            if d.get("id", p.stem) == scenario_id:
                events = d.get("events", [])
                if not isinstance(events, list):
                    raise ValueError(f"scenario {scenario_id!r}: 'events' must be a list")
                now = self.clock.now()
                pending = sorted(((now + off, body) for off, body in
                                  (scenario_event(n, e) for n, e in enumerate(events, 1))), key=lambda x: x[0])
                self.scenario = {"id": scenario_id, "start_ts": now, "pending": pending, "fired": []}
                return self.scenario_status()
        hint = f" (unreadable scenario files: {', '.join(unreadable)})" if unreadable else ""
        raise KeyError(f"no scenario {scenario_id!r}{hint}")

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
        if self.dbw is not None:  # queued; a snapshot, the list keeps changing
            events = [dict(e) for e in self.injector.ground_truth]
            self.dbw.submit(functools.partial(sync_ground_truth, session=self.run_id, events=events), key=("ground_truth", self.run_id))

    def add_sentinel(self, packet: dict) -> dict:
        entry = self.sentinel.add(packet, time.time())
        if self.dbw is not None:  # queued
            self.dbw.submit(functools.partial(insert_sentinel, entry=dict(entry)))
        return entry

    def find_incident(self, incident_id: str) -> tuple[IncidentTracker | None, dict | None]:
        """Look an incident up in either view (ids differ by prefix: inc- simulator, air- live airspace)."""
        for tracker in (self.real_incidents, self.incidents):
            inc = tracker.get(incident_id)
            if inc is not None:
                return tracker, inc
        return None, None

    # ------------------------------------------------------------------ tick
    def _aircraft_rows(self, latest: dict[str, Record], flags: dict, cfg, now: float) -> list[dict]:
        rows = []
        for r in latest.values():
            pos = r.best_position()
            if pos is None:
                continue
            rows.append({
                "hex": r.hex, "flight": r.flight, "lat": round(pos[0], 5), "lon": round(pos[1], 5),
                "pos_lost": not r.has_position, "alt_baro": r.alt_baro, "alt_geom": r.alt_geom,
                "on_ground": r.on_ground, "gs": r.gs, "track": r.track, "nic": r.nic, "nac_p": r.nac_p,
                "source": r.source, "age_s": round(now - r.ts, 1), "bad": bad_reason(r, cfg),
                "spoof": flags.get(r.hex, []), "injected": r.injected,
            })
        return rows

    @staticmethod
    def _cells_with_spoofing(recs: list[Record], cfg) -> tuple[dict[str, CellStat], dict, dict]:
        cells = classify_cells(recs, cfg)
        flags = spoofing.flag_aircraft(recs, cfg)
        for cell, n_flagged in spoofing.spoofed_cells(flags, recs, cfg).items():
            if n_flagged >= 1:  # spoofed_cells already applied the strong/weak rule
                c = cells.get(cell) or CellStat(h3=cell, n_aircraft=n_flagged, n_bad=0, frac_bad=0.0, lower_bound=0.0, state="spoofing")
                c.state = "spoofing"
                cells[cell] = c
        flagged = spoofing.flagged_by_cell(flags, recs, cfg)
        return cells, flags, flagged

    def _real_view(self, recs: list[Record], latest: dict[str, Record], cfg, now: float, sentinel_alerts: list[dict]) -> dict:
        """Live airspace: the same detectors on the pristine records, with every simulated attack
        stripped out (each injected record keeps its original). Its incidents are tracked separately,
        so a judge's jammer never shows up, or opens a report, in Live airspace."""
        def pristine(r: Record) -> Record:
            return r.original if r.injected and r.original is not None else r

        real_recs = [pristine(r) for r in recs]
        real_latest = {h: pristine(r) for h, r in latest.items()}
        cells, flags, flagged = self._cells_with_spoofing(real_recs, cfg)
        for c in cells.values():
            label_injection(c, flagged.get(c.h3, ()), set())
        alarm_cells = {cell: c.state for cell, c in cells.items() if c.state in ALARM_STATES}
        alerts = warning.early_warnings(real_latest, alarm_cells, cfg, now) + sentinel_alerts
        self.real_incidents.update(cells, real_recs, cfg, now, flags)
        aircraft = self._aircraft_rows(real_latest, flags, cfg, now)
        state_counts: dict[str, int] = {}
        for c in cells.values():
            state_counts[c.state] = state_counts.get(c.state, 0) + 1
        self.real_state = {"ts": now, "mode": self.mode, "window_s": cfg.jam_window_s, "cells": cells, "flags": flags,
                           "spoof_by_cell": flagged, "injected_aircraft": set(), "records": real_recs,
                           "alerts": alerts, "incidents": self.real_incidents.summary()}
        return {"cells": to_geojson(cells), "aircraft": aircraft, "alerts": alerts,
                "incidents_summary": self.real_state["incidents"],
                "stats": {"aircraft": len(aircraft), "cells": state_counts}}

    def compute_tick(self) -> dict:
        now = self.clock.now()
        cfg = get_detection()
        self._fire_scenario_events(now)
        self.window.prune(now)
        recs = self.window.since(now - cfg.jam_window_s, now)

        cells, flags, flagged = self._cells_with_spoofing(recs, cfg)
        spoof_flagged = {h for h, why in flags.items() if SPOOF_REASONS.intersection(why)}
        for h in spoof_flagged - self._prev_flagged:
            self.flag_log.append({"ts": now, "hex": h, "reasons": flags[h], "epoch": self.epoch})
        self._prev_flagged = spoof_flagged
        # Injected = ANY simulated effect in the cell; mixed = simulated and real ones together.
        injected_aircraft = {r.hex for r in recs if r.injected}
        for cell, c in cells.items():
            label_injection(c, flagged.get(cell, ()), injected_aircraft)

        for cell, c in cells.items():
            if c.state in ALARM_STATES and self._prev_states.get(cell) != c.state:
                self.detections.append({"ts": now, "h3": cell, "state": c.state, "n_bad": c.n_bad,
                                        "n_aircraft": c.n_aircraft, "n_injected": c.n_injected,
                                        "injected": c.injected, "mixed": c.mixed, "epoch": self.epoch})
        self._prev_states = {cell: c.state for cell, c in cells.items()}

        latest = self.latest_aircraft()
        alarm_cells = {cell: c.state for cell, c in cells.items() if c.state in ALARM_STATES}
        injected_cells = {cell for cell, c in cells.items() if c.state in ALARM_STATES and c.injected}
        mixed_cells = {cell for cell, c in cells.items() if c.state in ALARM_STATES and c.mixed}
        alerts = warning.early_warnings(latest, alarm_cells, cfg, now, injected_cells, mixed_cells)
        sentinel_alerts = self.sentinel.alerts(time.time())
        alerts += sentinel_alerts
        self._log_alerts(alerts, now)
        self.incidents.update(cells, recs, cfg, now, flags)
        real = self._real_view(recs, latest, cfg, now, sentinel_alerts)

        for a in self.injector.live_attacks(now):
            self.injector.record_coverage(a, self.injector.aircraft_inside(a, latest.values()))

        aircraft = self._aircraft_rows(latest, flags, cfg, now)

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
            # Live airspace reads this block: the same detectors on real data only (no simulated attacks).
            # Everything above is the Attack Simulator's view (real + injected).
            "real": real,
        }
        self.last_tick = payload
        # What the AI summary (app/ai/summary.py) may describe: rule-engine output of this tick only.
        self.tick_state = {"ts": now, "mode": self.mode, "window_s": cfg.jam_window_s, "cells": cells, "flags": flags,
                           "spoof_by_cell": flagged, "injected_aircraft": injected_aircraft, "records": recs,
                           "alerts": alerts, "incidents": payload["incidents_summary"]}
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
            "ai": self.ai.status(),
            "tick_s": self.settings.tick_s,
            "run_id": self.run_id,
            "regions": sorted(REGIONS),
            "recordings_dir": str(Path(self.settings.recordings_dir)),
        }
