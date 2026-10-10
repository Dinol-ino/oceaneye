"""Worker process entry point (started by the API's supervisor, or by hand for debugging):

    python -m app.worker.cli job --job-id job_xxx
    python -m app.worker.cli camera --camera-id cam_xxx
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import traceback

from app.config.settings import get_settings
from app.evidence.local import LocalEvidenceStorage
from app.worker.api_client import ApiClient, ApiError

logger = logging.getLogger("oceaneye.worker")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.worker.cli")
    p.add_argument("--api", default=os.environ.get("OCEANEYE_WORKER_API_URL"))
    sub = p.add_subparsers(dest="mode", required=True)
    sub.add_parser("job").add_argument("--job-id", required=True)
    sub.add_parser("camera").add_argument("--camera-id", required=True)
    args = p.parse_args(argv)

    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    threads = int(os.environ.get("OCEANEYE_WORKER_THREADS", settings.worker_threads))
    client = ApiClient(args.api or settings.worker_api_url, settings.api_prefix)
    evidence = LocalEvidenceStorage(settings.evidence_dir)

    from app.vision.devices import limit_torch_threads
    from app.vision.media import limit_opencv_threads
    from app.worker.session import MonitoringSession, SessionConfig

    limit_torch_threads(threads)
    limit_opencv_threads(1)

    if args.mode == "job":
        try:
            cfg = SessionConfig.from_worker_config("job", client.get(f"/processing/jobs/{args.job_id}/worker-config"))
            client.post(f"/processing/jobs/{args.job_id}/report", {"status": "running", "progress": 0.0})
            summary = MonitoringSession(cfg, client, evidence).run()
            client.post(f"/processing/jobs/{args.job_id}/report",
                        {"status": "completed", "summary": summary, "events_created": summary["events_created"]})
            logger.info("job done: %s", summary)
            return 0
        except Exception as exc:  # noqa: BLE001 - report every failure to the dashboard
            logger.error("job failed\n%s", traceback.format_exc())
            try:
                client.post(f"/processing/jobs/{args.job_id}/report",
                            {"status": "failed", "error": f"{type(exc).__name__}: {exc}"[:3900]}, retries=1)
            except ApiError:
                pass
            return 1

    cam = args.camera_id
    try:
        cfg = SessionConfig.from_worker_config("camera", client.get(f"/processing/cameras/{cam}/worker-config"))
        client.post(f"/processing/cameras/{cam}/state", {"state": "running", "message": f"model {cfg.model}"})
        MonitoringSession(cfg, client, evidence).run()
        client.post(f"/processing/cameras/{cam}/state", {"state": "stopped", "message": "source ended"})
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as exc:  # noqa: BLE001
        logger.error("camera worker failed\n%s", traceback.format_exc())
        try:
            client.post(f"/processing/cameras/{cam}/state",
                        {"state": "error", "message": f"{type(exc).__name__}: {exc}"[:1900]}, retries=1)
        except ApiError:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
