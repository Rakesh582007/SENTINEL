"""REST API (HANDOVER §8 and §7.1). The WebSocket lives in main.py.

Every route that changes runtime state (or may run compute_tick) is `async def`:
FastAPI runs those on the event-loop thread, the same thread as the replayer and the
tick, so they cannot interleave with them. Plain `def` routes run in a threadpool;
keep them read-only.
"""
from __future__ import annotations

import calendar
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from pydantic import ValidationError

from app.config import get_detection, reset_detection, update_detection
from app.detect.evaluate import evaluate
from app.ingest.recording import list_recordings
from app.ingest.replay import stamp_of
from app.models import AttackIn, AttackPatch, ModeIn, RegionIn, SeekIn, SentinelIn, SpeedIn
from app.regions import REGIONS
from app.report.pdf import incident_pdf
from app.runtime import Runtime

router = APIRouter(prefix="/api")


def rt_of(request: Request) -> Runtime:
    return request.app.state.rt


# ---------------------------------------------------------------- status & map
@router.get("/health")
def health(request: Request):
    return rt_of(request).health()


@router.get("/aircraft")
async def aircraft(request: Request):
    rt = rt_of(request)
    return (rt.last_tick or rt.compute_tick())["aircraft"]


@router.get("/cells")
async def cells(request: Request):
    rt = rt_of(request)
    return (rt.last_tick or rt.compute_tick())["cells"]


@router.get("/alerts")
def alerts(request: Request, active: bool = True):
    rt = rt_of(request)
    return (rt.last_tick or {}).get("alerts", [])


# ---------------------------------------------------------------- mode, region, replay
@router.post("/mode")
async def set_mode(body: ModeIn, request: Request):
    rt = rt_of(request)
    try:
        await rt.start(body.mode, files=body.recordings, speed=body.speed, start_ts=body.start_ts)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    return rt.health()


@router.get("/regions")
def regions(request: Request):
    rt = rt_of(request)
    return {
        "current": rt.region_name,
        "points": [p.as_dict() for p in rt.points],
        "presets": {name: [p.as_dict() for p in pts] for name, pts in REGIONS.items()},
    }


@router.post("/region")
async def set_region(body: RegionIn, request: Request):
    rt = rt_of(request)
    try:
        rt.set_region(body.name, body.points)
    except (KeyError, ValueError) as e:
        raise HTTPException(422, str(e)) from e
    return {"current": rt.region_name, "points": [p.as_dict() for p in rt.points],
            "note": "applies to live polling from the next sweep; replay plays whatever was recorded"}


@router.get("/recordings")
def recordings(request: Request):
    rt = rt_of(request)
    out = []
    for p in list_recordings(rt.settings.recordings_dir):
        stamp = stamp_of(p)
        hour_ist = None
        try:
            utc = calendar.timegm(time.strptime(stamp, "%Y%m%d_%H"))
            hour_ist = time.strftime("%d %b %H:%M IST", time.gmtime(utc + 5.5 * 3600))
        except ValueError:
            pass
        out.append({"name": p.name, "bytes": p.stat().st_size, "utc_hour": stamp, "starts": hour_ist})
    return out


def _replayer(request: Request):
    rt = rt_of(request)
    if rt.replayer is None:
        raise HTTPException(409, "not in replay mode")
    return rt.replayer


@router.get("/replay")
def replay_status(request: Request):
    return _replayer(request).status()


@router.post("/replay/seek")
async def replay_seek(body: SeekIn, request: Request):
    rep = _replayer(request)
    rep.seek(body.ts)
    return rep.status()


@router.post("/replay/speed")
async def replay_speed(body: SpeedIn, request: Request):
    rep = _replayer(request)
    rep.set_speed(body.speed)
    return rep.status()


@router.post("/replay/pause")
async def replay_pause(request: Request):
    rep = _replayer(request)
    rep.paused = True
    return rep.status()


@router.post("/replay/play")
async def replay_play(request: Request):
    rep = _replayer(request)
    rep.paused = False
    return rep.status()


# ---------------------------------------------------------------- detection sensitivity sliders
@router.get("/config/detection")
def get_detection_config():
    return get_detection().model_dump()


@router.patch("/config/detection")
async def patch_detection_config(changes: dict):
    try:
        return update_detection(changes).model_dump()
    except ValidationError as e:
        raise RequestValidationError(e.errors(include_url=False)) from e  # 422 via main.validation_error


@router.delete("/config/detection")
async def reset_detection_config():
    return reset_detection().model_dump()


# ---------------------------------------------------------------- attack simulator
@router.get("/attacks")
def list_attacks(request: Request):
    rt = rt_of(request)
    now = rt.clock.now()
    return [a.to_dict(now) for a in rt.injector.attacks.values()]


@router.get("/attacks/preview")
def preview_attack(lat: float, lon: float, radius_km: float, request: Request):
    """How many aircraft a jammer here would touch (show it while the judge drags)."""
    return rt_of(request).preview_circle(lat, lon, radius_km)


@router.post("/attacks")
async def create_attack(body: AttackIn, request: Request):
    try:
        return rt_of(request).create_attack(body.model_dump())
    except LookupError as e:
        raise HTTPException(409, str(e)) from e


@router.patch("/attacks/{attack_id}")
async def patch_attack(attack_id: str, body: AttackPatch, request: Request):
    rt = rt_of(request)
    if attack_id not in rt.injector.attacks:
        raise HTTPException(404, f"no attack {attack_id}")
    try:
        a = rt.update_attack(attack_id, body.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return a.to_dict(rt.clock.now())


@router.delete("/attacks/{attack_id}")
async def delete_attack(attack_id: str, request: Request):
    rt = rt_of(request)
    a = rt.injector.remove(attack_id, rt.clock.now())
    if a is None:
        raise HTTPException(404, f"no attack {attack_id}")
    restored = rt.window.restore_injected(attack_id)
    rt.persist_ground_truth()
    return {"deleted": attack_id, "records_restored": restored}


@router.delete("/attacks")
async def reset_attacks(request: Request):
    rt = rt_of(request)
    ids = rt.injector.reset(rt.clock.now())
    restored = sum(rt.window.restore_injected(i) for i in ids)
    rt.persist_ground_truth()
    return {"deleted": ids, "records_restored": restored}


# ---------------------------------------------------------------- incidents, report, evaluation (TODO modules)
@router.get("/incidents")
def incidents(request: Request):
    return rt_of(request).incidents.summary()


@router.get("/incidents/{incident_id}")
def incident(incident_id: str, request: Request):
    inc = rt_of(request).incidents.get(incident_id)
    if inc is None:
        raise HTTPException(404, f"no incident {incident_id}")
    return inc


@router.get("/incidents/{incident_id}/report.pdf")
def incident_report(incident_id: str, request: Request):
    inc = rt_of(request).incidents.get(incident_id)
    if inc is None:
        raise HTTPException(404, f"no incident {incident_id}")
    try:
        pdf = incident_pdf(inc)
    except NotImplementedError as e:
        raise HTTPException(501, str(e)) from e
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="incident-{incident_id}.pdf"'})


@router.get("/evaluation")
def evaluation(request: Request):
    rt = rt_of(request)
    coverage = {a.id: a.max_aircraft_inside for a in rt.injector.attacks.values()}
    try:
        return evaluate(rt.injector.ground_truth, rt.detections, get_detection(), rt.clock.now(), coverage, rt.flag_log)
    except NotImplementedError as e:
        raise HTTPException(501, {"error": str(e), "ground_truth": rt.injector.ground_truth, "detections": rt.detections}) from e


# ---------------------------------------------------------------- scripted scenarios
@router.get("/scenarios")
def scenarios(request: Request):
    rt = rt_of(request)
    return {"available": rt.list_scenarios(), "running": rt.scenario_status()}


@router.post("/scenarios/{scenario_id}/run")
async def run_scenario(scenario_id: str, request: Request):
    try:
        return rt_of(request).start_scenario(scenario_id)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e


# ---------------------------------------------------------------- ground sentinel
@router.post("/sentinel")
async def sentinel_post(body: SentinelIn, request: Request):
    entry = rt_of(request).add_sentinel(body.model_dump())
    return {"ok": True, "status": entry["status"], "recv_ts": entry["recv_ts"]}


@router.get("/sentinel/latest")
def sentinel_latest(request: Request):
    return rt_of(request).sentinel.latest(time.time())


@router.get("/sentinel/history")
def sentinel_history(request: Request, id: str = "sentinel-1", minutes: float = 10):
    return rt_of(request).sentinel.history(id, minutes, time.time())
