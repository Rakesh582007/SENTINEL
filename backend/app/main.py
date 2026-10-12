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

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.api.ws import WSManager, jsonable
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


async def db_flush_loop(rt: Runtime) -> None:
    """Write the queued SQLite rows from a worker thread, so the tick never waits on the disk."""
    while True:
        await asyncio.sleep(rt.settings.db_flush_s)
        if rt.dbw is not None:
            try:
                await asyncio.to_thread(rt.dbw.flush)
            except Exception:
                log.exception("SQLite flush failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    rt = Runtime(settings)
    rt.open_db()
    app.state.rt = rt
    tasks: list[asyncio.Task] = []
    if settings.autostart:
        try:
            await rt.start(settings.mode)
        except FileNotFoundError as e:
            log.error("startup failed: %s", e)
            rt.close_db()
            raise RuntimeError(f"startup failed: {e}") from None
        tasks.append(asyncio.create_task(tick_loop(rt), name="tick-loop"))
        tasks.append(asyncio.create_task(db_flush_loop(rt), name="db-flush"))
        log.info("started in %s mode, region %s, sources %s", rt.mode, rt.region_name, rt.sources)
    yield
    for task in tasks:
        task.cancel()
    await rt.stop_ingest()
    rt.close_db()  # writes whatever is still queued


app = FastAPI(title="GPS Attack Watch", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI's default 422 echoes the bad input back; a NaN input would then fail to serialise (500)."""
    return JSONResponse(status_code=422, content={"detail": jsonable(jsonable_encoder(exc.errors()))})


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        rt: Runtime = ws.app.state.rt
        if rt.last_tick:
            await manager.send(ws, rt.last_tick)  # the newcomer sees the map at once
        while True:
            # Clients need not send anything; this keeps the socket open. receive() (not
            # receive_text) so a binary frame is ignored instead of raising KeyError.
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(ws)
