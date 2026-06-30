from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timezone
from time import time
from typing import Any, Callable

from fastapi import WebSocket


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


class ProgressManager:
    def __init__(self, ttl_seconds: int | None = None, now: Callable[[], float] | None = None) -> None:
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)
        self._history: dict[int, list[dict[str, Any]]] = defaultdict(list)
        self.ttl_seconds = ttl_seconds if ttl_seconds is not None else _env_int("PROGRESS_HISTORY_TTL_SECONDS", 3600)
        self._now = now or time

    async def connect(self, analysis_id: int, websocket: WebSocket) -> None:
        self.cleanup_expired()
        await websocket.accept()
        self._connections[analysis_id].add(websocket)
        for event in self._history.get(analysis_id, []):
            await websocket.send_json(_public_event(event))

    def disconnect(self, analysis_id: int, websocket: WebSocket) -> None:
        self._connections[analysis_id].discard(websocket)
        if not self._connections[analysis_id]:
            self._connections.pop(analysis_id, None)

    async def publish(
        self,
        analysis_id: int,
        message: str,
        *,
        event: str = "progress",
        status: str | None = None,
        terminal: bool = False,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.cleanup_expired()
        payload: dict[str, Any] = {
            "analysis_id": analysis_id,
            "event": event,
            "message": message,
            "timestamp": datetime.fromtimestamp(self._now(), timezone.utc).isoformat(),
            "created_at_epoch": self._now(),
        }
        if status:
            payload["status"] = status
        if terminal:
            payload["terminal"] = True
        if details:
            payload["details"] = details

        self._history[analysis_id].append(payload)
        dead: list[WebSocket] = []
        for websocket in list(self._connections.get(analysis_id, set())):
            try:
                await websocket.send_json(_public_event(payload))
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            self.disconnect(analysis_id, websocket)
        return _public_event(payload)

    def history(self, analysis_id: int) -> list[dict[str, Any]]:
        self.cleanup_expired()
        return [_public_event(event) for event in self._history.get(analysis_id, [])]

    def cleanup_analysis(self, analysis_id: int) -> None:
        self._history.pop(analysis_id, None)
        self._connections.pop(analysis_id, None)

    def cleanup_expired(self) -> int:
        if self.ttl_seconds < 0:
            return 0
        cutoff = self._now() - self.ttl_seconds
        removed = 0
        for analysis_id, events in list(self._history.items()):
            if not events or float(events[-1].get("created_at_epoch", 0)) < cutoff:
                self._history.pop(analysis_id, None)
                removed += 1
        return removed


def _public_event(event: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in event.items() if key != "created_at_epoch"}
