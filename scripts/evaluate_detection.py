"""Measure OceanEye's distress detection against labelled footage.

WHY THIS EXISTS
---------------
Every threshold in ``app/risk/scoring/config.py`` is a guess chosen to make behaviour visible on
test clips. Until those guesses are measured against footage where someone has written down what
actually happened, no statement about this system's accuracy means anything - and a safety system
whose accuracy is unknown should not claim one.

This script turns clips plus a labels file into precision, recall and a false-alarm rate, and can
sweep a threshold so the trade-off between the two is a curve you can point at rather than an
opinion.

LABELS FILE (JSON)
------------------
One entry per clip. Times are seconds from the start of that clip.

    {
      "clips": [
        {
          "file": "videos/rescue_01.mp4",
          "distress": [[18.0, 31.5]],
          "zone": [[0.0,0.45],[1.0,0.45],[1.0,1.0],[0.0,1.0]],
          "notes": "swimmer caught in rip, lifeguard enters at 31s"
        },
        {"file": "videos/busy_afternoon.mp4", "distress": []}
      ]
    }

``distress`` is a list of [start, end] windows during which a person was genuinely in difficulty.
An empty list means the clip is a negative: nothing in it should raise an event, and anything that
does is a false alarm. Negatives are the most valuable clips you can label and the easiest to
collect - ordinary busy-beach footage.

``zone`` is optional, normalised (0..1, origin top-left). Omit it to evaluate the whole frame.

HOW A MATCH IS DECIDED
----------------------
An event counts as a true positive when its timestamp falls inside a labelled distress window,
extended by ``--grace`` seconds at the start: alerting a few seconds *before* the label begins is
early warning, which is the point, not an error. Every labelled window with no event in it is a
false negative. Every event outside all windows is a false positive.

Recall is reported per *window*, not per event: raising five alerts for one drowning is one
detection, not five.

USAGE
-----
    python scripts/evaluate_detection.py --labels labels.json
    python scripts/evaluate_detection.py --labels labels.json --pose --model yolov8s.pt
    python scripts/evaluate_detection.py --labels labels.json --sweep 0.3,0.4,0.5,0.6,0.7
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run without installing

from app.core.exceptions import OceanEyeError  # noqa: E402
from app.risk.distress.rules import RuleBasedBehaviorAnalyzer  # noqa: E402
from app.risk.engine.base import RiskInput  # noqa: E402
from app.risk.engine.rules import RuleBasedRiskEngine  # noqa: E402
from app.risk.scoring.config import RiskScoringConfig  # noqa: E402
from app.vision.config import DetectorConfig, PerceptionConfig, TrackerConfig  # noqa: E402
from app.vision.pose.yolo_pose import PoseConfig  # noqa: E402


@dataclass
class ClipResult:
    file: str
    windows: list[tuple[float, float]]
    event_times: list[float]
    true_positive_windows: int
    false_positives: int
    frames: int
    seconds: float

    @property
    def missed(self) -> int:
        return len(self.windows) - self.true_positive_windows


def _point_in_polygon(x: float, y: float, poly: list[tuple[float, float]]) -> bool:
    """Ray casting. Kept local so evaluation does not depend on the zone service's wiring."""
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1:
            inside = not inside
    return inside


class _StubZone:
    __slots__ = ("inside_zone",)

    def __init__(self, inside) -> None:
        self.inside_zone = inside


class _StubEnvironment:
    """No weather during evaluation: the boost would vary run to run and make results
    irreproducible. Measure the vision and behaviour chain on its own."""

    conditions = None


def evaluate_clip(path: Path, label: dict, cfg: PerceptionConfig, scoring: RiskScoringConfig,
                  grace: float, verbose: bool) -> ClipResult:
    from app.vision.runner import PerceptionRunner  # imports OpenCV

    windows = [(float(a), float(b)) for a, b in label.get("distress", [])]
    zone = label.get("zone")
    analyzer = RuleBasedBehaviorAnalyzer(scoring)
    engine = RuleBasedRiskEngine(scoring)
    event_times: list[float] = []
    state = {"frames": 0, "t0": None, "last": 0.0, "size": (0, 0)}

    def on_frame(frame, result, _annotated) -> None:
        state["frames"] += 1
        if state["t0"] is None:
            state["t0"] = frame.captured_at
        seconds = (frame.captured_at - state["t0"]).total_seconds()
        state["last"] = seconds
        if frame.image is not None:
            h, w = frame.image.shape[:2]
            state["size"] = (w, h)
        w, h = state["size"]

        for track in result.tracks:
            pose = result.poses.get(track.track_id) if result.poses else None
            assessment = analyzer.analyze(track, pose, frame.captured_at)
            if not assessment.signals:
                continue
            inside = None
            if zone and w and h:
                cx, cy = track.current.bbox.center
                inside = _point_in_polygon(cx / w, cy / h, [(float(a), float(b)) for a, b in zone])
            verdict = engine.assess(RiskInput(
                camera_id=cfg.camera_id, track=track, behavior=assessment,
                zone=_StubZone(inside), environment=_StubEnvironment(), now=frame.captured_at,
            ))
            if verdict.actionable:
                event_times.append(seconds)
                if verbose:
                    print(f"    event @ {seconds:7.2f}s  score={verdict.risk_score:.2f}  {verdict.reason}")

    runner = PerceptionRunner(replace(cfg, save_video=False, save_tracks=False, show=False),
                              on_frame=on_frame)
    runner.run(str(path))

    hit_windows = 0
    for start, end in windows:
        if any(start - grace <= t <= end for t in event_times):
            hit_windows += 1
    false_positives = sum(
        1 for t in event_times if not any(start - grace <= t <= end for start, end in windows)
    )
    return ClipResult(str(path), windows, event_times, hit_windows, false_positives,
                      state["frames"], state["last"])


def report(results: list[ClipResult], threshold: float) -> dict:
    detected = sum(r.true_positive_windows for r in results)
    total_windows = sum(len(r.windows) for r in results)
    false_pos = sum(r.false_positives for r in results)
    minutes = sum(r.seconds for r in results) / 60 or 1e-9

    recall = detected / total_windows if total_windows else None
    precision = detected / (detected + false_pos) if (detected + false_pos) else None
    return {
        "alert_threshold": threshold,
        "distress_windows": total_windows,
        "detected": detected,
        "missed": total_windows - detected,
        "false_alarms": false_pos,
        "recall": round(recall, 3) if recall is not None else None,
        "precision": round(precision, 3) if precision is not None else None,
        "false_alarms_per_hour": round(false_pos / minutes * 60, 2),
        "footage_minutes": round(minutes, 1),
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--labels", required=True, help="labels JSON (see the docstring above)")
    p.add_argument("--model", default="yolov8n.pt")
    p.add_argument("--weights-dir", default="models")
    p.add_argument("--device", default="auto")
    p.add_argument("--imgsz", type=int, default=DetectorConfig.imgsz)
    p.add_argument("--stride", type=int, default=2,
                   help="process every Nth frame (default %(default)s: evaluation is not live)")
    p.add_argument("--pose", action="store_true", help="enable the YOLO-pose posture signals")
    p.add_argument("--pose-model", default="yolov8n-pose.pt")
    p.add_argument("--sensitivity", default="medium", choices=["low", "medium", "high"])
    p.add_argument("--sweep", default=None,
                   help="comma-separated alert thresholds to try, e.g. 0.3,0.4,0.5,0.6")
    p.add_argument("--grace", type=float, default=5.0,
                   help="seconds before a labelled window in which an alert still counts as a hit")
    p.add_argument("--out", default="outputs/evaluation.json")
    p.add_argument("-v", "--verbose", action="store_true", help="print every event as it is raised")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    labels_path = Path(args.labels)
    if not labels_path.is_file():
        print(f"Labels file not found: {labels_path}", file=sys.stderr)
        return 2
    clips = json.loads(labels_path.read_text(encoding="utf-8")).get("clips", [])
    if not clips:
        print("No clips in the labels file. Nothing to measure.", file=sys.stderr)
        return 2

    cfg = PerceptionConfig(
        camera_id="eval",
        detector=DetectorConfig(model=args.model, weights_dir=args.weights_dir,
                                device=args.device, imgsz=args.imgsz),
        tracker=TrackerConfig(),
        pose=PoseConfig(enabled=args.pose, model=args.pose_model,
                        weights_dir=args.weights_dir, device=args.device),
        stride=args.stride, save_video=False, save_tracks=False,
    )

    thresholds = ([float(t) for t in args.sweep.split(",")] if args.sweep
                  else [RiskScoringConfig.preset(args.sensitivity).alert_threshold])

    all_reports = []
    for threshold in thresholds:
        scoring = replace(RiskScoringConfig.preset(args.sensitivity), alert_threshold=threshold)
        print(f"\n=== alert_threshold = {threshold} "
              f"(sensitivity {args.sensitivity}, pose {'on' if args.pose else 'off'}) ===")
        results = []
        for entry in clips:
            path = Path(entry["file"])
            if not path.is_file():
                print(f"  SKIP (missing): {path}")
                continue
            print(f"  {path.name} ...", flush=True)
            try:
                r = evaluate_clip(path, entry, cfg, scoring, args.grace, args.verbose)
            except OceanEyeError as exc:
                print(f"  ERROR on {path.name}: {exc.message}", file=sys.stderr)
                continue
            kind = "negative" if not r.windows else f"{len(r.windows)} window(s)"
            print(f"    {kind}: detected {r.true_positive_windows}, "
                  f"missed {r.missed}, false alarms {r.false_positives}")
            results.append(r)
        if results:
            summary = report(results, threshold)
            all_reports.append(summary)
            print("  " + json.dumps(summary))

    if not all_reports:
        print("\nNo clips were evaluated. Check the paths in the labels file.", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": args.model, "pose": args.pose, "sensitivity": args.sensitivity,
        "reports": all_reports,
    }, indent=2), encoding="utf-8")
    print(f"\nWritten: {out}")
    print("These numbers describe THIS footage only. Report them with the clip count and the "
          "minutes of video behind them, never as a general accuracy figure.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
