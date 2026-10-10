"""The auto-tune policy: the thing that stops a demo running the machine out of memory.

Pure functions over measured numbers, so these run on any machine, GPU or not.
"""
from __future__ import annotations

import pytest

from app.shared.hardware import Hardware, recommend_worker_slots
from app.vision.profiles import RING_WIDTH_LARGE, RING_WIDTH_SMALL, choose_profile


def test_small_laptop_gpu_gets_a_profile_that_fits_one_worker():
    """4 GB laptop GPU, one worker: large enough to see distant swimmers, small enough to survive."""
    p = choose_profile("cuda:0", vram_gb=4.0, ram_gb=16.0, cpu_count=8, workers_sharing=1)
    assert p.model == "yolov8s.pt" and p.imgsz == 768 and p.half is True
    assert "cuda" in p.reason


def test_the_same_gpu_shared_by_two_workers_drops_to_the_small_model():
    """The exact configuration that crashed: yolov8s @960 x2 on 4 GB. The policy must refuse it."""
    one = choose_profile("cuda:0", vram_gb=4.0, ram_gb=16.0, workers_sharing=1)
    two = choose_profile("cuda:0", vram_gb=4.0, ram_gb=16.0, workers_sharing=2)
    assert two.imgsz < one.imgsz
    assert (two.model, two.imgsz) == ("yolov8n.pt", 640)


def test_big_gpu_gets_the_larger_input_size():
    p = choose_profile("cuda:0", vram_gb=12.0, ram_gb=32.0, workers_sharing=1)
    assert (p.model, p.imgsz, p.target_fps) == ("yolov8s.pt", 960, 8.0)


@pytest.mark.parametrize("cores,imgsz,fps", [(16, 640, 4.0), (4, 512, 3.0), (2, 416, 2.0)])
def test_cpu_only_scales_with_cores_and_never_picks_a_big_model(cores, imgsz, fps):
    p = choose_profile("cpu", ram_gb=8.0, cpu_count=cores, workers_sharing=1)
    assert (p.model, p.imgsz, p.target_fps) == ("yolov8n.pt", imgsz, fps)
    assert p.half is False  # fp16 is a CUDA-only win


def test_mps_does_not_request_half_precision():
    assert choose_profile("mps", ram_gb=16.0).half is False


def test_explicit_configuration_always_wins():
    p = choose_profile("cpu", ram_gb=4.0, cpu_count=2, model="yolov8m.pt", imgsz=1280, target_fps=12.0)
    assert (p.model, p.imgsz, p.target_fps) == ("yolov8m.pt", 1280, 12.0)
    assert "overridden by configuration" in p.reason


def test_clip_width_is_reduced_on_a_low_memory_machine():
    """The evidence ring buffer is what exhausted memory; its width follows available RAM."""
    assert choose_profile("cpu", ram_gb=4.0).clip_max_width == RING_WIDTH_SMALL
    assert choose_profile("cpu", ram_gb=32.0).clip_max_width == RING_WIDTH_LARGE


def test_unmeasurable_machine_is_treated_as_a_small_one():
    p = choose_profile("cpu")
    assert p.model == "yolov8n.pt" and p.clip_max_width == RING_WIDTH_SMALL


@pytest.mark.parametrize("hw,expected", [
    (Hardware(8, 16.0, 4.0, "RTX 2050"), 2),     # 4 GB VRAM -> 2 slots
    (Hardware(8, 6.0, 4.0, "RTX 2050"), 2),      # RAM also allows 2
    (Hardware(8, 3.0, 4.0, "RTX 2050"), 1),      # 3 GB RAM caps it to one
    (Hardware(16, 32.0, 24.0, "A5000"), 4),      # capped at the hard maximum
    (Hardware(2, 2.0, None, None), 1),           # tiny CPU box
    (Hardware(16, 64.0, None, None), 4),
])
def test_worker_slots_follow_the_scarcest_resource(hw, expected):
    assert recommend_worker_slots(hw) == expected


def test_worker_slots_are_never_zero():
    assert recommend_worker_slots(Hardware(1, 0.5, 0.5, "tiny")) == 1


def test_hardware_describe_is_readable_without_a_gpu():
    assert recommend_worker_slots(Hardware(4, 8.0, None, None)) >= 1
    assert "cpu" in Hardware(4, 8.0, None, None).describe()
