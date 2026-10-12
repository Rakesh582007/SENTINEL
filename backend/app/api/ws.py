"""WebSocket fan-out: every detector tick goes to every connected browser."""
from __future__ import annotations

import asyncio
import json
import math

from fastapi import WebSocket


def jsonable(obj):
    """Replace NaN/inf with None: the browser's JSON.parse rejects them."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    return obj


class WSManager:
    """Sends go to all clients at once, each with a timeout: one stalled browser (a laptop
    asleep, a phone that lost Wi-Fi) is dropped instead of delaying the tick for everyone."""

    def __init__(self, send_timeout_s: float = 2.0) -> None:
        self.clients: set[WebSocket] = set()
        self.send_timeout_s = send_timeout_s
        self._closing: set[asyncio.Task] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def send(self, ws: WebSocket, payload: dict) -> None:
        await asyncio.wait_for(ws.send_text(json.dumps(jsonable(payload), separators=(",", ":"))), self.send_timeout_s)

    async def broadcast(self, payload: dict) -> None:
        if not self.clients:
            return
        text = json.dumps(jsonable(payload), separators=(",", ":"))
        await asyncio.gather(*(self._send_or_drop(ws, text) for ws in list(self.clients)))

    async def _send_or_drop(self, ws: WebSocket, text: str) -> None:
        try:
            await asyncio.wait_for(ws.send_text(text), self.send_timeout_s)
        except Exception:  # timed out (stalled) or already closed
            self.disconnect(ws)
            task = asyncio.create_task(self._close_quietly(ws))
            self._closing.add(task)
            task.add_done_callback(self._closing.discard)

    async def _close_quietly(self, ws: WebSocket) -> None:
        try:
            await asyncio.wait_for(ws.close(code=1011), self.send_timeout_s)
        except Exception:
            pass
