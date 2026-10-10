"""Run the full worker chain on a video WITHOUT the API (notebooks, quick experiments).

Same code path as the live worker (YOLO -> ByteTrack -> zone gate -> behaviour rules -> risk -> events
with evidence), but candidate events are collected in memory instead of being POSTed, and evidence is
written under the output folder.

Defaults are ``auto``: on a Colab GPU that picks a larger model and input size, on a laptop CPU a small
one. Pass explicit values to pin them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.evidence.local import LocalEvidenceStorage
from app.worker.api_client import ApiError
from app.worker.session import MonitoringSession, SessionConfig


@dataclass
class OfflineClient:
    """Stands in for the API: collects events, and has no weather to offer."""

    events: list[dict] = field(default_factory=list)

    def get(self, path: str, **params):
        raise ApiError("offline: no API")  # the risk engine works without environmental context

    def post(self, path: str, payload, retries: int = 2):
        if path == "/events":
            self.events.append(payload)
        return None


def analyze_video(source: str, output_dir: str, *, zone_polygon: list | None = None,
                  zone_name: str = "Danger zone", model: str = "auto", imgsz: int = 0,
                  device: str = "auto", target_fps: float = 0.0, sensitivity: str = "medium",
                  max_frames: int | None = None, weights_dir: str = "models",
                  clip_max_width: int = 0, camera_name: str = "offline") -> dict:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    cfg = SessionConfig(mode="job", camera_id="cam_offline", camera_name=camera_name, lat=0.0, lon=0.0,
                        source=str(source), zone_polygon=zone_polygon,
                        zone_name=zone_name if zone_polygon else None,
                        model=model, imgsz=imgsz, device=device, target_fps=target_fps,
                        sensitivity=sensitivity, job_id="offline", output_dir=str(out),
                        weights_dir=weights_dir, clip_max_width=clip_max_width, max_frames=max_frames)
    client = OfflineClient()
    session = MonitoringSession(cfg, client, LocalEvidenceStorage(out / "evidence"))  # type: ignore[arg-type]
    summary = session.run()
    return {"summary": summary, "events": client.events, "overlay_video": str(out / "overlay.mp4"),
            "tracks_jsonl": str(out / "tracks.jsonl"), "evidence_dir": str(out / "evidence")}
