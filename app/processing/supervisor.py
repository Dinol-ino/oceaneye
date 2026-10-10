"""Starts/stops worker processes (``python -m app.worker.cli ...``).

The reference PDF asks for the vision/risk pipeline and the alert API to be separate processes: the API
never imports YOLO; each analysis job or monitored camera gets its own worker process (one model each),
which talks back over HTTP. ``max_workers`` caps parallel workers so a laptop is not overloaded.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from abc import ABC, abstractmethod
from pathlib import Path

from app.core.exceptions import ConflictError

logger = logging.getLogger(__name__)


class WorkerLauncher(ABC):
    @abstractmethod
    def start(self, key: str, args: list[str]) -> None: ...

    @abstractmethod
    def stop(self, key: str) -> None: ...

    @abstractmethod
    def is_running(self, key: str) -> bool: ...

    @abstractmethod
    def exit_code(self, key: str) -> int | None:
        """None while running or unknown."""

    @abstractmethod
    def stop_all(self) -> None: ...

    def log_path(self, key: str) -> str | None:
        return None


class SubprocessWorkerLauncher(WorkerLauncher):
    def __init__(self, project_root: Path, logs_dir: Path, api_url: str, max_workers: int, threads: int) -> None:
        self._root, self._logs, self._api = Path(project_root), Path(logs_dir), api_url
        self._max, self._threads = max_workers, threads
        self._procs: dict[str, subprocess.Popen] = {}

    def _running(self) -> list[str]:
        return [k for k, p in self._procs.items() if p.poll() is None]

    def start(self, key: str, args: list[str]) -> None:
        if self.is_running(key):
            raise ConflictError(f"worker '{key}' is already running")
        if len(self._running()) >= self._max:
            raise ConflictError(f"worker limit reached ({self._max}); stop a camera or wait for a job "
                                f"(raise OCEANEYE_MAX_WORKERS only if the PC can handle it)")
        self._logs.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "OCEANEYE_WORKER_API_URL": self._api, "PYTHONUNBUFFERED": "1",
               "OMP_NUM_THREADS": str(self._threads), "MKL_NUM_THREADS": str(self._threads),
               "OPENBLAS_NUM_THREADS": str(self._threads), "OCEANEYE_WORKER_THREADS": str(self._threads)}
        log = open(self.log_path(key), "w", encoding="utf-8")  # noqa: SIM115 - owned by the child
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        self._procs[key] = subprocess.Popen([sys.executable, "-m", "app.worker.cli", *args], cwd=self._root,
                                            env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
        logger.info("worker started", extra={"worker": key, "pid": self._procs[key].pid})

    def stop(self, key: str) -> None:
        p = self._procs.get(key)
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()

    def is_running(self, key: str) -> bool:
        p = self._procs.get(key)
        return bool(p and p.poll() is None)

    def exit_code(self, key: str) -> int | None:
        p = self._procs.get(key)
        return p.poll() if p else None

    def stop_all(self) -> None:
        for k in list(self._procs):
            self.stop(k)

    def log_path(self, key: str) -> str:
        return str(self._logs / f"worker_{key.replace(':', '_')}.log")
