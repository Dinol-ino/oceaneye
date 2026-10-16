"""Run scripts/evaluate_detection.py over a grid of settings and print ONE comparison table.

Why: "is yolov8s better than yolov8n here?" and "what does pose cost me?" are questions about YOUR
footage. Answer them with numbers per configuration instead of one-off runs.

    python scripts/run_clip_matrix.py --labels labels.json --dry-run          # show the commands
    python scripts/run_clip_matrix.py --labels labels.json                    # default grid
    python scripts/run_clip_matrix.py --labels labels.json --models yolov8n.pt,yolov8s.pt \
        --imgsz 640,960 --strides 2,4 --pose off,on --sens medium,high

Stride is on the SOURCE frame rate: 30 fps source + stride 4 = 7.5 fps analysed (a GPU profile),
stride 10 = 3 fps (a CPU profile). Keep the stride/fps column in mind when comparing rows - the
behaviour layer's verdict changes with analysed fps (tests/hardening D1-D3).
"""
from __future__ import annotations

import argparse
import itertools
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--labels", default="labels.json")
    p.add_argument("--models", default="yolov8n.pt,yolov8s.pt")
    p.add_argument("--imgsz", default="640,960")
    p.add_argument("--strides", default="4,10")
    p.add_argument("--pose", default="off,on")
    p.add_argument("--sens", default="medium")
    p.add_argument("--device", default="auto")
    p.add_argument("--out-dir", default="outputs/matrix")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    split = lambda s: [x.strip() for x in s.split(",") if x.strip()]  # noqa: E731
    out_dir = ROOT / a.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for model, imgsz, stride, pose, sens in itertools.product(
            split(a.models), split(a.imgsz), split(a.strides), split(a.pose), split(a.sens)):
        tag = f"{Path(model).stem}_{imgsz}_s{stride}_pose-{pose}_{sens}"
        out = out_dir / f"{tag}.json"
        cmd = [sys.executable, str(ROOT / "scripts" / "evaluate_detection.py"), "--labels", a.labels,
               "--model", model, "--imgsz", imgsz, "--stride", stride, "--sensitivity", sens,
               "--device", a.device, "--out", str(out)]
        if pose == "on":
            cmd.append("--pose")
        print("$", " ".join(cmd))
        if a.dry_run:
            continue
        code = subprocess.call(cmd, cwd=ROOT)
        if code != 0 or not out.is_file():
            rows.append((tag, "FAILED", "", "", "", "", ""))
            continue
        rep = json.loads(out.read_text(encoding="utf-8"))["reports"][0]
        rows.append((tag, rep["distress_windows"], rep["detected"], rep["missed"], rep["false_alarms"],
                     rep["false_alarms_per_hour"], rep["footage_minutes"]))
    if a.dry_run:
        return 0
    print("\n" + f"{'config':44s} {'windows':>7} {'hit':>4} {'miss':>5} {'FA':>4} {'FA/h':>6} {'min':>6}")
    for r in rows:
        print(f"{r[0]:44s} " + " ".join(f"{str(x):>{w}}" for x, w in zip(r[1:], (7, 4, 5, 4, 6, 6))))
    print("\nwindows = labelled distress windows. With 0 windows, recall is undefined: add positive footage.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
