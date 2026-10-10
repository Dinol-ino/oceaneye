"""Hardware facts about this machine, using the standard library only.

Deliberately free of torch / OpenCV so *any* layer may import it: the API process needs the CPU and
memory numbers to decide how many worker processes it may spawn, and the worker process needs them
to pick a model size. ``app.vision.profiles`` turns these numbers into a perception profile.

Everything degrades to ``None`` rather than raising: a machine we cannot measure is treated as a
small machine, which is the safe direction.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache

logger = logging.getLogger(__name__)

NVIDIA_SMI_TIMEOUT_S = 4.0


@dataclass(frozen=True)
class Hardware:
    cpu_count: int
    ram_gb: float | None
    vram_gb: float | None  # largest single GPU, as reported by nvidia-smi (not a CUDA usability check)
    gpu_name: str | None

    def describe(self) -> str:
        parts = [f"{self.cpu_count} cpu"]
        if self.ram_gb:
            parts.append(f"{self.ram_gb:.1f} GB RAM")
        if self.gpu_name:
            parts.append(f"{self.gpu_name} ({self.vram_gb:.1f} GB VRAM)" if self.vram_gb else self.gpu_name)
        return ", ".join(parts)


def _ram_gb() -> float | None:
    """Total physical memory in GiB. Windows uses GlobalMemoryStatusEx; POSIX uses sysconf."""
    try:
        if sys.platform == "win32":
            import ctypes  # noqa: PLC0415

            class _MemStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            status = _MemStatus()
            status.dwLength = ctypes.sizeof(_MemStatus)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
                return None
            return status.ullTotalPhys / 1024**3
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return (pages * page_size) / 1024**3
    except Exception:  # noqa: BLE001 - an unmeasurable machine is treated as a small one
        return None


def _gpu_via_nvidia_smi() -> tuple[float | None, str | None]:
    """(VRAM GiB, name) of the largest NVIDIA GPU, or (None, None).

    nvidia-smi is used instead of torch so that the API process - which must never import torch -
    can still size its worker pool. It reports *installed* hardware; whether CUDA is actually usable
    from Python is decided separately by ``app.vision.devices.resolve_device``.
    """
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None, None
    try:
        out = subprocess.run([exe, "--query-gpu=memory.total,name", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=NVIDIA_SMI_TIMEOUT_S, check=True).stdout
    except (subprocess.SubprocessError, OSError) as exc:
        logger.debug("nvidia-smi unavailable: %s", type(exc).__name__)
        return None, None
    best: tuple[float, str] | None = None
    for line in out.splitlines():
        mib, _, name = line.partition(",")
        try:
            gb = float(mib.strip()) / 1024
        except ValueError:
            continue
        if best is None or gb > best[0]:
            best = (gb, name.strip() or "NVIDIA GPU")
    return best if best else (None, None)


@lru_cache(maxsize=1)
def probe() -> Hardware:
    """Measure the machine once per process (cached: nvidia-smi costs ~100 ms)."""
    vram, gpu = _gpu_via_nvidia_smi()
    hw = Hardware(cpu_count=os.cpu_count() or 2, ram_gb=_ram_gb(), vram_gb=vram, gpu_name=gpu)
    logger.debug("hardware: %s", hw.describe())
    return hw


#: Rough cost of one worker process: model weights + CUDA context + decode buffers + evidence ring.
VRAM_PER_WORKER_GB = 2.0
RAM_PER_WORKER_GB = 3.0
MAX_WORKER_SLOTS = 4


def recommend_worker_slots(hw: Hardware | None = None) -> int:
    """How many analysis worker processes this machine can host at once.

    Each worker loads its own detector, so the limit is memory rather than CPU time. Pure policy over
    the measured numbers, kept here (stdlib only) because the API process decides this and must never
    import torch. Two workers at a large input size is exactly what ran this machine out of memory,
    so the bias is deliberately conservative.
    """
    hw = hw or probe()
    if hw.vram_gb:
        limit = int(hw.vram_gb // VRAM_PER_WORKER_GB)
    else:
        limit = hw.cpu_count // 4
    if hw.ram_gb:
        limit = min(limit, int(hw.ram_gb // RAM_PER_WORKER_GB))
    return max(1, min(limit, MAX_WORKER_SLOTS))
