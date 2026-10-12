"""API smoke tests. GAW_AUTOSTART=false (conftest), so no network and no background tasks."""
import asyncio
import inspect
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, reset_detection, settings
from app.ingest.poller import LivePoller
from app.ingest.recording import append_line, make_line
from app.ingest.replay import Replayer
from app.main import app
from app.runtime import Runtime
from conftest import POLL_TS, make, pdf_text


@pytest.fixture
def client():
    with TestClient(app) as c:
        rt = c.app.state.rt
        rt.reset_experiment()
        rt.clock.use_replay(POLL_TS)
        reset_detection()  # a test that moved a slider must not leak into the next one
        yield c


def seed(client, n=12):
    rt = client.app.state.rt
    rt.ingest_records([make(f"{i:06x}", 31.6 + i * 0.01, 74.9, ts=POLL_TS - 5) for i in range(n)], now=POLL_TS)
    return rt


def replay_of(tmp_path, rt, snapshot, n=30, run="r000009"):
    """A Replayer over n polls (10 s apart) of one real API answer."""
    for i in range(n):
        append_line(tmp_path, make_line(POLL_TS + 10 * i, "adsb.fi", {"name": "amritsar"}, 200, 300, None, snapshot), run)
    rep = Replayer(rt, sorted(tmp_path.glob("rec_*.jsonl.gz")))
    rep.load()
    return rep


def advance(rep, seconds):
    """Play `seconds` of recording like one iteration of Replayer.run, but let errors raise."""
    rep._advance(seconds / rep.speed)


JSON = {"content-type": "application/json"}


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


def test_detection_config_rejects_values_that_would_crash_the_tick(client):
    assert client.patch("/api/config/detection", json={"warn_step_s": 0}).status_code == 422  # range() step 0
    assert client.patch("/api/config/detection", json={"jammer_radius_pct": 150}).status_code == 422  # IndexError
    for bad in ({"warn_horizon_s": 10**7}, {"incident_close_s": -1}, {"jump_speed_kt": -5}, {"alt_min_peers": 0},
                {"cluster_min_aircraft": 0}, {"warn_step_s": 600, "warn_horizon_s": 300}):
        assert client.patch("/api/config/detection", json=bad).status_code == 422, bad
    assert client.patch("/api/config/detection", content='{"jam_lower_bound": NaN}', headers=JSON).status_code == 422
    cfg = client.get("/api/config/detection").json()
    assert (cfg["warn_step_s"], cfg["jammer_radius_pct"]) == (30, 80.0)  # nothing was applied


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


def test_patch_null_is_ignored_and_replay_keeps_running(tmp_path, client, real_amritsar):
    rt = client.app.state.rt
    rep = replay_of(tmp_path, rt, real_amritsar)
    rep.seek(rep.t_start + 60)
    aid = client.post("/api/attacks", json={"kind": "jamming", "center": [31.6, 74.9], "radius_km": 100, "strength": 1.0}).json()["attack_id"]
    r = client.patch(f"/api/attacks/{aid}", json={"radius_km": None, "strength": None, "center": None, "position_loss": None})
    assert r.status_code == 200
    a = r.json()
    assert (a["radius_km"], a["strength"], a["center"], a["position_loss"]) == (100, 1.0, [31.6, 74.9], 0.3)
    t0 = rt.clock.now()
    advance(rep, 60)  # used to raise TypeError inside the replay loop
    assert rt.clock.now() == t0 + 60
    assert any(rec.injected == aid for rec in rt.window.all())
    rt.compute_tick()


def test_patch_duration_null_still_means_until_switched_off(client):
    seed(client)
    aid = client.post("/api/attacks", json={"kind": "jamming", "center": [31.6, 74.9], "duration_s": 600}).json()["attack_id"]
    assert client.patch(f"/api/attacks/{aid}", json={"duration_s": None}).json()["duration_s"] is None


def test_attack_bodies_reject_nan_and_inf(client):
    seed(client)
    aid = client.post("/api/attacks", json={"kind": "jamming", "center": [31.6, 74.9]}).json()["attack_id"]
    assert client.patch(f"/api/attacks/{aid}", content='{"strength": NaN}', headers=JSON).status_code == 422
    assert client.patch(f"/api/attacks/{aid}", content='{"radius_km": Infinity}', headers=JSON).status_code == 422
    assert client.post("/api/attacks", content='{"kind": "jamming", "center": [NaN, 74.9]}', headers=JSON).status_code == 422


def test_replay_survives_an_error_and_reports_it(tmp_path, client, real_amritsar, monkeypatch):
    rt = client.app.state.rt
    rep = replay_of(tmp_path, rt, real_amritsar)
    rt.replayer = rep  # what Runtime.start does, so /api/replay and /api/health see it
    rep.seek(rep.t_start + 60)
    real_apply, calls = rt.injector.apply, []

    def apply_failing_once(records, now):
        calls.append(now)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return real_apply(records, now)

    monkeypatch.setattr(rt.injector, "apply", apply_failing_once)
    t0, idx0 = rt.clock.now(), rep.idx
    assert rep.step(30) is False  # the error is caught...
    assert rt.clock.now() == t0 + 30  # ...and replay time still moved on
    assert rep.step(30) is True and rt.clock.now() == t0 + 60 and rep.idx > idx0 + 3
    status = client.get("/api/replay").json()
    assert "boom" in status["last_error"] and status["last_error_ts"] == t0 + 30
    assert "boom" in client.get("/api/health").json()["last_error"]


def test_live_poller_survives_an_error_and_reports_it(client, real_amritsar, monkeypatch):
    rt = client.app.state.rt
    poller = LivePoller(rt)

    class Answer:
        status_code = 200

        def json(self):
            return real_amritsar

    class FakeHttp:
        async def get(self, url):
            return Answer()

    real_on_answer, calls = rt.on_live_answer, []

    def on_answer_failing_once(*args):
        calls.append(args)
        if len(calls) == 1:
            raise RuntimeError("bad answer")
        return real_on_answer(*args)

    monkeypatch.setattr(rt, "on_live_answer", on_answer_failing_once)
    assert asyncio.run(poller.poll_guarded(FakeHttp(), rt.points[0], "adsb.fi")) is False
    assert "bad answer" in poller.last_error
    assert asyncio.run(poller.poll_guarded(FakeHttp(), rt.points[0], "adsb.fi")) is True
    assert len(rt.window) > 0


def test_simulated_spoof_turns_cell_purple_and_its_warning_is_injected(client):
    """Audit C1 + S13: the spoof overlay in compute_tick, end to end through the API."""
    rt = client.app.state.rt
    rt.ingest_records([make(f"{i:06x}", 31.6 + i * 0.01, 77.2, ts=POLL_TS - 5) for i in range(8)], now=POLL_TS)
    assert client.post("/api/attacks", json={"kind": "spoof", "hex": "000003", "offset_km": 30, "bearing_deg": 90}).status_code == 200
    rt.clock.set(POLL_TS + 10)
    later = [make(f"{i:06x}", 31.63 + i * 0.01, 77.2, ts=POLL_TS + 10, track=0.0) for i in range(8)]
    inbound = make("inbnd2", 31.4, 76.2, ts=POLL_TS + 10, track=90.0, gs=450.0)  # flying east toward the fake position
    rt.ingest_records(later + [inbound], now=POLL_TS + 10)
    t = rt.compute_tick()
    [purple] = [f["properties"] for f in t["cells"]["features"] if f["properties"]["state"] == "spoofing"]
    assert purple["injected"] is True and purple["mixed"] is False
    assert any(f["hex"] == "000003" and "impossible_jump" in f["reasons"] for f in rt.flag_log)
    [ew] = [a for a in t["alerts"] if a["kind"] == "early_warning"]
    assert ew["hex"] == "inbnd2" and ew["cell_state"] == "spoofing" and ew["injected"] is True and ew["mixed"] is False
    assert [(i["kind"], i["injected"], i["mixed"]) for i in t["incidents_summary"]] == [("spoofing", True, False)]


def test_simulated_jammer_with_one_real_bad_aircraft_is_injected_and_mixed(client):
    rt = client.app.state.rt
    c = (28.47, 77.20)
    inside = [make(f"{i:06x}", c[0] + (i - 10) * 0.01, c[1]) for i in range(20)]
    real_bad = make("realbd", c[0] + 0.45, c[1] - 0.1, nac_p=6)  # same res-3 cell, ~51 km out: not jammed by us
    inbound = make("inbnd4", c[0], c[1] - 1.3, track=90.0, gs=450.0)
    client.post("/api/attacks", json={"kind": "jamming", "center": list(c), "radius_km": 30, "strength": 1.0, "position_loss": 0.0})
    rt.ingest_records(inside + [real_bad, inbound], now=POLL_TS)
    t = rt.compute_tick()
    [cell] = [f["properties"] for f in t["cells"]["features"] if f["properties"]["state"] == "jammed"]
    assert (cell["n_bad"], cell["n_injected"], cell["injected"], cell["mixed"]) == (21, 20, True, True)
    [ew] = [a for a in t["alerts"] if a["kind"] == "early_warning"]
    assert ew["injected"] is True and ew["mixed"] is True
    [inc] = t["incidents_summary"]
    assert inc["injected"] is True and inc["mixed"] is True
    pdf = client.get(f"/api/incidents/{inc['id']}/report.pdf").content
    assert b"INJECTED" in pdf  # document subject
    text = pdf_text(pdf)
    assert "INJECTED TEST ATTACK" in text and "Also contains real" in text  # banner + mixed line on the page


def test_state_changing_routes_run_on_the_event_loop_thread(client, monkeypatch):
    """Audit S3: sync routes run in a threadpool and raced the replayer and the tick."""
    from fastapi.routing import APIRoute

    for route in client.app.routes:
        if isinstance(route, APIRoute) and (route.methods & {"POST", "PATCH", "DELETE"} or route.path in ("/api/aircraft", "/api/cells")):
            assert inspect.iscoroutinefunction(route.endpoint), f"{route.methods} {route.path} must be async def"

    rt = client.app.state.rt
    loop_thread = client.portal.call(threading.get_ident)
    seen, real = [], rt.persist_ground_truth
    monkeypatch.setattr(rt, "persist_ground_truth", lambda: (seen.append(threading.get_ident()), real())[1])
    seed(client)
    aid = client.post("/api/attacks", json={"kind": "jamming", "center": [31.6, 74.9]}).json()["attack_id"]
    client.patch(f"/api/attacks/{aid}", json={"strength": 0.5})
    client.delete(f"/api/attacks/{aid}")
    client.delete("/api/attacks")
    assert len(seen) == 4 and set(seen) == {loop_thread}


def test_replay_files_setting_pins_the_recording(tmp_path):
    for run in ("r000001", "r000002"):
        append_line(tmp_path, make_line(POLL_TS, "adsb.fi", {"name": "amritsar"}, 200, 300, None, {"ac": []}), run)
    pinned = "rec_20261011_06_r000001.jsonl.gz"
    rt = Runtime(Settings(recordings_dir=tmp_path, replay_files=f" {pinned} ", db_path=tmp_path / "t.db"))
    assert rt.replay_files(None) == [tmp_path / pinned]  # instead of the newest hours (both files)
    assert rt.replay_files(["rec_20261011_06_r000002.jsonl.gz"]) == [tmp_path / "rec_20261011_06_r000002.jsonl.gz"]
    with pytest.raises(FileNotFoundError, match="GAW_REPLAY_FILES"):
        Runtime(Settings(recordings_dir=tmp_path, replay_files="nope.jsonl.gz")).replay_files(None)


def test_startup_fails_clearly_when_replay_files_are_unknown(monkeypatch):
    monkeypatch.setattr(settings, "autostart", True)
    monkeypatch.setattr(settings, "mode", "replay")
    monkeypatch.setattr(settings, "replay_files", "nope.jsonl.gz")
    with pytest.raises(RuntimeError, match="GAW_REPLAY_FILES lists recordings that do not exist"):
        with TestClient(app):
            pass


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
