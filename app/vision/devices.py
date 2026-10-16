"""Compute-device discovery. torch is imported lazily: environments without it still work (CPU paths)."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def resolve_device(requested: str = "auto") -> str:
    """Turn ``auto`` into a concrete device, and verify an explicitly requested one is usable.

    An explicit ``cuda:0`` that is not actually available used to fail deep inside Ultralytics with
    an opaque error; here it falls back to the CPU with a clear warning so a monitoring session keeps
    running (degraded) instead of dying.
    """
    if requested != "auto":
        if requested.startswith("cuda") and not _cuda_available():
            logger.warning("device '%s' requested but CUDA is not available; falling back to cpu "
                           "(install a CUDA build of torch - see docs/perception.md)", requested)
            return "cpu"
        if requested.startswith("mps") and not _mps_available():
            logger.warning("device 'mps' requested but Apple GPU support is not available; using cpu")
            return "cpu"
        return requested
    if _cuda_available():
        return "cuda:0"
    if _mps_available():
        return "mps"
    return "cpu"


def _cuda_available() -> bool:
    try:
        import torch  # noqa: PLC0415
        return bool(torch.cuda.is_available())
    except Exception as exc:  # noqa: BLE001 - DLL load errors or low paging file fall back to CPU
        logger.warning("CUDA is not available (%s); falling back to CPU", exc)
        return False


def _mps_available() -> bool:
    try:
        import torch  # noqa: PLC0415
        mps = getattr(getattr(torch, "backends", None), "mps", None)
        return bool(mps is not None and mps.is_available())
    except Exception:  # noqa: BLE001
        return False


def describe_device(device: str) -> str:
    if device.startswith("cuda"):
        try:
            import torch  # noqa: PLC0415

            index = int(device.split(":")[1]) if ":" in device else 0
            return f"{device} ({torch.cuda.get_device_name(index)})"
        except Exception:  # noqa: BLE001
            return device
    return device


def cuda_total_memory_gb(device: str = "cuda:0") -> float | None:
    """Total VRAM of ``device`` in GiB, via torch (the worker's view; the API uses nvidia-smi)."""
    if not device.startswith("cuda"):
        return None
    try:
        import torch  # noqa: PLC0415

        index = int(device.split(":")[1]) if ":" in device else 0
        return torch.cuda.get_device_properties(index).total_memory / 1024**3
    except Exception:  # noqa: BLE001
        return None


def limit_torch_threads(n: int) -> None:
    """Cap CPU threads so a CPU-only laptop stays responsive while a worker runs."""
    try:
        import torch  # noqa: PLC0415

        torch.set_num_threads(max(1, n))
    except ImportError:
        pass


def release_cuda_cache(device: str = "") -> None:
    """Hand cached VRAM back to the driver. Called when a session ends so a second worker can start."""
    if device and not device.startswith("cuda"):
        return
    try:
        import torch  # noqa: PLC0415

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass
