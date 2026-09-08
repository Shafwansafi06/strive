"""EVAL-01 / LAT-03 acceptance: streaming WAV simulator and latency report."""
import json
import sys
import types
from pathlib import Path
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import stream_wav
from strive.audio import RATE


def make_args(**overrides):
    defaults = dict(wav=None, scenario="steady", seconds=12, max_seconds=600,
                    mode="accelerated", window=2.0, hop=1.0, frame=1.0,
                    multi_rate=False, language="auto", index=None, codec="none",
                    benchmark=False, events=None, json=None)
    return types.SimpleNamespace(**{**defaults, **overrides})


def run(**overrides):
    args = make_args(**overrides)
    audio, source = stream_wav.load_audio(args)
    call = stream_wav.build_call(args)
    try:
        events, pacing = stream_wav.stream(call, audio, args.mode, args.frame)
    finally:
        call.close()
    return events, stream_wav.summarize(events, len(audio) / RATE, pacing, args, source)


# --------------------------------------------------- EVAL-01 accelerated mode

def test_accelerated_mode_emits_one_event_per_hop():
    events, report = run(seconds=12, hop=1.0)
    assert len(events) == report["expected_windows"] == 11   # (12 - 2) / 1 + 1
    events, report = run(seconds=12, hop=0.5)
    assert len(events) == report["expected_windows"] == 21    # (12 - 2) / 0.5 + 1


def test_accelerated_mode_is_deterministic():
    """Same input, same events. Branch cadence runs on the audio timeline."""
    first, _ = run(seconds=12, hop=0.5, multi_rate=True)
    second, _ = run(seconds=12, hop=0.5, multi_rate=True)
    assert [e["s_risk"] for e in first] == [e["s_risk"] for e in second]
    assert [e["session_age_s"] for e in first] == [e["session_age_s"] for e in second]
    assert [e["reasons"] for e in first] == [e["reasons"] for e in second]


def test_events_carry_the_full_risk_schema():
    events, _ = run(seconds=12)
    for event in events:
        assert event["schema_version"] == "1.1"
        assert set(event["latency_ms"]) == {"compute", "queue", "end_to_end"}
        assert "channel" in event and "scheduler" in event
        assert event["demo_only"] is True
        # Events must be JSON-serializable for the JSONL output path.
        json.dumps(event, allow_nan=False)


def test_wav_input_round_trips(tmp_path):
    import soundfile as sf
    from strive.demo import scenario_audio
    wav = tmp_path / "call.wav"
    sf.write(wav, scenario_audio("steady", 10), RATE, subtype="PCM_16")
    events, report = run(wav=str(wav), scenario=None)
    assert report["dataset"] == "call.wav"
    assert len(events) == 9


# ------------------------------------------------------- EVAL-01 realtime mode

@pytest.mark.slow
def test_realtime_mode_paces_to_wall_clock():
    _, report = run(seconds=6, mode="realtime", frame=1.0)
    # 6 s of audio must take roughly 6 s of wall clock, not milliseconds.
    assert 5.0 < report["pacing"]["wall_clock_s"] < 9.0
    assert .6 < report["wall_clock_realtime_factor"] < 1.3
    assert report["pacing"]["late_frames"] == 0


def test_accelerated_mode_is_much_faster_than_realtime():
    _, report = run(seconds=12, mode="accelerated")
    assert report["pacing"]["wall_clock_s"] < 5.0
    assert report["realtime_factor"] > 1     # keeps up with live audio


# ------------------------------------------------------------ LAT-03 report

def test_report_has_percentiles_realtime_factor_and_stages():
    _, report = run(seconds=12, hop=0.5)
    for name in ("compute", "queue", "end_to_end"):
        values = report["latency_ms"][name]
        assert values["p50"] <= values["p95"] <= values["max"]
        assert values["count"] == report["windows"]
    assert report["realtime_factor"] > 0
    for stage in ("channel", "vad", "fusion"):
        assert report["stage_ms"][stage]["p95"] is not None


def test_report_captures_hardware_and_provenance():
    _, report = run(seconds=8)
    hardware = report["hardware"]
    assert hardware["python"] and hardware["platform"]
    assert hardware["device"] in ("cpu", "cuda")
    assert report["model_version"] and report["pipeline_version"]
    assert report["window_s"] == 2.0 and report["hop_s"] == 1.0
    # Same test must run on CPU or GPU; device is recorded, never assumed.
    assert "gpu" in hardware


def test_report_is_json_serializable_and_flags_budget():
    _, report = run(seconds=12, hop=0.5)
    json.dumps(report, allow_nan=False)
    assert report["budget_ms"] == 500.0
    assert report["windows_over_budget"] == 0


def test_multi_rate_reuse_is_reported():
    _, plain = run(seconds=12, hop=0.5, multi_rate=False)
    _, throttled = run(seconds=12, hop=0.5, multi_rate=True)
    assert plain["branch_reuse_windows"] == 0
    assert throttled["branch_reuse_windows"] > 0
    assert throttled["scheduler"]["branches"]["artifact"]["skips"] > 0


def test_empty_run_does_not_crash_the_report():
    """Audio shorter than one window yields no events and must still summarize."""
    events, report = run(seconds=1)
    assert events == []
    assert report["windows"] == 0
    assert report["latency_ms"]["compute"]["p50"] is None   # None, never 0.0
    assert report["realtime_factor"] is None
    json.dumps(report, allow_nan=False)
