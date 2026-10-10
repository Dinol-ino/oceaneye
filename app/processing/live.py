"""Latest annotated frame + stats per camera, pushed by camera workers (in-memory, single process).
FUTURE: Redis / a media server (MJPEG / WebRTC) when cameras and viewers scale."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class LiveState:
    camera_id: str
    jpeg: bytes | None = None
    frame_at: datetime | None = None
    stats: dict = field(default_factory=dict)
    worker_state: str = "stopped"  # starting | running | stopped | error
    worker_message: str | None = None


class LiveFrameStore:
    def __init__(self, online_after_seconds: float = 10.0) -> None:
        self._d: dict[str, LiveState] = {}
        self._online_after = online_after_seconds

    def state(self, camera_id: str) -> LiveState:
        return self._d.setdefault(camera_id, LiveState(camera_id))

    def put_frame(self, camera_id: str, jpeg: bytes, stats: dict, at: datetime) -> None:
        s = self.state(camera_id)
        s.jpeg, s.stats, s.frame_at, s.worker_state = jpeg, stats, at, "running"

    def set_worker_state(self, camera_id: str, state: str, message: str | None = None) -> None:
        s = self.state(camera_id)
        s.worker_state, s.worker_message = state, message

    def is_online(self, camera_id: str, now: datetime) -> bool:
        s = self._d.get(camera_id)
        return bool(s and s.frame_at and (now - s.frame_at).total_seconds() <= self._online_after)

    def all(self) -> list[LiveState]:
        return list(self._d.values())
