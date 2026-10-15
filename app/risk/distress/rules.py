"""Interpretable distress heuristics over a track's recent history (roadmap Stage 7).

These are *heuristics*, not a drowning classifier: each signal is weak evidence that can also fit
normal behaviour (someone floating still, playing in waves). The risk engine combines them with the
zone gate, persistence and environment before anything becomes a candidate event.

Two families of signal, and the difference matters:

* **Trajectory signals** (stillness, bobbing, erratic, submersion) read only the bounding box. They
  work at any distance and need no second model, but they cannot separate a swimmer from someone
  in difficulty - both are a box drifting in water.
* **Pose signals** (vertical_in_water, arms_raised) read COCO-17 keypoints and can. They are only
  available when a PoseEstimator is wired in and returns keypoints for that track; when it does
  not, they are simply not raised. A missing pose means *unknown*, never *fine*.
"""
from __future__ import annotations

import math
from datetime import datetime
from statistics import median

from app.core.enums import DistressSignalType
from app.risk.distress.base import BehaviorAnalyzer, BehaviorAssessment, DistressSignal
from app.risk.scoring.config import RiskScoringConfig
from app.vision.pose.base import PoseEstimate, PoseKeypoint
from app.vision.tracking.base import Track


class RuleBasedBehaviorAnalyzer(BehaviorAnalyzer):
    def __init__(self, config: RiskScoringConfig | None = None) -> None:
        self.cfg = config or RiskScoringConfig()

    def analyze(self, track: Track, pose: PoseEstimate | None, now: datetime) -> BehaviorAssessment:
        """Signals for one track, or an empty assessment when this track cannot be judged.

        Three gates come first, and all three return *nothing* rather than a low score. In a
        safety system "no evidence" and "evidence of safety" are different statements, and
        collapsing them is how a system ends up quietly confident about a person it never
        actually resolved.
        """
        cfg = self.cfg
        hist = [d for d in track.history if (now - d.timestamp).total_seconds() <= max(cfg.window_seconds, cfg.still_seconds)]
        if len(hist) < cfg.min_samples:
            return BehaviorAssessment(track.camera_id, track.track_id, now)

        # Gate 1 - maturity. A track younger than this is far more likely a fragment (a
        # re-identification, a wave crest, a split detection) than a person worth judging.
        track_age = (now - track.first_seen).total_seconds()
        if track_age < cfg.min_track_seconds:
            return BehaviorAssessment(track.camera_id, track.track_id, now)

        body = median(d.bbox.y_max - d.bbox.y_min for d in hist) or 1.0

        # Gate 2 - resolution. Every measurement below is in body-heights, so when the body is a
        # handful of pixels the denominator is noise and so is the result. Pose keypoints on a
        # target this small are meaningless too.
        if body < cfg.min_body_pixels:
            return BehaviorAssessment(track.camera_id, track.track_id, now)

        window = [d for d in hist if (now - d.timestamp).total_seconds() <= cfg.window_seconds]
        observed = (hist[-1].timestamp - hist[0].timestamp).total_seconds()

        # Gate 3 - sampling density. A window held together by three detections four seconds
        # apart cannot tell bobbing from dropped frames.
        if observed > 0 and (len(hist) / observed) < cfg.min_sample_rate_hz:
            return BehaviorAssessment(track.camera_id, track.track_id, now)
        signals: list[DistressSignal] = []
        for fn in (self._stillness, self._bobbing, self._erratic, self._submersion):
            sig = fn(hist, window, body, now)
            if sig:
                signals.append(sig)
        # Pose is optional throughout: no estimator, or a track the estimator could not resolve,
        # yields no pose signals rather than a default-safe or default-dangerous assumption.
        if pose is not None:
            for fn in (self._vertical_in_water, self._arms_raised):
                sig = fn(pose, hist, window, body, now)
                if sig:
                    signals.append(sig)
        return BehaviorAssessment(track.camera_id, track.track_id, now, tuple(signals), observed)

    # -- pose helpers ------------------------------------------------------
    @staticmethod
    def _points(pose: PoseEstimate) -> dict[str, PoseKeypoint]:
        return {k.name: k for k in pose.keypoints}

    @staticmethod
    def _midpoint(a: PoseKeypoint | None, b: PoseKeypoint | None):
        """Mean of whichever of the pair is present; None when neither is."""
        have = [p for p in (a, b) if p is not None]
        if not have:
            return None
        return (sum(p.x for p in have) / len(have), sum(p.y for p in have) / len(have))

    # -- individual signals ----------------------------------------------
    def _stillness(self, hist, window, body, now):
        cfg = self.cfg
        span = (hist[-1].timestamp - hist[0].timestamp).total_seconds()
        if span < cfg.still_seconds * 0.9:
            return None
        xs = [d.bbox.center[0] for d in hist]
        ys = [d.bbox.center[1] for d in hist]
        spread = math.hypot(max(xs) - min(xs), max(ys) - min(ys)) / body
        if spread >= cfg.still_motion:
            return None
        conf = min(1.0, 0.5 + 0.5 * (1 - spread / cfg.still_motion))
        return DistressSignal(DistressSignalType.PROLONGED_STILLNESS, now, round(conf, 2),
                              f"moved {spread:.2f} body-heights in {span:.1f}s")

    def _bobbing(self, hist, window, body, now):
        cfg = self.cfg
        if len(window) < cfg.min_samples:
            return None
        ys = [d.bbox.center[1] / body for d in window]
        drift = abs(window[-1].bbox.center[0] - window[0].bbox.center[0]) / body
        if drift > cfg.bob_max_drift:
            return None
        reversals, direction, anchor = 0, 0, ys[0]
        for y in ys[1:]:
            delta = y - anchor
            if abs(delta) >= cfg.bob_amplitude:
                d = 1 if delta > 0 else -1
                if direction and d != direction:
                    reversals += 1
                direction, anchor = d, y
        if reversals < cfg.bob_min_reversals:
            return None
        conf = min(1.0, reversals / (2 * cfg.bob_min_reversals) + 0.4)
        return DistressSignal(DistressSignalType.VERTICAL_BOBBING, now, round(conf, 2),
                              f"{reversals} up/down reversals, drift {drift:.2f}")

    def _erratic(self, hist, window, body, now):
        cfg = self.cfg
        if len(window) < cfg.min_samples:
            return None
        vel = []
        for a, b in zip(window, window[1:]):
            dt = (b.timestamp - a.timestamp).total_seconds() or 1e-6
            vx = (b.bbox.center[0] - a.bbox.center[0]) / body / dt
            vy = (b.bbox.center[1] - a.bbox.center[1]) / body / dt
            if math.hypot(vx, vy) >= cfg.erratic_min_speed:
                vel.append(math.atan2(vy, vx))
        if len(vel) < cfg.min_samples - 1:
            return None
        sharp = sum(1 for a, b in zip(vel, vel[1:])
                    if abs((math.degrees(b - a) + 180) % 360 - 180) > cfg.erratic_turn_deg)
        share = sharp / (len(vel) - 1)
        if share < cfg.erratic_min_share:
            return None
        return DistressSignal(DistressSignalType.ERRATIC_MOVEMENT, now, round(min(1.0, share + 0.3), 2),
                              f"{share:.0%} sharp direction changes")

    def _submersion(self, hist, window, body, now):
        """Repeated partial disappearance *of the body*, measured by the box shrinking.

        Track dropouts used to count here as well, and that was wrong. On a populated beach the
        usual reason a person stops being detected for a few frames is that someone walked between
        them and the camera. Occlusion and submersion are identical if the only question asked is
        "is the box still there", so the highest-weighted signal in the system fired on ordinary
        crowding. Only the box collapsing while the track survives is counted now; a history gap
        is treated as missing data and the measurements across it are not trusted.
        """
        cfg = self.cfg
        shrink, small = 0, False
        for a, b in zip(window, window[1:]):
            if (b.timestamp - a.timestamp).total_seconds() > cfg.gap_seconds:
                # Discontinuity: reset rather than read a shrink across frames we never saw.
                small = False
                continue
            is_small = (b.bbox.y_max - b.bbox.y_min) < cfg.shrink_ratio * body
            if is_small and not small:
                shrink += 1
            small = is_small
        if shrink < cfg.submersion_min_count:
            return None
        return DistressSignal(DistressSignalType.REPEATED_SUBMERSION, now,
                              round(min(1.0, 0.4 + 0.2 * shrink), 2),
                              f"{shrink} partial submersions (box collapsed, track held)")

    # -- pose signals ------------------------------------------------------
    def _vertical_in_water(self, pose, hist, window, body, now):
        """Torso upright while making no headway.

        This is the single most useful discriminator available without training data. Swimming -
        front crawl, breaststroke, floating, body-surfing - puts the shoulder-hip axis roughly
        horizontal in the image. The instinctive drowning response puts it vertical, with the
        person effectively climbing an invisible ladder and going nowhere.

        The "going nowhere" half is essential: a person standing in shallow water, or treading
        water deliberately while chatting, is also vertical. Requiring near-zero drift over
        several seconds is what separates "upright" from "upright and in trouble", and it is
        still only evidence - the risk engine decides, not this function.
        """
        cfg = self.cfg
        pts = self._points(pose)
        shoulders = self._midpoint(pts.get("left_shoulder"), pts.get("right_shoulder"))
        hips = self._midpoint(pts.get("left_hip"), pts.get("right_hip"))
        if shoulders is None or hips is None:
            return None  # torso not visible - unknown, not safe

        dx, dy = hips[0] - shoulders[0], hips[1] - shoulders[1]
        length = math.hypot(dx, dy)
        if length < 1e-6:
            return None
        # 0 deg = perfectly vertical torso, 90 deg = horizontal (swimming).
        tilt = abs(math.degrees(math.atan2(abs(dx), abs(dy))))
        if tilt > cfg.vertical_max_tilt_deg:
            return None

        span = (hist[-1].timestamp - hist[0].timestamp).total_seconds()
        if span < cfg.vertical_seconds:
            return None
        xs = [d.bbox.center[0] for d in hist]
        ys = [d.bbox.center[1] for d in hist]
        drift = math.hypot(max(xs) - min(xs), max(ys) - min(ys)) / body
        if drift > cfg.vertical_max_drift:
            return None  # upright but travelling: wading or treading on purpose

        upright = 1 - (tilt / cfg.vertical_max_tilt_deg)
        conf = min(1.0, 0.45 + 0.45 * upright)
        return DistressSignal(DistressSignalType.VERTICAL_IN_WATER, now, round(conf, 2),
                              f"torso {tilt:.0f}deg from vertical, drifted {drift:.2f} body-heights "
                              f"in {span:.1f}s")

    def _arms_raised(self, pose, hist, window, body, now):
        """One or both wrists above the shoulder line.

        A recognised distress sign, and also what someone waving to a friend looks like - which is
        precisely why it is one weighted signal among several and never actionable alone. Measured
        against the shoulder line rather than the image, so it holds as the camera angle changes.
        """
        cfg = self.cfg
        pts = self._points(pose)
        shoulders = self._midpoint(pts.get("left_shoulder"), pts.get("right_shoulder"))
        if shoulders is None:
            return None
        head = self._midpoint(pts.get("nose"), pts.get("left_eye")) or shoulders
        # Head-to-shoulder distance is a scale that survives distance and partial submersion
        # better than the bbox, which the waterline crops.
        head_height = abs(shoulders[1] - head[1]) or (body * 0.15)

        raised = []
        for side in ("left", "right"):
            wrist = pts.get(f"{side}_wrist")
            if wrist is None:
                continue
            # Image y grows downward: a raised wrist sits at a SMALLER y than the shoulders.
            if (shoulders[1] - wrist.y) > cfg.arms_raised_margin * head_height:
                raised.append(side)
        if not raised:
            return None
        conf = 0.5 if len(raised) == 1 else 0.75
        return DistressSignal(DistressSignalType.ARMS_RAISED, now, conf,
                              f"{' and '.join(raised)} wrist above the shoulder line")
