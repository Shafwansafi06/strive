"""SCH-01/02/03: run branches at different rates without blocking fusion.

Fusion must be able to refresh every hop even when an expensive branch cannot.
This module decides *when* a branch is due and holds its most recent result with
an explicit expiry. It does not own threads: the caller drives it, so the policy
is testable without a runtime and there are no branch-specific sleep loops.

A result that is missing and a result that is stale are different states, and
neither is a zero. Both keep `available=False` so fusion masks them.
"""
from dataclasses import dataclass, field
import threading
import time

from .branches import BranchResult

# SCH-01. Milliseconds between runs of each branch. A branch whose cadence is at
# or below the hop runs every window; a slower one reuses its last result until
# it goes stale. Overridden per deployment through Settings.branch_cadence_ms.
DEFAULT_CADENCE_MS = {
    "channel": 500,
    "prosody": 500,
    "artifact": 1000,
    "session": 2000,
    "identity": 3000,
    "fusion": 500,
}

# How long a result stays usable after it was produced. Defaults to three
# cadences: long enough to survive one skipped run, short enough that a dead
# branch stops contributing instead of silently freezing the risk score.
STALE_MULTIPLIER = 3


@dataclass
class BranchState:
    """SCH-02. One branch's latest result plus its expiry."""
    result: BranchResult | None = None
    updated_at: float | None = None
    stale_after_ms: float = 3000.
    last_started: float | None = None
    runs: int = 0
    skips: int = 0
    failures: int = 0

    def is_missing(self) -> bool:
        """No result has ever been produced."""
        return self.result is None or self.updated_at is None

    def is_stale(self, now: float | None = None) -> bool:
        if self.is_missing():
            return False  # Missing is its own state, not staleness.
        now = time.monotonic() if now is None else now
        return (now - self.updated_at) * 1000 > self.stale_after_ms

    def age_ms(self, now: float | None = None) -> float | None:
        if self.is_missing():
            return None
        now = time.monotonic() if now is None else now
        return round((now - self.updated_at) * 1000, 3)

    def usable(self, now: float | None = None) -> BranchResult | None:
        """The result fusion may use, or None when missing or expired."""
        if self.is_missing() or self.is_stale(now):
            return None
        return self.result


class MultiRateScheduler:
    """Decides which branches are due this window and caches their results.

    Thread-safe: `Call` scores windows on a worker thread while the API may read
    a snapshot for telemetry.
    """

    def __init__(self, cadence_ms: dict | None = None, stale_multiplier: int = STALE_MULTIPLIER) -> None:
        self.cadence = dict(DEFAULT_CADENCE_MS, **(cadence_ms or {}))
        for name, value in self.cadence.items():
            if not isinstance(value, (int, float)) or value <= 0:
                raise ValueError(f"Cadence for {name} must be a positive number of milliseconds")
        self.lock = threading.RLock()
        self.states = {name: BranchState(stale_after_ms=ms * stale_multiplier)
                       for name, ms in self.cadence.items()}
        self.queue_delay_ms = 0.

    def due(self, name: str, now: float | None = None) -> bool:
        """True when this branch has not run within its cadence."""
        now = time.monotonic() if now is None else now
        with self.lock:
            state = self.states.get(name)
            if state is None:
                return True  # An unregistered branch is never throttled.
            if state.last_started is None:
                return True
            return (now - state.last_started) * 1000 >= self.cadence[name] - 1e-9

    def begin(self, name: str, now: float | None = None) -> None:
        """Mark a branch as started, so cadence is measured from the start."""
        now = time.monotonic() if now is None else now
        with self.lock:
            state = self.states.setdefault(name, BranchState())
            state.last_started = now
            state.runs += 1

    def skip(self, name: str) -> None:
        with self.lock:
            self.states.setdefault(name, BranchState()).skips += 1

    def publish(self, name: str, result: BranchResult, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self.lock:
            state = self.states.setdefault(name, BranchState())
            state.result = result
            state.updated_at = now
            if not result.available:
                state.failures += 1

    def fail(self, name: str, reason: str, now: float | None = None) -> None:
        """SCH-03: a branch exception must not kill the call session.

        The branch publishes explicit unavailability and the stream continues.
        """
        self.publish(name, BranchResult.unavailable(name, reason), now)

    def snapshot(self, now: float | None = None) -> dict[str, BranchResult]:
        """Current usable results. Missing and stale branches are unavailable."""
        now = time.monotonic() if now is None else now
        out = {}
        with self.lock:
            for name, state in self.states.items():
                usable = state.usable(now)
                if usable is not None:
                    out[name] = usable
                elif state.is_missing():
                    out[name] = BranchResult.unavailable(name, "BRANCH_NOT_YET_RUN")
                else:
                    out[name] = BranchResult.unavailable(
                        name, "BRANCH_STALE", age_ms=state.age_ms(now),
                        stale_after_ms=state.stale_after_ms)
        return out

    def telemetry(self, now: float | None = None) -> dict:
        """SCH-03: expose queue delay and per-branch run/skip/failure counters."""
        now = time.monotonic() if now is None else now
        with self.lock:
            return {"queue_delay_ms": round(self.queue_delay_ms, 3),
                    "cadence_ms": dict(self.cadence),
                    "branches": {name: {"runs": s.runs, "skips": s.skips, "failures": s.failures,
                                        "age_ms": s.age_ms(now), "stale": s.is_stale(now),
                                        "missing": s.is_missing()}
                                 for name, s in self.states.items()}}

    def record_queue_delay(self, milliseconds: float) -> None:
        with self.lock:
            self.queue_delay_ms = max(0., float(milliseconds))

    def reset(self) -> None:
        """Drop every cached result, e.g. after a known audio gap."""
        with self.lock:
            for state in self.states.values():
                state.result = None
                state.updated_at = None
                state.last_started = None
