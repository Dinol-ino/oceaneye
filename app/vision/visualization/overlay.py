"""Draw tracking results on a frame: boxes, track ids, trajectories, HUD (roadmap Stage 4).
Visualisation only - it never feeds decisions.

These functions run on every analysed frame, so they avoid whole-frame work where a region will do:
the translucent danger zone is blended inside the polygon's bounding box rather than over a copy of
the entire image.
"""
from __future__ import annotations

import colorsys
import zlib
from functools import lru_cache

import cv2
import numpy as np

from app.vision.config import OverlayConfig
from app.vision.tracking.base import Track

FONT = cv2.FONT_HERSHEY_SIMPLEX
ZONE_FILL = (0, 0, 200)
ZONE_EDGE = (0, 0, 255)
ZONE_ALPHA = 0.18


@lru_cache(maxsize=512)
def track_color(track_id: str) -> tuple[int, int, int]:
    """Stable BGR colour per track id (cached: called for every box on every frame)."""
    hue = (zlib.crc32(track_id.encode()) % 360) / 360.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.85, 1.0)
    return int(b * 255), int(g * 255), int(r * 255)


def _anchor(track_point_box, anchor: str) -> tuple[int, int]:
    b = track_point_box
    cx = (b.x_min + b.x_max) / 2
    cy = b.y_max if anchor == "bottom" else (b.y_min + b.y_max) / 2
    return int(cx), int(cy)


def _label(img, text: str, org: tuple[int, int], color) -> None:
    (w, h), base = cv2.getTextSize(text, FONT, 0.5, 1)
    x, y = org
    y = max(y, h + 4)
    cv2.rectangle(img, (x, y - h - 4), (x + w + 4, y + base - 2), color, -1)
    cv2.putText(img, text, (x + 2, y - 2), FONT, 0.5, (0, 0, 0), 1, cv2.LINE_AA)


def draw_tracks(image: np.ndarray, tracks: list[Track], cfg: OverlayConfig | None = None, *,
                frame_index: int | None = None, timestamp_s: float | None = None,
                camera_id: str | None = None, fps: float | None = None) -> np.ndarray:
    """Return an annotated COPY of ``image`` (BGR uint8)."""
    cfg = cfg or OverlayConfig()
    out = image.copy()
    h, w = out.shape[:2]
    for tr in tracks:
        color = track_color(tr.track_id)
        pts = [_anchor(d.bbox, cfg.trail_anchor) for d in tr.history[-cfg.trail_length:]]
        n = len(pts)
        if n > 1:
            # One polylines call per fade band instead of one line call per segment.
            bands = min(4, n - 1)
            for band in range(bands):
                lo = 1 + band * (n - 1) // bands
                hi = 1 + (band + 1) * (n - 1) // bands
                if hi <= lo:
                    continue
                k = 0.35 + 0.65 * (band + 1) / bands
                seg_color = tuple(int(c * k) for c in color)
                cv2.polylines(out, [np.array(pts[lo - 1:hi + 1], dtype=np.int32)], False,
                              seg_color, max(1, cfg.thickness - 1), cv2.LINE_AA)
        b = tr.current.bbox
        p1 = (int(max(0, b.x_min)), int(max(0, b.y_min)))
        p2 = (int(min(w - 1, b.x_max)), int(min(h - 1, b.y_max)))
        cv2.rectangle(out, p1, p2, color, cfg.thickness)
        short_id = tr.track_id.rsplit("-", 1)[-1]  # "cam_01-T7" -> "T7"
        _label(out, f"{short_id} {tr.current.confidence:.2f}", p1, color)
    if cfg.show_hud:
        parts = [camera_id or "", f"frame {frame_index}" if frame_index is not None else "",
                 f"t={timestamp_s:.1f}s" if timestamp_s is not None else "", f"people={len(tracks)}",
                 f"{fps:.1f} fps" if fps else ""]
        text = "  ".join(p for p in parts if p)
        (tw, _), _ = cv2.getTextSize(text, FONT, 0.5, 1)
        cv2.rectangle(out, (0, 0), (min(w, tw + 12), 24), (0, 0, 0), -1)
        cv2.putText(out, text, (6, 17), FONT, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return out


RISK_COLORS = {"low": (80, 200, 80), "medium": (0, 200, 255), "high": (0, 120, 255), "critical": (0, 0, 255)}


def draw_zone(image: np.ndarray, polygon: list | tuple | None, name: str | None = None) -> np.ndarray:
    """Draw a normalised (0..1) danger-zone polygon in place (translucent red).

    Blends only the polygon's bounding box, so the cost scales with the zone rather than the frame.
    """
    if not polygon or len(polygon) < 3:
        return image
    h, w = image.shape[:2]
    pts = np.array([[int(x * w), int(y * h)] for x, y in polygon], dtype=np.int32)
    x0, y0 = max(0, int(pts[:, 0].min())), max(0, int(pts[:, 1].min()))
    x1, y1 = min(w, int(pts[:, 0].max()) + 1), min(h, int(pts[:, 1].max()) + 1)
    if x1 <= x0 or y1 <= y0:
        return image
    roi = image[y0:y1, x0:x1]
    shifted = pts - (x0, y0)
    tint = np.empty_like(roi)
    tint[:] = ZONE_FILL
    mask = np.zeros(roi.shape[:2], dtype=np.uint8)
    cv2.fillPoly(mask, [shifted], 255)
    blended = cv2.addWeighted(tint, ZONE_ALPHA, roi, 1 - ZONE_ALPHA, 0)
    np.copyto(roi, blended, where=mask[:, :, None].astype(bool))
    cv2.polylines(image, [pts], True, ZONE_EDGE, 2, cv2.LINE_AA)
    if name:
        cv2.putText(image, name, (x0 + 4, y0 + 16), FONT, 0.5, ZONE_EDGE, 1, cv2.LINE_AA)
    return image


def draw_risk(image: np.ndarray, tracks: list[Track], risk: dict[str, tuple[str, float]]) -> np.ndarray:
    """Thick coloured frame + 'LEVEL score' label for tracks with medium or higher risk (in place)."""
    for tr in tracks:
        level, score = risk.get(tr.track_id, ("low", 0.0))
        if level == "low":
            continue
        color = RISK_COLORS.get(level, (0, 0, 255))
        b = tr.current.bbox
        p1, p2 = (int(b.x_min) - 3, int(b.y_min) - 3), (int(b.x_max) + 3, int(b.y_max) + 3)
        cv2.rectangle(image, p1, p2, color, 4)
        _label(image, f"{level.upper()} {score:.2f}", (p1[0], p2[1] + 18), color)
    return image
