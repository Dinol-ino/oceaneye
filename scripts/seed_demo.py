"""Build a ready-to-present demo from the clips in videos/ (the API must already be running).

For every video: upload it, register it as a *simulated CCTV camera* along the coast at this
installation's beach, and give it a default danger zone (the lower 60% of the frame - a demo guess;
redraw real zones in the Control Room). Optionally start monitoring the first N cameras.

    python scripts/seed_demo.py                  # cameras only
    python scripts/seed_demo.py --start 2        # and start 2 camera workers
    python scripts/seed_demo.py --start 1        # safest on a laptop GPU

Never starts more workers than the server says it can host.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config.settings import get_settings  # noqa: E402

NAMES = ["North watch tower", "Central lifeguard post", "South rocks", "Estuary mouth", "Pier view", "Family zone"]
EXT = {".mp4", ".avi", ".mov", ".mkv", ".m4v"}
DEMO_ZONE = [[0, 0.4], [1, 0.4], [1, 1], [0, 1]]


def main() -> int:
    s = get_settings()
    default_api = f"{'https' if s.tls_enabled else 'http'}://127.0.0.1:{s.port}"
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default=default_api)
    ap.add_argument("--videos", default=str(ROOT / "videos"))
    ap.add_argument("--start", type=int, default=0, help="start monitoring this many cameras")
    args = ap.parse_args()

    headers = {"X-Dev-Role": "operator", "X-Dev-User": "demo-seed"}
    # verify=False: the prototype's TLS certificate is self-signed on purpose (scripts/make_certs.py).
    api_url = args.api.rstrip("/")
    try_urls = [api_url]
    if api_url.startswith("http://"):
        try_urls.append("https://" + api_url[len("http://"):])

    cfg = None
    last_exc = None
    for url in try_urls:
        try:
            with httpx.Client(base_url=url + "/api", headers=headers, timeout=120, verify=False) as c:
                cfg = c.get("/config/public").raise_for_status().json()
                api_url = url
                break
        except httpx.HTTPError as exc:
            last_exc = exc

    if cfg is None:
        print(f"API not reachable at {args.api} ({last_exc}). Start it first: python scripts/run_api.py")
        return 1

    with httpx.Client(base_url=api_url + "/api", headers=headers, timeout=120, verify=False) as c:

        beach = cfg.get("beach")
        if not beach:
            print("No deployment beach configured. Open the Control Room and choose one first.")
            return 1
        print(f"Beach: {beach['label']}  ({cfg['max_workers']} worker slot(s) on this machine)")

        videos = sorted(p for p in Path(args.videos).iterdir() if p.suffix.lower() in EXT)
        if not videos:
            print(f"no videos in {args.videos}")
            return 1

        existing = {cam["name"] for cam in c.get("/cameras").json()}
        created = []
        for i, video in enumerate(videos):
            name = f"{beach['name'].split(',')[0]} – {NAMES[i % len(NAMES)]}"
            if name in existing:
                print(f"skip (exists): {name}")
                continue
            with open(video, "rb") as f:
                upload = c.post("/uploads", files={"file": (video.name, f, "video/mp4")}).raise_for_status().json()
            cam = c.post("/cameras", json={
                "name": name,
                "lat": round(beach["lat"] + 0.006 * i, 5),
                "lon": round(beach["lon"] - 0.0015 * i, 5),
                "beach_id": beach["id"],
                "video_upload_id": upload["id"],
            }).raise_for_status().json()
            c.put(f"/zones/{cam['id']}", json={"name": "Swim area (demo default)",
                                               "polygon": DEMO_ZONE}).raise_for_status()
            created.append(cam)
            print(f"camera {cam['id']}  {name}  <- {video.name}")

        # Each worker loads its own model; starting more than the machine can host is what used to
        # run it out of memory, so the server's own limit wins over the requested number.
        to_start = min(args.start, cfg["max_workers"], len(created))
        if args.start > to_start:
            print(f"starting {to_start} of {args.start} requested (this machine hosts {cfg['max_workers']})")
        for cam in created[:to_start]:
            r = c.post(f"/cameras/{cam['id']}/monitoring/start")
            print(f"monitoring {cam['name']}: {'starting' if r.status_code < 400 else r.json()}")

    print(f"\nOpen {args.api}/ui/control.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
