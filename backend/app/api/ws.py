"""WebSocket fan-out: every detector tick goes to every connected browser."""
from __future__ import annotations

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
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def send(self, ws: WebSocket, payload: dict) -> None:
        await ws.send_text(json.dumps(jsonable(payload), separators=(",", ":")))

    async def broadcast(self, payload: dict) -> None:
        if not self.clients:
            return
        text = json.dumps(jsonable(payload), separators=(",", ":"))
        for ws in list(self.clients):
            try:
                await ws.send_text(text)
            except Exception:
                self.disconnect(ws)
