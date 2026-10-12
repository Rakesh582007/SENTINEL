"""Evaluation against injected ground truth (HANDOVER §6.5).

The demo slide: "detected X of Y injected attacks, Z unexplained alarms,
median time-to-detect T s". Measured, not claimed.

    evaluate(ground_truth, detections, cfg, now, coverage, flag_log=()) -> dict

- ground_truth: injector events {attack_id, kind, start_ts, end_ts, center, radius_km, hex, ...}
- detections:   runtime log of cells ENTERING "jammed"/"spoofing" {ts, h3, state, n_injected, ...}
- flag_log:     runtime log of aircraft newly flagged by spoofing.py {ts, hex, reasons}
- coverage:     {attack_id: most aircraft ever inside that jammer's circle}

Outcomes per event:
- detected:     a jamming event, if a cell overlapping its circle entered "jammed"
                within cfg.eval_detect_within_s of its start; a spoof event, if its
                aircraft got a spoofing flag within that time.
- pending:      not detected yet, but the time allowed has not run out.
- undetectable: a jamming event whose circle never held cfg.min_aircraft aircraft.
                The crowd method cannot see it; counting it as a miss would be
                unfair, hiding it would be dishonest, so it is reported apart.
- missed:       everything else.
An alarm that matches no event is "unexplained". On live data that can be REAL
interference, so it is never called a false alarm.
"""
from __future__ import annotations

import statistics

import h3

from app.config import DetectionConfig
from app.detect.geo import haversine_km
from app.detect.spoofing import SPOOF_REASONS

SLACK_S = 15.0  # a detection logged up to one poll before the recorded start still counts


def _cell_overlaps(cell: str, center, radius_km: float) -> bool:
    lat, lon = h3.cell_to_latlng(cell)
    edge = h3.average_hexagon_edge_length(h3.get_resolution(cell), unit="km")
    return haversine_km(lat, lon, center[0], center[1]) <= radius_km + edge


def evaluate(ground_truth: list[dict], detections: list[dict], cfg: DetectionConfig, now: float,
             coverage: dict[str, int], flag_log: list[dict] | tuple = ()) -> dict:
    per_event, used = [], set()
    for ev in ground_truth:
        start, window_end = ev["start_ts"], ev["start_ts"] + cfg.eval_detect_within_s
        hit = None
        if ev["kind"] == "jamming":
            for i, d in enumerate(detections):
                if d["state"] == "jammed" and start - SLACK_S <= d["ts"] <= window_end and _cell_overlaps(d["h3"], ev["center"], ev["radius_km"]):
                    hit = d
                    used.add(i)
                    break
        else:
            for f in flag_log:
                if f["hex"] == ev["hex"] and start - SLACK_S <= f["ts"] <= window_end and SPOOF_REASONS.intersection(f["reasons"]):
                    hit = f
                    break
            for i, d in enumerate(detections):  # the purple cell it caused is explained too
                if d["state"] == "spoofing" and start - SLACK_S <= d["ts"] <= window_end:
                    used.add(i)
        if hit is not None:
            outcome, ttd = "detected", max(0.0, hit["ts"] - start)
        elif now < window_end:
            outcome, ttd = "pending", None
        elif ev["kind"] == "jamming" and coverage.get(ev["attack_id"], 0) < cfg.min_aircraft:
            outcome, ttd = "undetectable", None
        else:
            outcome, ttd = "missed", None
        per_event.append({"attack_id": ev["attack_id"], "kind": ev["kind"], "start_ts": start, "end_ts": ev["end_ts"],
                          "outcome": outcome, "time_to_detect_s": None if ttd is None else round(ttd, 1),
                          "max_aircraft_inside": coverage.get(ev["attack_id"])})

    counts = {k: sum(1 for e in per_event if e["outcome"] == k) for k in ("detected", "missed", "undetectable", "pending")}
    unexplained = [d for i, d in enumerate(detections) if i not in used]
    ttds = [e["time_to_detect_s"] for e in per_event if e["time_to_detect_s"] is not None]
    scored = counts["detected"] + counts["missed"]
    return {
        "events": len(per_event),
        **counts,
        "detection_rate": round(counts["detected"] / scored, 3) if scored else None,
        "unexplained_alarms": len(unexplained),
        "unexplained_real_data": sum(1 for d in unexplained if not (d.get("injected") or d.get("n_injected"))),
        "median_time_to_detect_s": round(statistics.median(ttds), 1) if ttds else None,
        "per_event": per_event,
        "note": "Unexplained alarms on live data may be real interference; they are not counted as false alarms.",
    }
