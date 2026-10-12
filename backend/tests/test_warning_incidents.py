import h3

from app.config import DetectionConfig
from app.detect.evaluate import evaluate
from app.detect.incidents import IncidentTracker
from app.detect.jamming import classify_cells
from app.detect.warning import early_warnings
from app.ingest.injector import Injector
from app.report.pdf import incident_pdf, latlon_text, summary_text
from conftest import make, pdf_text

CFG = DetectionConfig()
JAM = (31.6, 74.9)
CELL = h3.latlng_to_cell(*JAM, CFG.h3_res)


def test_inbound_aircraft_gets_eta_outbound_does_not():
    east = make("inbound", 31.6, 73.85, track=90.0, gs=400.0)  # ~100 km west of the cell, heading east
    west = make("outbnd", 31.6, 73.85, track=270.0, gs=400.0)
    alerts = early_warnings({r.hex: r for r in (east, west)}, {CELL: "jammed"}, CFG, now=east.ts)
    assert [a["hex"] for a in alerts] == ["inbound"]
    assert 300 <= alerts[0]["eta_s"] <= 900 and alerts[0]["path"] and "min" in alerts[0]["message"]


def test_aircraft_already_inside_gets_no_warning():
    inside = make("inside", *JAM, track=90.0)
    assert early_warnings({"inside": inside}, {CELL: "jammed"}, CFG, now=inside.ts) == []


def jammed_window(now=1000.0):
    inj = Injector()
    inj.add_jamming(JAM, 80, 1.0, 0.0, None, now=now)
    recs = inj.apply([make(f"{i:06x}", JAM[0] + i * 0.002, JAM[1], ts=now) for i in range(12)], now=now)
    return inj, recs


def test_incident_opens_estimates_area_and_closes():
    inj, recs = jammed_window()
    tr = IncidentTracker()
    tr.update(classify_cells(recs, CFG), recs, CFG, now=1000)
    [inc] = tr.summary()
    assert inc["kind"] == "jamming" and inc["open"] and inc["injected"] and inc["n_aircraft"] == 12
    assert abs(inc["est_lat"] - JAM[0]) < 0.1 and inc["est_radius_km"] >= CFG.jammer_min_radius_km
    tr.update({}, [], CFG, now=1000 + CFG.incident_close_s + 1)
    assert not tr.summary()[0]["open"]


def test_pdf_renders():
    inj, recs = jammed_window()
    tr = IncidentTracker()
    tr.update(classify_cells(recs, CFG), recs, CFG, now=1000)
    pdf = incident_pdf(tr.get(tr.summary()[0]["id"]))
    assert pdf[:4] == b"%PDF" and len(pdf) > 2000


def test_pdf_summary_is_worded_by_aircraft_count_and_hemispheres_follow_the_signs():
    """Audit N9."""
    base = {"id": "inc-x", "kind": "spoofing", "opened_ts": 1000.0, "closed_ts": None, "cells": [CELL],
            "est_lat": None, "est_lon": None, "est_radius_km": None, "max_frac_bad": 0.0}
    one = summary_text({**base, "n_aircraft": 1})
    assert "a single aircraft" in one and "several independent" not in one and "area above" not in one
    assert "3 aircraft" in summary_text({**base, "n_aircraft": 3}) and "several independent" in summary_text({**base, "n_aircraft": 3})
    assert "no individual aircraft" in summary_text({**base, "n_aircraft": 0})
    assert "area above" in summary_text({**base, "kind": "jamming", "n_aircraft": 3, "est_lat": 31.6, "est_lon": 74.9})
    assert latlon_text(31.6, 74.9) == "31.600 N, 74.900 E"
    assert latlon_text(-33.87, -70.65) == "33.870 S, 70.650 W"
    pdf = incident_pdf({**base, "n_aircraft": 1, "aircraft": [{"hex": "abc123", "flight": "X1", "first_bad_ts": 1000.0,
                                                               "reason": "impossible_jump", "alt_baro": 30000, "injected": None}]})
    assert "a single aircraft" in pdf_text(pdf)


def test_evaluation_counts_detected_undetectable_and_unexplained():
    gt = [
        {"attack_id": "jam-1", "kind": "jamming", "start_ts": 100, "end_ts": 400, "center": JAM, "radius_km": 60, "hex": None},
        {"attack_id": "jam-2", "kind": "jamming", "start_ts": 100, "end_ts": 400, "center": (34.5, 78.0), "radius_km": 30, "hex": None},
        {"attack_id": "spoof-3", "kind": "spoof", "start_ts": 100, "end_ts": 400, "center": None, "radius_km": 0, "hex": "abc123"},
    ]
    detections = [
        {"ts": 130, "h3": CELL, "state": "jammed", "n_injected": 5},
        {"ts": 200, "h3": h3.latlng_to_cell(20.0, 80.0, 3), "state": "jammed", "n_injected": 0},  # real-data alarm
    ]
    flags = [{"ts": 115, "hex": "abc123", "reasons": ["impossible_jump"]}]
    out = evaluate(gt, detections, CFG, now=1000, coverage={"jam-1": 12, "jam-2": 1}, flag_log=flags)
    assert (out["detected"], out["undetectable"], out["missed"]) == (2, 1, 0)
    assert out["unexplained_alarms"] == 1 and out["unexplained_real_data"] == 1
    assert out["median_time_to_detect_s"] == 22.5


def test_more_cells_of_the_same_jammer_are_explained_but_real_ones_nearby_are_not():
    gt = [{"attack_id": "jam-1", "kind": "jamming", "start_ts": 100, "end_ts": None, "center": JAM, "radius_km": 150, "hex": None}]
    neighbour = h3.grid_disk(CELL, 1)[1]
    detections = [
        {"ts": 130, "h3": CELL, "state": "jammed", "n_injected": 5, "injected": True},
        {"ts": 700, "h3": neighbour, "state": "jammed", "n_injected": 3, "injected": True},  # later, same jammer
        {"ts": 800, "h3": neighbour, "state": "jammed", "n_injected": 0, "injected": False},  # real interference
    ]
    out = evaluate(gt, detections, CFG, now=1000, coverage={}, flag_log=[])
    assert (out["detected"], out["unexplained_alarms"], out["unexplained_real_data"]) == (1, 1, 1)
