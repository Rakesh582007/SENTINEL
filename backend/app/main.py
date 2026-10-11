"""FastAPI entry point.

    cd backend
    uvicorn app.main:app --reload --port 8000

Startup: open SQLite, start ONE ingest task (replay by default, or live), and
start the tick loop that runs the detectors every settings.tick_s seconds and
pushes the result to every browser on /ws.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.ws import WSManager
from app.config import settings
from app.runtime import Runtime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("gaw")

manager = WSManager()


async def tick_loop(rt: Runtime) -> None:
    while True:
        try:
            payload = rt.compute_tick()
            await manager.broadcast(payload)
        except Exception:
            log.exception("tick failed")  # keep ticking; one bad tick must not kill the demo
        await asyncio.sleep(rt.settings.tick_s)


@asynccontextmanager
async def lifespan(app: FastAPI):
    rt = Runtime(settings)
    rt.open_db()
    app.state.rt = rt
    tick_task = None
    if settings.autostart:
        await rt.start(settings.mode)
        tick_task = asyncio.create_task(tick_loop(rt), name="tick-loop")
        log.info("started in %s mode, region %s, sources %s", rt.mode, rt.region_name, rt.sources)
    yield
    if tick_task:
        tick_task.cancel()
    await rt.stop_ingest()


app = FastAPI(title="GPS Attack Watch", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        rt: Runtime = ws.app.state.rt
        if rt.last_tick:
            await manager.send(ws, rt.last_tick)  # the newcomer sees the map at once
        while True:
            await ws.receive_text()  # clients do not need to send anything; this keeps the socket open
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(ws)
