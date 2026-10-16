"""Hardware -> perception profile. Pure policy: no torch, no OpenCV, no I/O.

Why this exists: running ``yolov8s`` at 960 px in two worker processes on a 4 GB laptop GPU ran this
machine out of memory mid-demo (``cv2.error ... Insufficient memory``). Rather than hard-coding one
set of numbers that is wrong on every other machine, the worker measures the machine
(:mod:`app.shared.hardware`) and asks this module what it can afford.

Keeping the decision pure and in one file means it is unit-testable without a GPU, and every
threshold is visible and documented in one place.

EXPERIMENTAL PARAMETERS: the thresholds below are starting points - calibrated so that a 4 GB
laptop GPU and a 2-core CPU box both survive a full demo - not validated OceanEye requirements.
Anything set explicitly in ``.env`` always wins over this policy.
"""
from __future__ import annotations

from dataclasses import dataclass

# Any Ultralytics model name is accepted by the detector; these are the ones the policy picks from
# and the API allows, smallest (fastest) first.
MODEL_LADDER = ("yolov8n.pt", "yolov8s.pt", "yolov8m.pt")

#: Frames kept for the evidence clip are stored at or below this width. Full-resolution annotated
#: frames in the ring buffer were the memory leak that crashed the demo: 6 s at 6 fps of 1080p BGR
#: is ~220 MB *per worker*, and two workers plus the API exhausted the machine.
RING_WIDTH_SMALL = 640
RING_WIDTH_LARGE = 854


@dataclass(frozen=True)
class PerceptionProfile:
    """What one worker process should run with."""

    model: str
    imgsz: int
    target_fps: float
    half: bool
    clip_max_width: int
    reason: str

    def describe(self) -> str:
        return (f"{self.model} @{self.imgsz}px, {self.target_fps:g} fps target, "
                f"{'fp16' if self.half else 'fp32'}, clips <={self.clip_max_width}px ({self.reason})")


def _clip_width(ram_gb: float | None) -> int:
    return RING_WIDTH_SMALL if (ram_gb or 0) < 8 else RING_WIDTH_LARGE


def choose_profile(device: str, *, vram_gb: float | None = None, ram_gb: float | None = None,
                   cpu_count: int = 2, workers_sharing: int = 1,
                   model: str | None = None, imgsz: int | None = None,
                   target_fps: float | None = None) -> PerceptionProfile:
    """Pick model / input size / frame rate for ``device``.

    ``workers_sharing`` is how many worker processes are expected to run at the same time: GPU memory
    and CPU threads are divided between them, so two cameras get a smaller profile than one.
    ``model`` / ``imgsz`` / ``target_fps`` are explicit overrides from configuration and are kept
    verbatim when given (the operator asked for them; we only fill in what they left to us).
    """
    cuda = device.startswith("cuda")
    mps = device.startswith("mps")
    share = max(1, workers_sharing)

    if cuda:
        budget = (vram_gb or 4.0) / share
        tight_ram = ram_gb is not None and ram_gb < 8.0
        if budget >= 6.0 and not tight_ram:
            auto_model, auto_imgsz, auto_fps = "yolov8s.pt", 960, 8.0
        elif budget >= 3.0 and not tight_ram:
            # 4 GB laptop GPU with one worker: 768 px keeps small swimmers visible without the OOM.
            auto_model, auto_imgsz, auto_fps = "yolov8s.pt", 768, 6.0
        elif budget >= 1.5:
            auto_model, auto_imgsz, auto_fps = "yolov8n.pt", 640, 6.0
        else:
            auto_model, auto_imgsz, auto_fps = "yolov8n.pt", 512, 4.0
        why = f"cuda, {budget:.1f} GB VRAM per worker" + (", tight RAM" if tight_ram else "")
    elif mps:
        auto_model, auto_imgsz, auto_fps = "yolov8n.pt", 640, 5.0
        why = "apple gpu (mps)"
    else:
        cores = max(1, cpu_count // share)
        if cores >= 8:
            auto_model, auto_imgsz, auto_fps = "yolov8n.pt", 640, 4.0
        elif cores >= 4:
            auto_model, auto_imgsz, auto_fps = "yolov8n.pt", 512, 3.0
        else:
            auto_model, auto_imgsz, auto_fps = "yolov8n.pt", 416, 2.0
        why = f"cpu only, {cores} core(s) per worker"

    return PerceptionProfile(
        model=model or auto_model,
        imgsz=imgsz or auto_imgsz,
        target_fps=target_fps or auto_fps,
        half=cuda,  # fp16 is a CUDA-only win; it is numerically unhelpful on CPU and unsupported on mps
        clip_max_width=_clip_width(ram_gb),
        reason=why + ("; overridden by configuration" if (model or imgsz or target_fps) else ""),
    )
