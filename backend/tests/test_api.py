"""API smoke tests. GAW_AUTOSTART=false (conftest), so no network and no background tasks."""
import time

import pytest
from fastapi.testclient import TestClient

from app.ingest.recording import append_line, make_line
from app.ingest.replay import Replayer
from app.main import app
from conftest import POLL_TS, make


@pytest.fixture
def client():
    with TestClient(app) as c:
        rt = c.app.state.rt
        rt.reset_experiment()
        rt.clock.use_replay(POLL_TS)
        yield c


def seed(client, n=12):
    rt = client.app.state.rt
    rt.ingest_records([make(f"{i:06x}", 31.6 + i * 0.01, 74.9, ts=POLL_TS - 5) for i in range(n)], now=POLL_TS)
    return rt


def test_health_and_map(client):
    seed(client)
    assert client.get("/api/health").json()["n_aircraft"] == 12
    client.app.state.rt.compute_tick()
    cells = client.get("/api/cells").json()
    assert cells["type"] == "FeatureCollection" and cells["features"]
    assert len(client.get("/api/aircraft").json()) == 12


def test_detection_sliders_validate(client):
    assert client.patch("/api/config/detection", json={"nacp_bad": 6}).json()["nacp_bad"] == 6
    assert client.patch("/api/config/detection", json={"nacp_bad": 20}).status_code == 422
    assert client.delete("/api/config/detection").json()["nacp_bad"] == 7


def test_jammer_lifecycle_turns_cell_red_then_reset_clears_it(client):
    rt = seed(client, 20)
    r = client.post("/api/attacks", json={"kind": "jamming", "center": [31.7, 74.9], "radius_km": 150, "strength": 1.0})
    assert r.status_code == 200 and r.json()["aircraft_now"] == 20
    attack_id = r.json()["attack_id"]
    rt.ingest_records([make(f"{i:06x}", 31.6 + i * 0.01, 74.91, ts=POLL_TS) for i in range(20)], now=POLL_TS)
    states = {f["properties"]["state"] for f in rt.compute_tick()["cells"]["features"]}
    assert "jammed" in states
    assert client.patch(f"/api/attacks/{attack_id}", json={"strength": 0.5}).status_code == 200
    assert client.delete("/api/attacks").json()["records_restored"] > 0
    states = {f["properties"]["state"] for f in rt.compute_tick()["cells"]["features"]}
    assert "jammed" not in states


def test_spoof_random_needs_aircraft(client):
    assert client.post("/api/attacks", json={"kind": "spoof", "hex": "random"}).status_code == 409
    seed(client)
    r = client.post("/api/attacks", json={"kind": "spoof", "hex": "random", "offset_km": 30})
    assert r.status_code == 200 and r.json()["attack"]["hex"]


def test_preview_warns_when_too_sparse(client):
    seed(client, 1)
    p = client.get("/api/attacks/preview", params={"lat": 31.6, "lon": 74.9, "radius_km": 20}).json()
    assert p["likely_detectable"] is False and p["hint"]


def test_full_chain_jammer_to_incident_pdf_and_evaluation(client):
    rt = seed(client, 20)
    client.post("/api/attacks", json={"kind": "jamming", "center": [31.7, 74.9], "radius_km": 150, "strength": 1.0})
    rt.ingest_records([make(f"{i:06x}", 31.6 + i * 0.01, 74.91, ts=POLL_TS) for i in range(20)], now=POLL_TS)
    rt.compute_tick()
    incs = client.get("/api/incidents").json()
    assert incs and incs[0]["kind"] == "jamming" and incs[0]["injected"] and incs[0]["est_radius_km"] >= 15
    pdf = client.get(f"/api/incidents/{incs[0]['id']}/report.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    ev = client.get("/api/evaluation").json()
    assert ev["events"] == 1 and ev["detected"] == 1 and ev["median_time_to_detect_s"] == 0.0


def test_scenarios_list_and_run(client):
    seed(client)
    listed = client.get("/api/scenarios").json()
    assert any(s["id"] == "demo1" for s in listed["available"])
    st = client.post("/api/scenarios/demo1/run").json()
    assert st["remaining"] == 3
    rt = client.app.state.rt
    rt.clock.set(POLL_TS + 130)
    rt.compute_tick()
    assert client.get("/api/scenarios").json()["running"]["fired"][0].startswith("jam-")
    assert client.post("/api/scenarios/nope/run").status_code == 404


def test_sentinel_post_and_latest(client):
    r = client.post("/api/sentinel", json={"id": "sentinel-1", "fix": True, "sats_used": 8, "avg_snr": 38.5, "status": "ok"})
    assert r.json()["status"] == "OK"
    latest = client.get("/api/sentinel/latest").json()
    assert latest[0]["id"] == "sentinel-1" and latest[0]["status"] == "OK"
    store = client.app.state.rt.sentinel
    assert store.latest(time.time() + 60)[0]["status"] == "OFFLINE"


def test_websocket_sends_latest_tick_on_connect(client):
    seed(client)
    client.app.state.rt.compute_tick()
    with client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
    assert msg["type"] == "tick" and msg["stats"]["aircraft"] == 12


def test_replay_load_seek_prefills_window(tmp_path, client, real_amritsar):
    for i in range(6):
        append_line(tmp_path, make_line(POLL_TS + 10 * i, "adsb.fi", {"name": "amritsar"}, 200, 300, None, real_amritsar), "r000001")
    rt = client.app.state.rt
    rep = Replayer(rt, sorted(tmp_path.glob("rec_*.jsonl.gz")), speed=5)
    rep.load()
    assert rep.frames and rep.t_end - rep.t_start == 50
    rep.seek(POLL_TS + 30)
    assert rt.clock.now() == POLL_TS + 30 and len(rt.window) > 0
    assert rep.status()["progress"] == 0.6


def test_short_recording_starts_inside_and_seek_keeps_attacks(tmp_path, client, real_amritsar):
    for i in range(60):  # 10 minutes of data
        append_line(tmp_path, make_line(POLL_TS + 10 * i, "adsb.fi", {"name": "amritsar"}, 200, 300, None, real_amritsar), "r000002")
    rt = client.app.state.rt
    rep = Replayer(rt, sorted(tmp_path.glob("rec_*.jsonl.gz")))
    rep.load()
    start = rep.default_start()
    assert rep.t_start < start < rep.t_end - 300  # leaves most of a short recording to play
    rep.seek(start)
    attack = rt.injector.add_jamming((31.6, 74.9), 100, 1.0, 0.0, None, now=rt.clock.now())
    rep.seek(rep.t_start + 60)
    assert attack.id in rt.injector.attacks and attack.live(rt.clock.now())


def test_unknown_ids_are_404_not_500(client):
    assert client.patch("/api/attacks/jam-999", json={"strength": 0.5}).status_code == 404
    assert client.delete("/api/attacks/jam-999").status_code == 404
    assert client.get("/api/incidents/inc-1").status_code == 404
    assert client.get("/api/incidents/inc-1/report.pdf").status_code == 404
    assert client.post("/api/replay/seek", json={"ts": 0}).status_code == 409  # not in replay mode
    assert client.post("/api/region", json={"name": "atlantis"}).status_code == 422


def test_replay_starts_in_longest_stretch_not_in_a_gap(tmp_path, client, real_amritsar):
    append_line(tmp_path, make_line(POLL_TS, "adsb.fi", {"name": "amritsar"}, 200, 300, None, real_amritsar), "r000001")  # a --once test
    later = POLL_TS + 750  # recorder started 12.5 min later (the real 11 Oct situation)
    for i in range(30):
        append_line(tmp_path, make_line(later + 10 * i, "adsb.fi", {"name": "amritsar"}, 200, 300, None, real_amritsar), "r000002")
    rep = Replayer(client.app.state.rt, sorted(tmp_path.glob("rec_*.jsonl.gz")))
    rep.load()
    assert len(rep.segments()) == 2
    assert later <= rep.default_start() <= later + 290
