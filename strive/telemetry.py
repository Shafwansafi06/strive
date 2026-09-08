"""LAT-01/LAT-02: per-stage timing and aggregation.

Timers use `time.perf_counter` and store one float per stage. The overhead is a
pair of clock reads per stage (sub-microsecond on CPython), which is why stages
can be left permanently on rather than gated behind a debug flag.

Nothing here allocates per sample or holds audio.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
from math import ceil
import time

# LAT-01 required stages, in pipeline order. Naming is fixed so aggregation across
# runs and hardware stays comparable; unused stages are simply absent, not zero.
STAGES = ("decode", "resample", "vad", "buffer_wait", "channel",
          "artifact", "session", "fusion", "api_push")


@dataclass
class StageTimer:
    """Collect per-stage milliseconds for one window."""
    ms: dict = field(default_factory=dict)

    @contextmanager
    def stage(self, name: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            self.ms[name] = self.ms.get(name, 0.) + (time.perf_counter() - start) * 1000

    def record(self, name: str, milliseconds: float) -> None:
        """Record a stage measured elsewhere (e.g. inside a worker thread)."""
        self.ms[name] = self.ms.get(name, 0.) + float(milliseconds)

    def total(self) -> float:
        return float(sum(self.ms.values()))

    def to_dict(self) -> dict:
        return {name: round(value, 3) for name, value in self.ms.items()}


def percentiles(values, points=(50, 95)) -> dict:
    """p50/p95/max/mean over a list of milliseconds, without a NumPy dependency.

    Uses the nearest-rank definition: the p-th percentile is the smallest value
    at or above which p% of the sample lies, i.e. element ceil(p/100 * N) of the
    sorted sample, 1-indexed. Returns explicit `None` for an empty sample rather
    than 0.0, which would read as "instant".
    """
    data = sorted(float(v) for v in values if v is not None)
    if not data:
        return {f"p{p}": None for p in points} | {"max": None, "mean": None, "count": 0}
    out = {}
    for p in points:
        rank = max(1, min(len(data), ceil(p / 100 * len(data))))
        out[f"p{p}"] = round(data[rank - 1], 3)
    out["max"] = round(data[-1], 3)
    out["mean"] = round(sum(data) / len(data), 3)
    out["count"] = len(data)
    return out


def aggregate_stages(events, key: str = "stage_ms") -> dict:
    """Per-stage p50/p95 across a list of risk events."""
    collected: dict[str, list] = {}
    for event in events:
        for name, value in (event.get(key) or {}).items():
            collected.setdefault(name, []).append(value)
    return {name: percentiles(values) for name, values in collected.items()}


def realtime_factor(audio_seconds: float, compute_seconds: float) -> float | None:
    """Audio seconds processed per wall-clock second. >1 keeps up with live audio."""
    if compute_seconds <= 0 or audio_seconds <= 0:
        return None
    return round(audio_seconds / compute_seconds, 3)
