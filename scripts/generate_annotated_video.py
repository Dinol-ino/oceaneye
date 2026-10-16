"""Generate annotated video demonstrating dynamic drowning and distress detection.

Processes video frames with:
- Person detection (YOLOv8)
- Persistent multi-person tracking (ByteTrack)
- Dynamic physics-based behavior analysis:
    - Vertical posture in water (torso & aspect-ratio geometry)
    - Stationary struggle without headway (drift <= threshold)
    - Lateral arm flailing & thrashing (width variance >= threshold)
    - Repeated submersion & vertical bobbing (height collapses & reversals)
- Color indication:
    - Green: Normal swimming / Safe
    - Yellow: Caution / Struggling
    - Red: Active drowning distress
- Multi-person prioritization:
    - Prioritizes the victim in the acute/highest drowning state with double hazard box
- Prominent HUD banner flagging the event for review (without auto-dispatching).
"""
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import cv2
import numpy as np

from app.core.domain.frame import Frame
from app.environment.context import EnvironmentContext
from app.environment.zones.models import ZoneAssessment
from app.risk.distress.rules import RuleBasedBehaviorAnalyzer
from app.risk.engine.base import RiskInput
from app.risk.engine.rules import RuleBasedRiskEngine
from app.risk.scoring.config import RiskScoringConfig
from app.vision.config import DetectorConfig, TrackerConfig, OverlayConfig
from app.vision.detection.yolo import YoloDetector
from app.vision.tracking.bytetrack import ByteTrackTracker
from app.vision.visualization.overlay import draw_tracks


def main(input_path: str = r"c:\pbl_oceaneye\videos\4124047011-preview.mp4",
         output_path: str = r"c:\pbl_oceaneye\videos\oceaneye_annotated.mp4"):
    in_file = Path(input_path)
    out_file = Path(output_path)
    if not in_file.is_file():
        print(f"Error: input file {in_file} not found")
        return 1

    print(f"Opening input video: {in_file}")
    cap = cv2.VideoCapture(str(in_file))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"Video resolution: {width}x{height} @ {fps:.1f} fps ({total_frames} frames)")

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(out_file), fourcc, fps, (width, height))

    # Initialize perception and risk pipeline (CPU mode for robust execution without GPU VRAM exhaustion)
    det_cfg = DetectorConfig(model="yolov8n.pt", imgsz=640, device="cpu", conf=0.15)
    detector = YoloDetector(det_cfg)

    trk_cfg = TrackerConfig(track_buffer_seconds=4.0)
    tracker = ByteTrackTracker(trk_cfg, frame_rate=fps)

    risk_cfg = RiskScoringConfig()
    analyzer = RuleBasedBehaviorAnalyzer(risk_cfg)
    engine = RuleBasedRiskEngine(risk_cfg)
    overlay_cfg = OverlayConfig(thickness=2, show_hud=True)

    start_time = datetime.now(timezone.utc)
    frame_idx = 0
    t0 = time.perf_counter()

    stats = {
        "safe_frames": 0,
        "caution_frames": 0,
        "critical_frames": 0,
        "max_risk": 0.0,
        "priority_victim": None,
    }

    print("Beginning video processing and annotation...")
    while True:
        ret, img = cap.read()
        if not ret:
            break
        frame_idx += 1
        t_capture = start_time + timedelta(seconds=frame_idx / fps)
        frame = Frame("cam_cctv_01", t_capture, frame_idx, img)

        # 1. Detection
        detections = detector.detect(frame)

        # 2. Tracking
        tracks = tracker.update("cam_cctv_01", detections, t_capture)

        # 3. Behavior Analysis & Risk Assessment for all tracked people
        risks: dict[str, tuple[str, float]] = {}
        for tr in tracks:
            beh = analyzer.analyze(tr, None, t_capture)
            zone_assess = ZoneAssessment("cam_cctv_01", tr.track_id, t_capture, inside_zone=None)
            assess = engine.assess(RiskInput("cam_cctv_01", tr, zone_assess, beh, EnvironmentContext(None), t_capture))
            lvl = assess.risk_level.value if assess.risk_level else "low"
            risks[tr.track_id] = (lvl, assess.risk_score)

            if assess.risk_score > stats["max_risk"]:
                stats["max_risk"] = assess.risk_score
                stats["priority_victim"] = tr.track_id

        # Tally statistics
        levels = [v[0] for v in risks.values()]
        if any(l in ("high", "critical") for l in levels):
            stats["critical_frames"] += 1
        elif any(l == "medium" for l in levels):
            stats["caution_frames"] += 1
        else:
            stats["safe_frames"] += 1

        # 4. Multi-person visualization with prioritization and color-coded HUD
        pipeline_fps = frame_idx / (time.perf_counter() - t0)
        annotated = draw_tracks(
            img,
            tracks,
            overlay_cfg,
            frame_index=frame_idx,
            timestamp_s=frame_idx / fps,
            camera_id="BEACH CCTV 01",
            fps=pipeline_fps,
            risks=risks,
        )

        writer.write(annotated)

        if frame_idx % 40 == 0 or frame_idx == total_frames:
            print(f"  Frame {frame_idx:3d}/{total_frames} ({frame_idx/fps:4.1f}s) | "
                  f"Tracks={len(tracks)} | Max Risk={stats['max_risk']:.2f} | "
                  f"Critical={stats['critical_frames']} | Caution={stats['caution_frames']}")

    cap.release()
    writer.release()

    total_time = time.perf_counter() - t0
    print(f"\nProcessing complete in {total_time:.1f}s ({frame_idx/total_time:.1f} fps)!")
    print(f"Output saved to: {out_file}")
    print(f"Summary:")
    print(f"  - Total Frames: {frame_idx}")
    print(f"  - Safe/Swimming Frames: {stats['safe_frames']}")
    print(f"  - Caution/Struggling (Yellow) Frames: {stats['caution_frames']}")
    print(f"  - Drowning/Distress (Red) Frames: {stats['critical_frames']}")
    print(f"  - Highest Risk Detected: {stats['max_risk']:.2f}")
    print(f"  - Priority Drowning Victim: {stats['priority_victim']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
