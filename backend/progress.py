from __future__ import annotations

from collections import defaultdict

from fastapi import WebSocket


class ProgressManager:
    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)
        self._history: dict[int, list[str]] = defaultdict(list)

    async def connect(self, analysis_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[analysis_id].add(websocket)
        for message in self._history[analysis_id]:
            await websocket.send_json({"analysis_id": analysis_id, "message": message})

    def disconnect(self, analysis_id: int, websocket: WebSocket) -> None:
        self._connections[analysis_id].discard(websocket)
        if not self._connections[analysis_id]:
            self._connections.pop(analysis_id, None)

    async def publish(self, analysis_id: int, message: str) -> None:
        self._history[analysis_id].append(message)
        dead: list[WebSocket] = []
        for websocket in self._connections.get(analysis_id, set()):
            try:
                await websocket.send_json({"analysis_id": analysis_id, "message": message})
            except RuntimeError:
                dead.append(websocket)
        for websocket in dead:
            self.disconnect(analysis_id, websocket)

