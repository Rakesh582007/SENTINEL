"""Evaluation against injected ground truth (HANDOVER §6.5).  STATUS: TODO

The demo slide: "detected X of Y injected attacks, Z false alarms, median
time-to-detect T s". Measured, not claimed.

Inputs already collected by the runtime:
- injector.ground_truth: [{"attack_id", "kind", "start_ts", "end_ts",
  "center", "radius_km", "hex", ...}] (one per simulated attack)
- runtime.detections: [{"ts", "h3", "state", "n_bad", "n_aircraft",
  "n_injected"}] appended whenever a cell ENTERS "jammed" or "spoofing"

Contract:  evaluate(ground_truth, detections, cfg, now, coverage) -> dict

Rules:
- A jamming event is detected if a cell overlapping its circle enters "jammed"
  within cfg.eval_detect_within_s of start_ts. A spoof event is detected if its
  hex gets a spoofing flag within the same time.
- An alarm with no matching ground truth is a false alarm (in live data it may
  also be REAL interference; label it "unexplained", not "false").
- IMPORTANT: report "undetectable" separately: events whose circle had fewer
  than cfg.min_aircraft aircraft during the event. With free data many border
  cells are that sparse; counting those as misses is unfair, hiding them is
  dishonest. `coverage` = {attack_id: max aircraft inside the circle}.
Return: {"events": n, "detected": n, "missed": n, "undetectable": n,
         "unexplained_alarms": n, "median_time_to_detect_s": float | None,
         "per_event": [...]}
"""
from __future__ import annotations

from app.config import DetectionConfig


def evaluate(ground_truth: list[dict], detections: list[dict], cfg: DetectionConfig, now: float, coverage: dict[str, int]) -> dict:
    raise NotImplementedError("evaluate.py: implement per the module docstring")
