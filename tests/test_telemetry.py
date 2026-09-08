"""LAT-01 / LAT-02 acceptance: per-stage timers and end-to-end latency events."""
import time
import numpy as np
import pytest
from strive.audio import RATE
from strive.config import Settings
from strive.demo import scenario_audio
from strive.engine import Call
from strive.features import DSPExtractor
from strive.telemetry import (STAGES, StageTimer, aggregate_stages, percentiles,
                              realtime_factor)


# ------------------------------------------------------------ LAT-01 timers

def test_stage_timer_measures_and_accumulates():
    timer = StageTimer()
    with timer.stage("artifact"):
        time.sleep(.01)
    with timer.stage("artifact"):
        time.sleep(.01)
    with timer.stage("fusion"):
        pass
    assert timer.ms["artifact"] >= 18          # both passes accumulated
    assert timer.ms["fusion"] < 5
    assert timer.total() == pytest.approx(sum(timer.ms.values()))
    assert set(timer.to_dict()) == {"artifact", "fusion"}


def test_stage_timer_records_on_exception():
    timer = StageTimer()
    with pytest.raises(RuntimeError):
        with timer.stage("artifact"):
            raise RuntimeError("branch failed")
    # A failed stage still cost wall-clock time; it must not vanish from the budget.
    assert "artifact" in timer.ms


def test_timer_overhead_is_negligible():
    """LAT-01: timers must be cheap enough to leave permanently enabled."""
    timer = StageTimer()
    started = time.perf_counter()
    for _ in range(10_000):
        with timer.stage("fusion"):
            pass
    per_call_us = (time.perf_counter() - started) / 10_000 * 1e6
    assert per_call_us < 20, f"{per_call_us:.2f} us per stage is too expensive"


def test_record_accepts_measurements_from_worker_threads():
    timer = StageTimer()
    timer.record("session", 4.5)
    timer.record("session", 1.5)
    assert timer.ms["session"] == 6.0


def test_required_stage_names_are_declared():
    for name in ("decode", "resample", "vad", "buffer_wait", "channel",
                 "artifact", "session", "fusion", "api_push"):
        assert name in STAGES


# -------------------------------------------------------- LAT-01 aggregation

def test_percentiles_p50_p95_max():
    values = list(range(1, 101))          # 1..100 ms
    out = percentiles(values)
    assert out["p50"] == 50
    assert out["p95"] == 95
    assert out["max"] == 100
    assert out["count"] == 100
    assert out["mean"] == pytest.approx(50.5)


def test_percentiles_on_empty_sample_is_none_not_zero():
    out = percentiles([])
    assert out["p50"] is None and out["p95"] is None and out["max"] is None
    assert out["count"] == 0


def test_percentiles_ignore_missing_values():
    assert percentiles([1., None, 3.])["count"] == 2


def test_aggregate_stages_across_events():
    events = [{"stage_ms": {"artifact": 10., "fusion": 1.}},
              {"stage_ms": {"artifact": 20., "fusion": 2.}},
              {"stage_ms": {"artifact": 30.}}]
    out = aggregate_stages(events)
    assert out["artifact"]["count"] == 3
    assert out["fusion"]["count"] == 2
    assert out["artifact"]["max"] == 30.


def test_realtime_factor():
    assert realtime_factor(10., 2.) == 5.
    assert realtime_factor(10., 0.) is None
    assert realtime_factor(0., 1.) is None


# ---------------------------------------------------- LAT-02 latency events

def run_call(index, hop_s=1.0, seconds=12, scenario="steady"):
    call = Call(Settings(window_s=2.0, stride_s=hop_s), DSPExtractor(), index)
    audio = scenario_audio(scenario, seconds)
    events = []
    for i, start in enumerate(range(0, len(audio), RATE)):
        events.extend(call.feed(audio[start:start + RATE], i))
    call.close()
    return events


def test_event_exposes_compute_queue_and_end_to_end(index):
    for event in run_call(index):
        latency = event["latency_ms"]
        assert set(latency) == {"compute", "queue", "end_to_end"}
        assert all(isinstance(v, float) for v in latency.values())
        assert latency["compute"] >= 0 and latency["queue"] >= 0
        assert latency["end_to_end"] == pytest.approx(
            latency["compute"] + latency["queue"], abs=1e-3)


def test_schema_version_bumped_for_latency_change(index):
    assert all(e["schema_version"] == "1.1" for e in run_call(index))


def test_stage_breakdown_is_present_and_bounded_by_compute(index):
    for event in run_call(index):
        stages = event["stage_ms"]
        assert "vad" in stages and "channel" in stages and "fusion" in stages
        # Stages are nested inside the compute span, so they cannot exceed it.
        assert sum(stages.values()) <= event["latency_ms"]["compute"] + 1e-6


def test_active_windows_report_artifact_and_session_stages(index):
    events = run_call(index)
    active = [e for e in events if "LOW_AUDIO_ACTIVITY" not in e["reasons"]]
    assert active, "fixture should produce active windows"
    for event in active:
        assert event["stage_ms"]["artifact"] > 0
        assert event["stage_ms"]["session"] >= 0


def test_silence_skips_branch_stages_but_still_times_channel(index):
    events = run_call(index, scenario="silence")
    quiet = [e for e in events if "LOW_AUDIO_ACTIVITY" in e["reasons"]]
    assert quiet
    for event in quiet:
        assert "artifact" not in event["stage_ms"]
        assert event["stage_ms"]["channel"] >= 0


def test_overrun_reason_follows_the_configured_hop(index):
    """COMPUTE_EXCEEDS_STRIDE is measured against stride_s, not a fixed 1 s."""
    class Slow(DSPExtractor):
        def extract(self, x):
            time.sleep(.05)
            return super().extract(x)

    call = Call(Settings(window_s=2.0, stride_s=0.5), Slow(), index)
    audio = scenario_audio("steady", 6)
    events = []
    for i, start in enumerate(range(0, len(audio), RATE)):
        events.extend(call.feed(audio[start:start + RATE], i))
    call.close()
    # 50 ms of forced work is well under a 500 ms hop, so nothing should trip.
    assert not any("COMPUTE_EXCEEDS_STRIDE" in e["reasons"] for e in events)
    assert max(e["latency_ms"]["compute"] for e in events) >= 50


def test_p50_p95_aggregate_from_a_real_run(index):
    events = run_call(index, hop_s=0.5, seconds=16)
    end_to_end = percentiles([e["latency_ms"]["end_to_end"] for e in events])
    assert end_to_end["count"] == len(events)
    assert end_to_end["p50"] <= end_to_end["p95"] <= end_to_end["max"]
    stages = aggregate_stages(events)
    assert stages["channel"]["p95"] is not None
