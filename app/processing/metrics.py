"""Performance & response tracking (reference PDF §12 north-star metric: time from a distress signal to
an acknowledged human response). Computed on demand from the event log, live camera stats and jobs."""
from __future__ import annotations

from statistics import mean, median

from app.core.enums import EventStatus, JobStatus
from app.core.interfaces.clock import Clock
from app.core.interfaces.repositories import EventFilter, EventRepository, JobRepository
from app.processing.live import LiveFrameStore


def _stats(values: list[float]) -> dict:
    if not values:
        return {"count": 0, "mean_s": None, "median_s": None, "p90_s": None, "max_s": None}
    v = sorted(values)
    return {"count": len(v), "mean_s": round(mean(v), 1), "median_s": round(median(v), 1),
            "p90_s": round(v[min(len(v) - 1, int(0.9 * len(v)))], 1), "max_s": round(v[-1], 1)}


class MetricsService:
    def __init__(self, events: EventRepository, jobs: JobRepository, live: LiveFrameStore, clock: Clock) -> None:
        self._events, self._jobs, self._live, self._clock = events, jobs, live, clock

    def snapshot(self) -> dict:
        now = self._clock.now()
        events = self._events.list(EventFilter(limit=1000))
        by_status = {s.value: 0 for s in EventStatus}
        ack_latency, signal_counts, per_camera = [], {}, {}
        demo = 0
        for e in events:
            by_status[e.status.value] += 1
            per_camera[e.camera_id] = per_camera.get(e.camera_id, 0) + 1
            if (e.reason or "").startswith("DEMO"):
                demo += 1
            if e.acknowledgement:
                ack_latency.append((e.acknowledgement.at - e.created_at).total_seconds())
            for s in e.distress_signals:
                signal_counts[s.value] = signal_counts.get(s.value, 0) + 1
        closed = by_status["resolved"] + by_status["false_alarm"]
        live = [s for s in self._live.all() if self._live.is_online(s.camera_id, now)]
        jobs = [j for j in self._jobs.list(200) if j.status is JobStatus.COMPLETED]
        return {
            "generated_at": now.isoformat(),
            "events": {"total": len(events), "by_status": by_status, "per_camera": per_camera,
                       "active": by_status["pending"] + by_status["acknowledged"] + by_status["escalated"],
                       "demo_events": demo, "signals": signal_counts,
                       "false_alarm_rate": round(by_status["false_alarm"] / closed, 3) if closed else None},
            "response": {"time_to_ack": _stats(ack_latency),
                         "escalated_share": round(sum(1 for e in events if e.escalation_level > 0) / len(events), 3) if events else None},
            "cameras": {"online": len(live), "people_now": sum(int(s.stats.get("people", 0)) for s in live),
                        "fps": {s.camera_id: s.stats.get("fps") for s in live},
                        "latency_ms": {s.camera_id: s.stats.get("pipeline_ms") for s in live}},
            "jobs": {"completed": len(jobs),
                     "avg_pipeline_fps": round(mean(j.summary.get("pipeline_fps", 0) for j in jobs), 2) if jobs else None,
                     "frames_processed": sum(int(j.summary.get("frames_processed", 0)) for j in jobs)},
        }
