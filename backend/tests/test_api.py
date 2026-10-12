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
from app.api.ws import WSManager
from app.main import app, manager
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
DELHI = [28.47, 77.20]  # the busiest res-3 cell in the real_amritsar snapshot (15 aircraft)


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


def test_sentinel_rejects_nan_and_latest_keeps_working(client):
    """Audit N4: a NaN was stored and GET /api/sentinel/latest then answered 500."""
    r = client.post("/api/sentinel", content='{"id": "s-nan", "fix": true, "avg_snr": NaN}', headers=JSON)
    assert r.status_code == 422
    assert client.post("/api/sentinel", content='{"id": "s-inf", "fix": true, "hdop": Infinity}', headers=JSON).status_code == 422
    assert client.get("/api/sentinel/latest").status_code == 200


def test_websocket_sends_latest_tick_on_connect(client):
    seed(client)
    client.app.state.rt.compute_tick()
    with client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
    assert msg["type"] == "tick" and msg["stats"]["aircraft"] == 12


def test_websocket_survives_a_binary_frame(client):
    """Audit N5: receive_text() raised KeyError on a binary frame and dropped the socket."""
    seed(client)
    client.app.state.rt.compute_tick()
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "tick"
        ws.send_bytes(b"\x00\x01binary")
        client.portal.call(manager.broadcast, {"type": "tick", "probe": 1})
        assert ws.receive_json()["probe"] == 1  # still connected and still served


def test_a_stalled_client_is_dropped_without_delaying_the_others():
    class Stalled:
        async def send_text(self, text):
            await asyncio.sleep(3600)

        async def close(self, code=1000):
            await asyncio.sleep(3600)

    class Healthy:
        def __init__(self):
            self.got = []

        async def send_text(self, text):
            self.got.append(text)

    async def one_tick():
        m = WSManager(send_timeout_s=0.05)
        stalled, healthy = Stalled(), Healthy()
        m.clients |= {stalled, healthy}
        t0 = time.monotonic()
        await m.broadcast({"type": "tick"})
        return m, stalled, healthy, time.monotonic() - t0

    m, stalled, healthy, took = asyncio.run(one_tick())
    assert healthy.got and stalled not in m.clients and healthy in m.clients and took < 1.0


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


def fake_http(snapshot):
    """An httpx-like client whose every GET answers 200 with `snapshot`."""

    class Answer:
        status_code = 200

        def json(self):
            return snapshot

    class FakeHttp:
        async def get(self, url):
            return Answer()

    return FakeHttp


def test_live_poller_survives_an_error_and_reports_it(client, real_amritsar, monkeypatch):
    rt = client.app.state.rt
    poller = LivePoller(rt)
    FakeHttp = fake_http(real_amritsar)
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


def outcomes(client):
    return [(e["attack_id"], e["outcome"], e["max_aircraft_inside"]) for e in client.get("/api/evaluation").json()["per_event"]]


def test_missed_jammer_stays_missed_after_delete(client):
    """Audit S5: deleting an attack used to turn 'missed' into 'undetectable'."""
    rt = seed(client, 20)
    body = {"kind": "jamming", "center": [31.7, 74.9], "radius_km": 150, "strength": 0.0}  # covers 20 aircraft, affects none
    first = client.post("/api/attacks", json=body).json()["attack_id"]
    second = client.post("/api/attacks", json=body).json()["attack_id"]
    rt.compute_tick()
    rt.clock.set(POLL_TS + 400)  # past eval_detect_within_s (300 s)
    assert outcomes(client) == [(first, "missed", 20), (second, "missed", 20)]
    client.delete(f"/api/attacks/{first}")
    client.delete("/api/attacks")
    assert outcomes(client) == [(first, "missed", 20), (second, "missed", 20)]


def test_one_jammer_over_several_cells_is_one_detection_and_no_unexplained_alarms(client):
    """Audit S6: the extra cells of one big jammer used to count as unexplained alarms."""
    rt = client.app.state.rt
    spread = [make(f"{i:06x}", 31.0 + (i % 40) * 0.03, 74.0 + (i // 40) * 0.6) for i in range(160)]
    client.post("/api/attacks", json={"kind": "jamming", "center": [31.6, 74.9], "radius_km": 150, "strength": 1.0})
    rt.ingest_records(spread, now=POLL_TS)
    t = rt.compute_tick()
    assert sum(f["properties"]["state"] == "jammed" for f in t["cells"]["features"]) >= 3
    ev = client.get("/api/evaluation").json()
    assert (ev["events"], ev["detected"], ev["unexplained_alarms"]) == (1, 1, 0)


def test_incidents_and_their_pdf_survive_a_replay_seek(tmp_path, client, real_amritsar):
    """Audit S7: a seek or loop used to delete every incident (PDF -> 404)."""
    rt = client.app.state.rt
    rep = replay_of(tmp_path, rt, real_amritsar)
    rep.seek(rep.t_start + 60)
    client.post("/api/attacks", json={"kind": "jamming", "center": DELHI, "radius_km": 60, "strength": 1.0})
    advance(rep, 60)
    rt.compute_tick()
    [inc] = client.get("/api/incidents").json()
    assert inc["open"]
    jumped_at = rt.clock.now()
    rep.seek(rep.t_start + 30)  # scrub backwards
    [after] = client.get("/api/incidents").json()
    assert after["id"] == inc["id"] and not after["open"] and after["closed_ts"] == jumped_at
    r = client.get(f"/api/incidents/{inc['id']}/report.pdf")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"


def test_after_a_loop_a_missed_event_stays_missed(tmp_path, client, real_amritsar):
    """Audit S8: the clock jumping back used to flip 'missed' back to 'pending'."""
    rt = client.app.state.rt
    rep = replay_of(tmp_path, rt, real_amritsar, n=60)
    rep.seek(rep.t_start + 60)
    client.post("/api/attacks", json={"kind": "jamming", "center": DELHI, "radius_km": 60, "strength": 0.0})
    advance(rep, 360)  # past the 300 s detection allowance, nothing detected
    rt.compute_tick()
    assert [e[1] for e in outcomes(client)] == ["missed"]
    rep.seek(rep.t_start + 60)  # what the replay loop does
    assert [e[1] for e in outcomes(client)] == ["missed", "pending"]  # old event done; reopened event is new


def test_after_a_loop_old_detections_do_not_match_the_reopened_event(tmp_path, client, real_amritsar):
    rt = client.app.state.rt
    rep = replay_of(tmp_path, rt, real_amritsar, n=60)
    rep.seek(rep.t_start + 100)
    client.post("/api/attacks", json={"kind": "jamming", "center": DELHI, "radius_km": 60, "strength": 1.0})
    advance(rep, 60)
    rt.compute_tick()
    assert [e[1] for e in outcomes(client)] == ["detected"]
    rep.seek(rep.t_start + 60)  # 100 s back: the old detection's time falls inside the reopened event's window
    assert [e[1] for e in outcomes(client)] == ["detected", "pending"]  # used to be detected by the stale alarm
    advance(rep, 60)
    rt.compute_tick()  # the attack is still on: the cell goes red again in the new epoch
    assert [e[1] for e in outcomes(client)] == ["detected", "detected"]


def test_mode_switch_with_a_bad_file_keeps_the_current_mode_running(tmp_path, client, real_amritsar, monkeypatch):
    """Audit S9: the old ingest was stopped before the file names were checked."""
    rt = client.app.state.rt
    monkeypatch.setattr(settings, "recordings_dir", tmp_path)  # rt.settings is this object
    good = append_line(tmp_path, make_line(POLL_TS, "adsb.fi", {"name": "amritsar"}, 200, 300, None, real_amritsar), "rs9test")
    assert client.post("/api/mode", json={"mode": "replay", "recordings": [good.name]}).status_code == 200
    running = rt.ingest_task
    r = client.post("/api/mode", json={"mode": "replay", "recordings": ["nope.jsonl.gz"]})
    assert r.status_code == 404 and "nope.jsonl.gz" in r.json()["detail"]
    assert rt.mode == "replay" and rt.ingest_task is running and not running.done()
    assert [p.name for p in rt.replayer.files] == [good.name]


class ConnSpy:
    """Records every use of the SQLite connection."""

    def __init__(self, conn):
        self.conn, self.used = conn, []

    def __getattr__(self, name):
        self.used.append(name)
        return getattr(self.conn, name)

    def __enter__(self):
        self.used.append("begin")
        return self.conn.__enter__()

    def __exit__(self, *exc):
        return self.conn.__exit__(*exc)


def test_sqlite_writes_are_queued_and_flushed_outside_the_tick(client):
    """Audit N1: the tick (and the routes) used to write to SQLite directly."""
    rt = seed(client, 20)
    spy = ConnSpy(rt.dbw.conn)
    rt.dbw.conn = spy
    client.post("/api/attacks", json={"kind": "jamming", "center": [31.7, 74.9], "radius_km": 150, "strength": 1.0})
    client.post("/api/sentinel", json={"id": "sentinel-n1", "fix": True, "avg_snr": 40.0})
    rt.ingest_records([make(f"{i:06x}", 31.6 + i * 0.01, 74.91, ts=POLL_TS) for i in range(20)], now=POLL_TS)
    rt.compute_tick()  # opens an incident
    queued = rt.dbw.pending()
    rt.compute_tick()  # upserts it again: replaces the queued write, does not add one
    assert spy.used == [] and queued == rt.dbw.pending() == 3  # ground truth, sentinel packet, incident
    assert rt.dbw.flush() == 3 and spy.used and rt.dbw.pending() == 0
    [inc] = client.get("/api/incidents").json()
    assert rt.db.execute("SELECT kind FROM incidents WHERE id = ?", (inc["id"],)).fetchone() == ("jamming",)
    assert rt.db.execute("SELECT COUNT(*) FROM sentinel WHERE id = 'sentinel-n1'").fetchone() == (1,)


def test_attack_and_preview_ranges(client):
    """Audit N2."""
    seed(client)
    for center in ([200, 500], [31.6, 190], [-91, 0]):
        assert client.post("/api/attacks", json={"kind": "jamming", "center": center}).status_code == 422, center
    aid = client.post("/api/attacks", json={"kind": "jamming", "center": [31.6, 74.9]}).json()["attack_id"]
    assert client.patch(f"/api/attacks/{aid}", json={"center": [95, 0]}).status_code == 422
    preview = "/api/attacks/preview"
    for bad in ({"radius_km": 5}, {"radius_km": 200}, {"radius_km": -5}, {"lat": 100}, {"lon": -181}):
        assert client.get(preview, params={"lat": 31.6, "lon": 74.9, "radius_km": 60, **bad}).status_code == 422, bad
    assert client.get(preview, params={"lat": 31.6, "lon": 74.9, "radius_km": 60}).status_code == 200


def test_patch_spoof_hex_random_picks_a_real_aircraft(client):
    aid = client.post("/api/attacks", json={"kind": "spoof", "hex": "abc123"}).json()["attack_id"]
    assert client.patch(f"/api/attacks/{aid}", json={"hex": "random"}).status_code == 409  # nothing airborne yet
    seed(client)
    r = client.patch(f"/api/attacks/{aid}", json={"hex": "random"})
    assert r.status_code == 200 and r.json()["hex"] in {f"{i:06x}" for i in range(12)}  # used to store "random"


def test_live_answers_are_stamped_with_the_runtime_clock(client, real_amritsar):
    """Audit N7: the poller used time.time() instead of the one clock."""
    rt = client.app.state.rt
    rt.clock.use_replay(POLL_TS + 123)  # stands in for "now"; live mode reads the wall clock through it
    assert asyncio.run(LivePoller(rt).poll_guarded(fake_http(real_amritsar)(), rt.points[0], "adsb.fi"))
    assert {r.poll_ts for r in rt.window.all()} == {POLL_TS + 123}


def test_unknown_ids_are_404_not_500(client):
    assert client.patch("/api/attacks/jam-999", json={"strength": 0.5}).status_code == 404
    assert client.delete("/api/attacks/jam-999").status_code == 404
    assert client.get("/api/incidents/inc-1").status_code == 404
    assert client.get("/api/incidents/inc-1/report.pdf").status_code == 404
    assert client.post("/api/replay/seek", json={"ts": 0}).status_code == 409  # not in replay mode
    assert client.post("/api/region", json={"name": "atlantis"}).status_code == 422
    assert client.post("/api/region", json={"points": "31,74,inf"}).status_code == 422  # was 500 (OverflowError)


def test_replay_starts_in_longest_stretch_not_in_a_gap(tmp_path, client, real_amritsar):
    append_line(tmp_path, make_line(POLL_TS, "adsb.fi", {"name": "amritsar"}, 200, 300, None, real_amritsar), "r000001")  # a --once test
    later = POLL_TS + 750  # recorder started 12.5 min later (the real 11 Oct situation)
    for i in range(30):
        append_line(tmp_path, make_line(later + 10 * i, "adsb.fi", {"name": "amritsar"}, 200, 300, None, real_amritsar), "r000002")
    rep = Replayer(client.app.state.rt, sorted(tmp_path.glob("rec_*.jsonl.gz")))
    rep.load()
    assert len(rep.segments()) == 2
    assert later <= rep.default_start() <= later + 290
