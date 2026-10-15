"""Application service for the prototype video path: uploads, analysis jobs, live camera monitoring.

Framework-free (no FastAPI / SQLAlchemy): routers call this, workers report back through it.
"""
from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from app.core.domain.ids import new_id
from app.core.entities.camera import Camera
from app.core.entities.processing import AnalysisJob, UploadedVideo
from app.core.enums import CameraSourceType, JobStatus
from app.core.exceptions import ConflictError, DomainValidationError, NotFoundError
from app.core.interfaces.clock import Clock
from app.core.interfaces.repositories import CameraRepository, JobRepository, UploadRepository
from app.environment.zones.service import ZoneService
from app.processing.live import LiveFrameStore
from app.processing.supervisor import WorkerLauncher

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".m4v"}
AUTO = "auto"
#: Models the API will hand to a worker. ``auto`` lets the worker size itself to the machine
#: (app.vision.profiles); the rest are explicit choices an operator may force.
ALLOWED_MODELS = {AUTO} | {f"yolov8{s}.pt" for s in "nsmlx"} | {f"yolo11{s}.pt" for s in "nsmlx"}
DEVICE_RE = re.compile(r"^(auto|cpu|mps|cuda(:\d)?)$")
IMGSZ_RANGE = (320, 1920)
MAX_TARGET_FPS = 30.0


@dataclass(frozen=True)
class WorkerDefaults:
    """Defaults from settings. ``auto`` / ``0`` mean "let the worker decide from the hardware"."""

    model: str = AUTO
    imgsz: int = 0
    device: str = AUTO
    target_fps: float = 0.0
    sensitivity: str = "medium"
    clip_max_width: int = 0
    max_workers: int = 1


@dataclass
class ProcessingPaths:
    upload_dir: Path
    jobs_dir: Path

    def __post_init__(self) -> None:
        self.upload_dir, self.jobs_dir = Path(self.upload_dir).resolve(), Path(self.jobs_dir).resolve()


@dataclass(frozen=True)
class JobOptions:
    model: str | None = None
    imgsz: int | None = None
    device: str | None = None
    sensitivity: str | None = None
    extra: dict = field(default_factory=dict)


class ProcessingService:
    def __init__(self, uploads: UploadRepository, jobs: JobRepository, cameras: CameraRepository,
                 zones: ZoneService, launcher: WorkerLauncher, live: LiveFrameStore, clock: Clock,
                 paths: ProcessingPaths, defaults: WorkerDefaults, max_upload_mb: int = 500) -> None:
        self._uploads, self._jobs, self._cameras, self._zones = uploads, jobs, cameras, zones
        self._launcher, self.live, self._clock = launcher, live, clock
        self.paths, self.defaults, self._max_bytes = paths, defaults, max_upload_mb * 1024 * 1024

    # -- uploads -----------------------------------------------------------
    def save_upload(self, filename: str, stream: BinaryIO) -> UploadedVideo:
        name = Path(filename or "").name
        ext = Path(name).suffix.lower()
        if ext not in VIDEO_EXTENSIONS:
            raise DomainValidationError(f"unsupported video type '{ext}'; allowed: {sorted(VIDEO_EXTENSIONS)}")
        upload_id = new_id("vid")
        self.paths.upload_dir.mkdir(parents=True, exist_ok=True)
        target = self.paths.upload_dir / f"{upload_id}{ext}"
        size = 0
        try:
            with open(target, "wb") as out:
                while chunk := stream.read(1024 * 1024):
                    size += len(chunk)
                    if size > self._max_bytes:
                        raise DomainValidationError(f"file larger than {self._max_bytes // (1024 * 1024)} MB")
                    out.write(chunk)
            if size == 0:
                raise DomainValidationError("empty file")
        except BaseException:
            target.unlink(missing_ok=True)  # never leave a partial upload behind
            raise
        upload = UploadedVideo(upload_id, name[:255], target.name, size, self._clock.now())
        self._uploads.save(upload)
        logger.info("video uploaded", extra={"upload_id": upload_id, "bytes": size})
        return upload

    def list_uploads(self) -> list[UploadedVideo]:
        return self._uploads.list()

    def get_upload(self, upload_id: str) -> UploadedVideo:
        u = self._uploads.get(upload_id)
        if u is None:
            raise NotFoundError("Upload", upload_id)
        return u

    def upload_path(self, upload_id: str) -> Path:
        return self.paths.upload_dir / self.get_upload(upload_id).stored_name

    # -- options -----------------------------------------------------------
    def resolve_options(self, opts: JobOptions | None = None) -> dict:
        """Merge request options over the configured defaults and validate the result.

        ``auto`` / ``0`` are passed through to the worker untouched: it is the process that can see
        the GPU, so it is the process that picks a model size. ``workers_sharing`` tells it how many
        siblings it may have to share memory with.
        """
        opts = opts or JobOptions()
        d = self.defaults
        model = opts.model or d.model or AUTO
        if model not in ALLOWED_MODELS:
            raise DomainValidationError(f"model must be one of {sorted(ALLOWED_MODELS)}")
        imgsz = opts.imgsz if opts.imgsz is not None else d.imgsz
        imgsz = int(imgsz or 0)
        if imgsz and not (IMGSZ_RANGE[0] <= imgsz <= IMGSZ_RANGE[1] and imgsz % 32 == 0):
            raise DomainValidationError(
                f"imgsz must be 0 (auto) or a multiple of 32 between {IMGSZ_RANGE[0]} and {IMGSZ_RANGE[1]}")
        device = opts.device or d.device or AUTO
        if not DEVICE_RE.match(device):
            raise DomainValidationError("device must be auto, cpu, mps or cuda[:N]")
        sensitivity = opts.sensitivity or d.sensitivity
        if sensitivity not in ("low", "medium", "high"):
            raise DomainValidationError("sensitivity must be low, medium or high")
        target_fps = float(d.target_fps or 0)
        if target_fps and not (0 < target_fps <= MAX_TARGET_FPS):
            raise DomainValidationError(f"target_fps must be 0 (auto) or between 0 and {MAX_TARGET_FPS:g}")
        return {"model": model, "imgsz": imgsz, "device": device, "sensitivity": sensitivity,
                "target_fps": target_fps, "clip_max_width": int(d.clip_max_width or 0),
                "workers_sharing": max(1, int(d.max_workers or 1))}

    # -- analysis jobs -------------------------------------------------------
    def create_job(self, upload_id: str, camera_id: str, opts: JobOptions | None = None) -> AnalysisJob:
        self.get_upload(upload_id)
        self._camera(camera_id)
        job = AnalysisJob(new_id("job"), upload_id, camera_id, JobStatus.QUEUED, self._clock.now(),
                          options=self.resolve_options(opts))
        self._jobs.save(job)
        try:
            self._launcher.start(f"job:{job.id}", ["job", "--job-id", job.id])
        except ConflictError as exc:
            job.status, job.error, job.finished_at = JobStatus.FAILED, exc.message, self._clock.now()
            self._jobs.save(job)
            raise
        return job

    #: How much of the worker log to scan for the line that explains a crash.
    _LOG_TAIL_BYTES = 8000

    def _worker_error(self, key: str) -> str | None:
        """The worker's own last error line, if its log has one.

        "exited with code 1" is true and useless: the reason is in the subprocess log, which an
        operator looking at the Control Room cannot see. Surfacing the actual exception turns a
        dead end into something diagnosable without a terminal.
        """
        path = self._launcher.log_path(key)
        if not path:
            return None
        try:
            with open(path, "rb") as fh:
                fh.seek(0, 2)
                fh.seek(max(0, fh.tell() - self._LOG_TAIL_BYTES))
                tail = fh.read().decode("utf-8", errors="replace")
        except OSError:
            return None  # the log is the diagnostic aid, never the thing that breaks reaping
        # A traceback's last line carries the exception; prefer it over the generic header.
        lines = [ln.strip() for ln in tail.splitlines() if ln.strip()]
        for line in reversed(lines):
            if ("Error" in line or "Exception" in line) and not line.startswith("File \""):
                return line[:400]
        return lines[-1][:400] if lines else None

    def _reap(self, job: AnalysisJob) -> AnalysisJob:
        if job.status in (JobStatus.QUEUED, JobStatus.RUNNING) and not self._launcher.is_running(f"job:{job.id}"):
            code = self._launcher.exit_code(f"job:{job.id}")
            if code is not None:  # process ended without reporting completion
                key = f"job:{job.id}"
                job.status, job.finished_at = JobStatus.FAILED, self._clock.now()
                reason = self._worker_error(key)
                job.error = (f"{reason} (worker exit code {code}; full log: {self._launcher.log_path(key)})"
                             if reason
                             else f"worker exited with code {code}; see {self._launcher.log_path(key)}")
                logger.warning("analysis job %s failed: %s", job.id, job.error)
                self._jobs.save(job)
        return job

    def list_jobs(self, limit: int = 50) -> list[AnalysisJob]:
        return [self._reap(j) for j in self._jobs.list(limit)]

    def get_job(self, job_id: str) -> AnalysisJob:
        job = self._jobs.get(job_id)
        if job is None:
            raise NotFoundError("Job", job_id)
        return self._reap(job)

    def cancel_job(self, job_id: str) -> AnalysisJob:
        job = self.get_job(job_id)
        if job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
            self._launcher.stop(f"job:{job.id}")
            job.status, job.finished_at = JobStatus.CANCELLED, self._clock.now()
            self._jobs.save(job)
        return job

    def job_dir(self, job_id: str) -> Path:
        return self.paths.jobs_dir / job_id

    def job_worker_config(self, job_id: str) -> dict:
        job = self.get_job(job_id)
        return {"job_id": job.id, "source": str(self.upload_path(job.upload_id)), "loop": False,
                "output_dir": str(self.job_dir(job.id)), "options": job.options,
                **self._camera_config(self._camera(job.camera_id))}

    def report_job(self, job_id: str, status: JobStatus, progress: float | None = None,
                   summary: dict | None = None, error: str | None = None, events_created: int | None = None) -> AnalysisJob:
        job = self.get_job(job_id)
        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            return job
        now = self._clock.now()
        if status is JobStatus.RUNNING and job.started_at is None:
            job.started_at = now
        job.status = status
        if progress is not None:
            job.progress = max(0.0, min(1.0, progress))
        if summary is not None:
            job.summary = summary
        if events_created is not None:
            job.events_created = events_created
        if error:
            job.error = error[:2000]
        if status in (JobStatus.COMPLETED, JobStatus.FAILED):
            job.finished_at = now
            if status is JobStatus.COMPLETED:
                job.progress = 1.0
                if (self.job_dir(job.id) / "overlay.mp4").is_file():
                    job.overlay_key = "overlay.mp4"
        self._jobs.save(job)
        return job

    def job_overlay_path(self, job_id: str) -> Path:
        job = self.get_job(job_id)
        path = self.job_dir(job.id) / (job.overlay_key or "overlay.mp4")
        if not path.is_file():
            raise NotFoundError("Overlay video for job", job_id)
        return path

    def delete_upload_file(self, upload_id: str) -> None:  # pragma: no cover - maintenance helper
        shutil.rmtree(self.paths.upload_dir / upload_id, ignore_errors=True)

    # -- removing test material ----------------------------------------------
    #
    # Analysis is how this system is exercised, so an operator accumulates failed runs and stale
    # clips faster than anything else. Leaving them on screen is not cosmetic: the job table is
    # where you read whether the pipeline works, and a wall of old FAILED rows hides the run you
    # are actually looking at. These removals are deliberate and narrow - they never touch events,
    # evidence or alerts, which are the audit trail and are not the operator's to discard.

    #: A job in one of these states is finished with: nothing is running, nothing will report in.
    TERMINAL_JOB_STATUSES = (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)

    def delete_job(self, job_id: str) -> None:
        """Remove one finished job and its working directory.

        A queued or running job is refused rather than silently cancelled: killing a worker is a
        different decision from tidying up after one, and the caller should have to make it.
        """
        job = self.get_job(job_id)
        if job.status not in self.TERMINAL_JOB_STATUSES:
            raise ConflictError(
                f"Job {job_id} is {job.status.value}. Cancel it before removing it."
            )
        shutil.rmtree(self.job_dir(job_id), ignore_errors=True)
        self._jobs.delete(job_id)
        logger.info("analysis job %s removed", job_id)

    def clear_finished_jobs(self) -> int:
        """Remove every finished job. Returns how many went, so the UI can say."""
        removed = 0
        for job in self._jobs.list(limit=1000):
            if job.status in self.TERMINAL_JOB_STATUSES:
                shutil.rmtree(self.job_dir(job.id), ignore_errors=True)
                self._jobs.delete(job.id)
                removed += 1
        logger.info("cleared %d finished analysis job(s)", removed)
        return removed

    def delete_upload(self, upload_id: str) -> None:
        """Remove an uploaded clip and its file.

        Refused while any job against it is still running, and refused while a camera still uses
        it as a simulated feed - deleting the file under a live worker turns a working camera into
        an unexplained read failure minutes later.
        """
        self.get_upload(upload_id)  # 404 if it never existed
        live = [j.id for j in self._jobs.list_by_upload(upload_id)
                if j.status not in self.TERMINAL_JOB_STATUSES]
        if live:
            raise ConflictError(
                f"Upload {upload_id} is still being analysed by job(s) {', '.join(live)}."
            )
        # A simulated-CCTV camera stores the resolved file path, not the upload id (see
        # app/camera/api/router.py), so the file path is what identifies a user of this upload.
        path = str(self.upload_path(upload_id))
        users = [c.name for c in self._cameras.list() if c.stream_url == path]
        if users:
            raise ConflictError(
                f"Upload {upload_id} is the feed for camera(s) {', '.join(users)}. "
                "Remove the camera first."
            )
        self.delete_upload_file(upload_id)
        self._uploads.delete(upload_id)
        logger.info("upload %s removed", upload_id)

    # -- live cameras --------------------------------------------------------
    def _camera(self, camera_id: str) -> Camera:
        c = self._cameras.get(camera_id)
        if c is None:
            raise NotFoundError("Camera", camera_id)
        return c

    def _camera_config(self, camera: Camera) -> dict:
        zone = self._zones.get_zone(camera.id)
        return {"camera": {"id": camera.id, "name": camera.name, "lat": camera.location.lat,
                           "lon": camera.location.lon, "source_type": camera.source_type.value},
                "zone": {"name": zone.name, "polygon": [list(p) for p in zone.polygon.points]} if zone else None}

    def camera_worker_config(self, camera_id: str) -> dict:
        camera = self._camera(camera_id)
        return {"source": camera.stream_url, "loop": camera.source_type is CameraSourceType.VIDEO_FILE,
                "options": self.resolve_options(), **self._camera_config(camera)}

    def start_monitoring(self, camera_id: str) -> None:
        camera = self._camera(camera_id)
        if camera.source_type is CameraSourceType.MOCK:
            raise DomainValidationError("mock cameras have no video to monitor")
        self._launcher.start(f"cam:{camera.id}", ["camera", "--camera-id", camera.id])
        self.live.set_worker_state(camera.id, "starting")

    def stop_monitoring(self, camera_id: str) -> None:
        self._camera(camera_id)
        self._launcher.stop(f"cam:{camera_id}")
        self.live.set_worker_state(camera_id, "stopped")

    def is_monitoring(self, camera_id: str) -> bool:
        return self._launcher.is_running(f"cam:{camera_id}")

    def live_overview(self) -> list[dict]:
        now = self._clock.now()
        out = []
        for cam in self._cameras.list():
            s = self.live.state(cam.id)
            running = self.is_monitoring(cam.id)
            if not running and s.worker_state in ("running", "starting"):
                code = self._launcher.exit_code(f"cam:{cam.id}")
                s.worker_state = "error" if code not in (None, 0) else "stopped"
                if code not in (None, 0):
                    s.worker_message = f"worker exited ({code}); see {self._launcher.log_path(f'cam:{cam.id}')}"
            out.append({"camera_id": cam.id, "beach_id": cam.beach_id, "monitoring": running,
                        "worker_state": s.worker_state, "worker_message": s.worker_message,
                        "online": self.live.is_online(cam.id, now),
                        "last_frame_at": s.frame_at.isoformat() if s.frame_at else None, "stats": s.stats})
        return out
