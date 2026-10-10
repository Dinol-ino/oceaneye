"""Stages 1-4: video -> YOLO person detection -> ByteTrack -> overlay video + tracks.jsonl.

Windows PowerShell examples (from the project folder, venv active):

    python scripts/run_perception.py --source "C:\\Users\\me\\Videos\\beach 01.mp4"
    python scripts/run_perception.py --source clips\\beach.mp4 --model yolov8s.pt --device cuda:0 --show
    python scripts/run_perception.py --source 0                      # webcam
    python scripts/run_perception.py --source rtsp://192.168.1.20:8080/live   # phone / CCTV

Needs:  pip install -e ".[vision]"   (see docs/perception.md for GPU / CUDA notes)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run without installing

from app.core.exceptions import OceanEyeError  # noqa: E402
from app.vision.config import DetectorConfig, OverlayConfig, PerceptionConfig, TrackerConfig  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", required=True, help="video file path | webcam index | rtsp/http URL")
    p.add_argument("--camera-id", default="cam_01")
    p.add_argument("--model", default="yolov8n.pt", help="Ultralytics model name or path (default: %(default)s)")
    p.add_argument("--weights-dir", default="models", help="where bare model names are downloaded/stored")
    p.add_argument("--device", default="auto", help="auto | cpu | cuda:0 | mps")
    p.add_argument("--imgsz", type=int, default=DetectorConfig.imgsz)
    p.add_argument("--conf", type=float, default=DetectorConfig.conf, help="detector confidence floor (experimental)")
    p.add_argument("--stride", type=int, default=1, help="process every Nth frame")
    p.add_argument("--max-frames", type=int, default=None, help="stop after N processed frames")
    p.add_argument("--output-dir", default="outputs/perception")
    p.add_argument("--no-video", action="store_true", help="do not write overlay.mp4")
    p.add_argument("--no-tracks", action="store_true", help="do not write tracks.jsonl")
    p.add_argument("--show", action="store_true", help="live preview window (q to quit)")
    p.add_argument("--trail", type=int, default=OverlayConfig.trail_length, help="trajectory length in frames")
    p.add_argument("--trail-anchor", choices=["center", "bottom"], default="center")
    p.add_argument("--track-buffer", type=int, default=TrackerConfig.track_buffer)
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = PerceptionConfig(
        camera_id=args.camera_id,
        detector=DetectorConfig(model=args.model, weights_dir=args.weights_dir, device=args.device,
                                imgsz=args.imgsz, conf=args.conf),
        tracker=TrackerConfig(track_buffer=args.track_buffer),
        overlay=OverlayConfig(trail_length=args.trail, trail_anchor=args.trail_anchor),
        stride=args.stride, max_frames=args.max_frames, output_dir=args.output_dir,
        save_video=not args.no_video, save_tracks=not args.no_tracks, show=args.show,
    )
    try:
        from app.vision.runner import PerceptionRunner  # imports OpenCV

        summary = PerceptionRunner(cfg).run(args.source)
    except ImportError as exc:
        print(f"Missing dependency: {exc}\nInstall with:  pip install -e \".[vision]\"", file=sys.stderr)
        return 2
    except OceanEyeError as exc:
        print(f"Error: {exc.message}", file=sys.stderr)
        return 1
    print(json.dumps({k: v for k, v in summary.__dict__.items() if k != "config"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
