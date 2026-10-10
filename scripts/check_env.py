"""Environment doctor for the perception stage (Windows / Linux / Colab).

    python scripts/check_env.py [--source path\\to\\video.mp4]

Reports Python, OpenCV, Ultralytics, PyTorch, GPU visibility, and optionally whether a video opens.
"""
from __future__ import annotations

import argparse
import importlib
import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def version(mod: str) -> str:
    try:
        return getattr(importlib.import_module(mod), "__version__", "installed")
    except Exception as exc:  # noqa: BLE001
        return f"MISSING ({type(exc).__name__})"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="optional video to test-open")
    args = ap.parse_args()
    print(f"python       {sys.version.split()[0]}  ({platform.system()} {platform.release()}, {platform.machine()})")
    for name in ("numpy", "cv2", "ultralytics", "torch"):
        print(f"{name:<12} {version(name)}")
    try:
        import torch

        if torch.cuda.is_available():
            print(f"cuda         available - {torch.cuda.get_device_name(0)} (torch built for CUDA {torch.version.cuda})")
        else:
            built = torch.version.cuda
            print("cuda         NOT available ->", "CPU-only torch build (see docs/perception.md, GPU section)" if not built
                  else "torch has CUDA support but no usable GPU/driver (check nvidia-smi)")
    except ImportError:
        print("cuda         torch not installed")
    if args.source:
        from app.camera.infrastructure.opencv_source import OpenCvFrameSource
        from app.core.exceptions import OceanEyeError

        try:
            src = OpenCvFrameSource("cam_check", args.source)
            info = src.open_sync()
            frame = src.read_sync()
            src.close_sync()
            print(f"source       OK  {info.width}x{info.height} @ {info.fps:.2f} fps, frames={info.frame_count}, "
                  f"first frame {'read' if frame is not None else 'FAILED'}")
        except OceanEyeError as exc:
            print(f"source       FAILED: {exc.message}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
