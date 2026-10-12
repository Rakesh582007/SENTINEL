"""Plain-English summaries of a hexagon or an incident (decision D22: AI words, rules decide).

- Detection is 100% rule-based. This module only rewords facts the rule engine already
  computed (build_cell_facts / build_incident_facts); nothing here changes a state, a flag
  or an alert.
- Gemini is asked first: each model in GAW_AI_MODELS in turn, GAW_AI_TIMEOUT_S each. With no
  key, AI switched off, the global rate limit (GAW_AI_MAX_PER_MIN) reached, or every model
  failing (timeout, quota 429, offline venue Wi-Fi, empty answer), a deterministic template
  built in Python from the same facts is used instead.
- Never called from the tick: only on request (GET /api/cells/{h3}/summary,
  GET /api/incidents/{id}/summary and the incident PDF).
- The API key is never logged; errors are scrubbed of it.

    facts = build_cell_facts(h3_id, rt.tick_state)          # None: not in the current state
    result = await rt.ai.summarize("cell", h3_id, facts, cell_cache_key(facts), now_ts)
    -> {id, summary, source: "ai"|"template", model, label, generated_ts, cached, facts}
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Callable

import h3

from app.detect.spoofing import SPOOF_REASONS
from app.report.pdf import latlon_text

log = logging.getLogger("gaw.ai")

SYSTEM_INSTRUCTION = """You write short status notes for GPS Attack Watch, a receive-only system that detects GPS jamming and spoofing from public aircraft ADS-B data.
Rules:
- Use only the facts in the JSON you are given. Invent no numbers, places, aircraft, times or causes.
- Never say or guess who is jamming or spoofing. If an area estimate is given, call it an "approximate area for investigation".
- Never say that this system transmits anything or alerts aircraft directly. Warnings go to air traffic controllers and airlines.
- If "injected" is true, the first sentence must say this is a simulated test attack. If "mixed" is true, also say that real (non-injected) GPS problems are present too.
- If "state" is "insufficient", say there are too few aircraft here to judge.
- Write 2 to 4 sentences of plain English, under 90 words, with no markdown, lists or headings."""

LABEL_AI = "AI-written summary"
LABEL_TEMPLATE = "Auto summary"
IST_OFFSET_S = 5.5 * 3600
MAX_WORDS = 110  # the prompt asks for < 90; longer answers are cut at a sentence end

STATE_MEANING = {
    "insufficient": "too few aircraft in this hexagon to judge GPS health",
    "clear": "aircraft here report healthy GPS",
    "degraded": "a few aircraft report weak GPS, below the jamming threshold",
    "jammed": "many aircraft report degraded or lost GPS: GPS jamming detected",
    "spoofing": "aircraft report physically impossible positions or altitudes: suspected GPS spoofing",
}
REASON_WORDS = {
    "low_nacp": "low position accuracy (NACp)",
    "low_nic": "low position integrity (NIC)",
    "position_lost": "position lost while still transmitting",
    "gps_lost_flag": "GPS loss seen by the receiver network",
    "impossible_jump": "impossible position jumps",
    "colocation_cluster": "several aircraft stacked on one spot",
    "alt_offset_outlier": "GPS altitude out of line with nearby aircraft",
    "track_mismatch": "a reported track that does not match the movement",
}


def ist(ts: float | None) -> str | None:
    return None if ts is None else time.strftime("%d %b %H:%M IST", time.gmtime(ts + IST_OFFSET_S))


def _area(inc: dict) -> dict | None:
    if inc.get("est_lat") is None:
        return None
    return {"lat": inc["est_lat"], "lon": inc["est_lon"], "radius_km": inc["est_radius_km"]}


# ---------------------------------------------------------------------- facts (rule-engine output only)
def build_cell_facts(h3_id: str, tick_state: dict | None) -> dict | None:
    """Everything the rule engine says about one hexagon at the latest tick; None if the
    hexagon is not in the current state."""
    if not tick_state or h3_id not in tick_state["cells"]:
        return None
    c = tick_state["cells"][h3_id]
    flags = tick_state["flags"]
    injected_aircraft = tick_state["injected_aircraft"]
    wanted = set(c.bad_hexes) | set(tick_state["spoof_by_cell"].get(h3_id, ()))
    flights = {r.hex: r.flight for r in tick_state["records"] if r.hex in wanted and r.flight}
    aircraft = [{"flight": flights.get(hx), "hex": hx, "bad_reason": c.bad_reasons.get(hx),
                 "spoof_reasons": sorted(SPOOF_REASONS.intersection(flags.get(hx, ()))), "injected": hx in injected_aircraft}
                for hx in sorted(wanted)]
    lat, lon = h3.cell_to_latlng(h3_id)
    warnings = sorted(({"flight": a.get("flight"), "hex": a["hex"], "eta_s": a["eta_s"]} for a in tick_state["alerts"]
                       if a.get("kind") == "early_warning" and a.get("h3") == h3_id), key=lambda w: w["eta_s"])
    inc = next((i for i in tick_state["incidents"] if i["open"] and h3_id in i["cells"]), None)
    return {
        "subject": "hexagon", "h3": h3_id, "state": c.state, "state_meaning": STATE_MEANING.get(c.state, c.state),
        "n_aircraft": c.n_aircraft, "n_bad": c.n_bad, "frac_bad": round(c.frac_bad, 3), "lower_bound": round(c.lower_bound, 3),
        "reasons": dict(c.reasons), "n_injected": c.n_injected, "injected": c.injected, "mixed": c.mixed,
        "centre": {"lat": round(lat, 3), "lon": round(lon, 3)}, "window_min": round(tick_state["window_s"] / 60),
        "flagged_aircraft": aircraft[:12], "n_flagged_aircraft": len(aircraft), "early_warnings": warnings[:8],
        "open_incident": None if inc is None else {"id": inc["id"], "kind": inc["kind"], "opened": ist(inc["opened_ts"]),
                                                   "approximate_area_for_investigation": _area(inc)},
        "mode": tick_state["mode"], "time": ist(tick_state["ts"]),
    }


def build_incident_facts(incident_id: str, incidents, mode: str, now: float) -> dict | None:
    """The same for an incident (incidents = the IncidentTracker); None if it does not exist."""
    inc = incidents.get(incident_id)
    if inc is None:
        return None
    aircraft = [{"flight": a.get("flight"), "hex": a["hex"], "reason": a["reason"], "first_problem": ist(a["first_bad_ts"]),
                 "injected": bool(a.get("injected"))} for a in inc.get("aircraft", [])]
    return {
        "subject": "incident", "id": inc["id"], "kind": inc["kind"],
        "kind_meaning": "GPS jamming" if inc["kind"] == "jamming" else "suspected GPS spoofing",
        "state": "open" if inc["open"] else "closed", "open": inc["open"],
        "opened": ist(inc["opened_ts"]), "closed": ist(inc["closed_ts"]),
        "n_aircraft": inc["n_aircraft"], "peak_aircraft_in_a_hexagon": inc.get("peak_aircraft"), "n_cells": len(inc["cells"]),
        "max_frac_bad": inc.get("max_frac_bad"), "injected": inc["injected"], "mixed": inc["mixed"],
        "approximate_area_for_investigation": _area(inc), "aircraft": aircraft[:12],
        "mode": mode, "time": ist(now),
    }


def cell_cache_key(f: dict) -> tuple:
    return (f["state"], f["n_bad"], f["n_aircraft"], f["injected"], f["mixed"])


def incident_cache_key(f: dict) -> tuple:
    return (f["state"], f["n_aircraft"], f["n_cells"], f["injected"], f["mixed"])


# ---------------------------------------------------------------------- template (offline fallback)
def _injected_lead(f: dict) -> list[str]:
    if not f.get("injected"):
        return []
    out = ["This is a simulated test attack (INJECTED TEST ATTACK) from the Attack Simulator, not a real-world event."]
    if f.get("mixed"):
        out.append("Real (non-injected) GPS problems are also present here.")
    return out


def _words(codes) -> str:
    names = [REASON_WORDS.get(c, c.replace("_", " ")) for c in codes]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def template_cell(f: dict) -> str:
    s = _injected_lead(f)
    n, k, win, state = f["n_aircraft"], f["n_bad"], f["window_min"], f["state"]
    if state == "insufficient":
        s.append(f"Only {n} aircraft {'was' if n == 1 else 'were'} seen in this hexagon in the last {win} minutes, "
                 "too few to judge GPS health here.")
    elif state == "jammed":
        top = [code for code, _ in sorted(f["reasons"].items(), key=lambda kv: -kv[1])[:2]]
        s.append(f"{k} of {n} aircraft here ({round(100 * f['frac_bad'])}%) reported degraded or lost GPS in the last "
                 f"{win} minutes{', mainly ' + _words(top) if top else ''}: GPS jamming is detected in this area.")
    elif state == "spoofing":
        spoofed = [a for a in f["flagged_aircraft"] if a["spoof_reasons"]]
        codes = sorted({r for a in spoofed for r in a["spoof_reasons"]})
        who = "One aircraft here shows" if len(spoofed) == 1 else f"{len(spoofed)} aircraft here show"
        s.append(f"{who} {_words(codes) if codes else 'physically impossible positions or altitudes'}, "
                 "a sign of suspected GPS spoofing.")
    elif state == "degraded":
        s.append(f"{k} of {n} aircraft here reported weak GPS in the last {win} minutes, not enough for a jamming alarm.")
    else:
        s.append(f"All {n} aircraft seen here in the last {win} minutes reported healthy GPS.")
    warnings = f["early_warnings"]
    if warnings:
        first = warnings[0]
        name = first["flight"] or first["hex"].upper()
        mins = max(1, round(first["eta_s"] / 60))
        if len(warnings) == 1:
            s.append(f"{name} is projected to enter in about {mins} min; controllers and airlines should prepare backup navigation.")
        else:
            s.append(f"{len(warnings)} flights are projected to enter, {name} first in about {mins} min; "
                     "controllers and airlines should prepare backup navigation.")
    inc = f["open_incident"]
    if inc:
        area = inc["approximate_area_for_investigation"]
        tail = (f"; approximate area for investigation: {latlon_text(area['lat'], area['lon'])}, within about "
                f"{area['radius_km']:.0f} km." if area else ".")
        s.append(f"Incident {inc['id']} has been open since {inc['opened']}{tail}")
    return " ".join(s)


def template_incident(f: dict) -> str:
    s = _injected_lead(f)
    n, cells = f["n_aircraft"], f["n_cells"]
    when = f"open since {f['opened']}" if f["open"] else f"from {f['opened']} to {f['closed']}"
    who = "a single aircraft" if n == 1 else f"{n} aircraft"
    s.append(f"Incident {f['id']} ({f['kind_meaning']}, {when}): {who} affected across {cells} hexagon{'' if cells == 1 else 's'}.")
    if f["kind"] == "jamming" and f.get("max_frac_bad"):
        s.append(f"At its peak {round(100 * f['max_frac_bad'])}% of the aircraft in a hexagon had bad GPS.")
    area = f["approximate_area_for_investigation"]
    if area:
        s.append(f"Approximate area for investigation: {latlon_text(area['lat'], area['lon'])}, within about {area['radius_km']:.0f} km.")
    if n == 1:
        s.append("One aircraft alone is not proof of interference.")
    return " ".join(s)


def template_summary(kind: str, facts: dict) -> str:
    return template_cell(facts) if kind == "cell" else template_incident(facts)


# ---------------------------------------------------------------------- AI answer hygiene
def clean_ai_text(text: str | None, facts: dict) -> str:
    """No markdown, one paragraph, at most MAX_WORDS (cut at a sentence end), and an injected
    test always says so first, whatever the model wrote."""
    if not text:
        return ""
    t = re.sub(r"[*#`]+", "", text)
    t = re.sub(r"(?m)^\s*[-•]\s+", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t.split()) > MAX_WORDS:
        kept, count = [], 0
        for sentence in re.split(r"(?<=[.!?])\s+", t):
            n = len(sentence.split())
            if kept and count + n > MAX_WORDS:
                break
            kept.append(sentence)
            count += n
        t = " ".join(kept)
        if len(t.split()) > MAX_WORDS:
            t = " ".join(t.split()[:MAX_WORDS]) + " ..."
    first = re.split(r"(?<=[.!?])\s+", t, maxsplit=1)[0].lower()
    if t and facts.get("injected") and "simulat" not in first:
        t = "Simulated test attack (INJECTED TEST ATTACK). " + t
    return t


def _default_client(api_key: str):
    from google import genai  # imported only when a key is configured

    return genai.Client(api_key=api_key)


def _model_config(model: str) -> dict:
    cfg: dict[str, Any] = {"system_instruction": SYSTEM_INSTRUCTION, "temperature": 0.2, "max_output_tokens": 400}
    if model.startswith("gemini-2.5-flash"):
        cfg["thinking_config"] = {"thinking_budget": 0}  # a short note needs no thinking: faster, cheaper
    return cfg


# ---------------------------------------------------------------------- the summarizer
class Summarizer:
    def __init__(self, settings, client_factory: Callable[[str], Any] | None = None) -> None:
        self.settings = settings
        self._client_factory = client_factory or _default_client
        self._client = None
        self._cache: dict[tuple, tuple[float, dict]] = {}
        self._inflight: dict[tuple, asyncio.Future] = {}
        self._calls: list[float] = []  # monotonic times of Gemini calls in the last minute (real-world quota)
        self.last_model_used: str | None = None
        self.last_error: str | None = None

    def _key(self) -> str:
        return self.settings.gemini_api_key.get_secret_value().strip()

    def _scrub(self, msg: str) -> str:
        key = self._key()
        msg = msg.replace(key, "***") if key else msg
        return msg[:300]

    def status(self) -> dict:
        return {"enabled": self.settings.ai_enabled, "key_present": bool(self._key()), "models": self.settings.ai_model_list,
                "last_model_used": self.last_model_used, "last_error": self.last_error}

    def template_result(self, kind: str, ident: str, facts: dict, now_ts: float) -> dict:
        return {"id": ident, "summary": template_summary(kind, facts), "source": "template", "model": None,
                "label": LABEL_TEMPLATE, "generated_ts": now_ts, "cached": False, "facts": facts}

    async def summarize(self, kind: str, ident: str, facts: dict, cache_key: tuple, now_ts: float) -> dict:
        key = (kind, ident, *cache_key)
        now = time.monotonic()
        self._cache = {k: v for k, v in self._cache.items() if now - v[0] < self.settings.ai_cache_ttl_s}
        if key in self._cache:
            return {**self._cache[key][1], "cached": True}
        task = self._inflight.get(key)
        shared = task is not None
        if task is None:  # one Gemini call per key, even when the PDF and the panel ask at once
            task = asyncio.ensure_future(self._produce(kind, ident, facts, now_ts))
            self._inflight[key] = task
            task.add_done_callback(lambda _t, k=key: self._inflight.pop(k, None))
        result = await asyncio.shield(task)
        self._cache[key] = (time.monotonic(), result)
        return {**result, "cached": shared}

    async def _produce(self, kind: str, ident: str, facts: dict, now_ts: float) -> dict:
        text, model = await self._ask_ai(kind, ident, facts)
        if not text:
            return self.template_result(kind, ident, facts, now_ts)
        return {"id": ident, "summary": text, "source": "ai", "model": model, "label": LABEL_AI,
                "generated_ts": now_ts, "cached": False, "facts": facts}

    def _take_rate_slot(self) -> bool:
        now = time.monotonic()
        self._calls = [t for t in self._calls if now - t < 60.0]
        if len(self._calls) >= self.settings.ai_max_per_min:
            return False
        self._calls.append(now)
        return True

    def _get_client(self):
        if self._client is None:
            try:
                self._client = self._client_factory(self._key())
            except Exception as e:
                self.last_error = f"client: {type(e).__name__}: {self._scrub(str(e))}"
                log.warning("AI summary unavailable (%s); using the template", type(e).__name__)
                return None
        return self._client

    async def _ask_ai(self, kind: str, ident: str, facts: dict) -> tuple[str | None, str | None]:
        if not self.settings.ai_enabled or not self._key():
            return None, None
        client = self._get_client()
        if client is None:
            return None, None
        prompt = "Facts (JSON, computed by the rule engine):\n" + json.dumps(facts, ensure_ascii=False) + "\n\nWrite the note."
        for model in self.settings.ai_model_list:
            if not self._take_rate_slot():
                self.last_error = f"rate limit reached ({self.settings.ai_max_per_min}/min)"
                log.info("AI summary for %s %s: rate limit reached; using the template", kind, ident)
                return None, None
            t0 = time.monotonic()
            try:
                resp = await asyncio.wait_for(
                    client.aio.models.generate_content(model=model, contents=prompt, config=_model_config(model)),
                    timeout=self.settings.ai_timeout_s)
                text = clean_ai_text(getattr(resp, "text", None), facts)
            except Exception as e:  # timeout, quota (429), network, unknown model, ...
                ms = (time.monotonic() - t0) * 1000
                self.last_error = f"{model}: {type(e).__name__}: {self._scrub(str(e))}"
                log.warning("AI summary for %s %s: %s failed after %.0f ms (%s); trying the next model",
                            kind, ident, model, ms, type(e).__name__)
                continue
            ms = (time.monotonic() - t0) * 1000
            if not text:
                self.last_error = f"{model}: empty answer"
                log.warning("AI summary for %s %s: %s gave an empty answer after %.0f ms", kind, ident, model, ms)
                continue
            self.last_model_used, self.last_error = model, None
            log.info("AI summary for %s %s by %s in %.0f ms", kind, ident, model, ms)
            return text, model
        return None, None
