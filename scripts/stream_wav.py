"""EVAL-01 + LAT-03: stream a WAV as if it were a live call, and benchmark latency.

Two pacing modes:

  --mode accelerated   feed as fast as the machine allows. Deterministic: branch
                       cadence runs on the audio timeline, so the emitted events
                       are identical run to run. Use this for benchmarks and CI.

  --mode realtime      sleep between frames so audio arrives at 1x wall clock,
                       the way a live call does. Use this to observe queue delay
                       and backpressure. Not deterministic.

Examples:

  python -E scripts/stream_wav.py --scenario switch --mode accelerated
  python -E scripts/stream_wav.py --wav call.wav --mode realtime --events out.jsonl
  python -E scripts/stream_wav.py --scenario steady --benchmark --hop 0.5 --json bench.json
"""
import argparse
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from strive.audio import RATE, decode
from strive.config import Settings
from strive.demo import SCENARIOS, make_demo_index, scenario_audio
from strive.engine import Call
from strive.features import DSPExtractor
from strive.retrieval import ReferenceIndex
from strive.telemetry import aggregate_stages, percentiles, realtime_factor

# A frame is only "late" if it misses its slot by more than this.
LATE_TOLERANCE_S = 0.001


def git_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, timeout=10,
                             cwd=Path(__file__).resolve().parents[1])
        return out.stdout.decode().strip() or None
    except Exception:
        return None


def hardware() -> dict:
    """LAT-03: capture enough environment to make a result reproducible."""
    info = {"platform": platform.platform(), "machine": platform.machine(),
            "processor": platform.processor() or None, "python": platform.python_version(),
            "cpu_count": None, "device": "cpu", "gpu": None}
    try:
        import os
        info["cpu_count"] = os.cpu_count()
    except Exception:
        pass
    try:  # Only if the research extras are installed; never a hard dependency.
        import torch
        if torch.cuda.is_available():
            info["device"] = "cuda"
            info["gpu"] = torch.cuda.get_device_name(0)
        info["torch"] = torch.__version__
    except Exception:
        pass
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    info["processor"] = line.split(":", 1)[1].strip()
                    break
    except Exception:
        pass
    return info


def load_audio(args) -> tuple[np.ndarray, str]:
    if args.wav:
        return decode(Path(args.wav).read_bytes(), max_s=args.max_seconds), Path(args.wav).name
    return scenario_audio(args.scenario, args.seconds), f"scenario:{args.scenario}"


def build_call(args) -> Call:
    settings = Settings(window_s=args.window, stride_s=args.hop, multi_rate=args.multi_rate,
                        audit_path=":memory:")
    extractor = DSPExtractor()
    index = make_demo_index() if not args.index else ReferenceIndex.load(args.index)
    return Call(settings, extractor, index, language=args.language, source="stream_simulator")


def stream(call: Call, audio: np.ndarray, mode: str, frame_s: float = 1.0) -> tuple[list[dict], dict]:
    """Feed `audio` through `call` in `frame_s` frames. Returns events and pacing stats."""
    frame = round(frame_s * RATE)
    events, late_frames, max_late_ms = [], 0, 0.
    started = time.perf_counter()
    for index, offset in enumerate(range(0, len(audio), frame)):
        if mode == "realtime":
            # Frame i should arrive at t = i * frame_s. Sleep only if we are early.
            target = started + index * frame_s
            delay = target - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            elif delay < -LATE_TOLERANCE_S:
                # Only real lateness counts; sub-millisecond drift is scheduler noise.
                late_frames += 1
                max_late_ms = max(max_late_ms, -delay * 1000)
        events.extend(call.feed(audio[offset:offset + frame], index))
    wall_s = time.perf_counter() - started
    return events, {"wall_clock_s": round(wall_s, 4), "late_frames": late_frames,
                    "max_lateness_ms": round(max_late_ms, 3), "frames": index + 1}


def summarize(events: list[dict], audio_s: float, pacing: dict, args, source: str) -> dict:
    """LAT-03 report: p50/p95/max, realtime factor, per-stage breakdown."""
    compute = [e["latency_ms"]["compute"] for e in events]
    queue = [e["latency_ms"]["queue"] for e in events]
    end_to_end = [e["latency_ms"]["end_to_end"] for e in events]
    compute_s = sum(compute) / 1000
    return {
        "run_id": f"{int(time.time())}-{args.mode}-{args.window:g}s-{args.hop:g}s",
        "git_commit": git_commit(),
        "hardware": hardware(),
        "mode": "demo",
        "pacing_mode": args.mode,
        "dataset": source,
        "codec": args.codec,
        "window_s": args.window,
        "hop_s": args.hop,
        "multi_rate": args.multi_rate,
        "model_version": events[0]["model_version"] if events else None,
        "pipeline_version": events[0]["pipeline_version"] if events else None,
        "schema_version": events[0]["schema_version"] if events else None,
        "demo_only": events[0]["demo_only"] if events else None,
        "audio_seconds": round(audio_s, 3),
        "windows": len(events),
        "expected_windows": max(0, int((audio_s - args.window) / args.hop) + 1),
        "latency_ms": {"compute": percentiles(compute), "queue": percentiles(queue),
                       "end_to_end": percentiles(end_to_end)},
        "stage_ms": aggregate_stages(events),
        "realtime_factor": realtime_factor(audio_s, compute_s),
        "wall_clock_realtime_factor": realtime_factor(audio_s, pacing["wall_clock_s"]),
        "pacing": pacing,
        "budget_ms": round(args.hop * 1000, 3),
        "windows_over_budget": sum("COMPUTE_EXCEEDS_STRIDE" in e["reasons"] for e in events),
        "branch_reuse_windows": sum("BRANCH_RESULT_REUSED" in e["reasons"] for e in events),
        "scheduler": events[-1]["scheduler"] if events else None,
        "measurement_note": ("Wall-clock CPU measurement of the DSP surrogate on the hardware "
                             "above. Excludes network transport and browser capture. Not a "
                             "detection metric and not a production real-time claim."),
    }


def print_report(report: dict) -> None:
    hw = report["hardware"]
    print(f"\nSTRIVE latency benchmark  ({report['run_id']})")
    print(f"  commit      {report['git_commit'] or 'unknown'}")
    print(f"  hardware    {hw['processor'] or hw['machine']}, {hw['cpu_count']} cores, device={hw['device']}"
          + (f", gpu={hw['gpu']}" if hw["gpu"] else ""))
    print(f"  python      {hw['python']}")
    print(f"  dataset     {report['dataset']}  codec={report['codec']}")
    print(f"  geometry    window {report['window_s']}s / hop {report['hop_s']}s"
          f"   multi_rate={report['multi_rate']}")
    print(f"  windows     {report['windows']} (expected {report['expected_windows']})"
          f"   audio {report['audio_seconds']}s")

    print(f"\n  {'latency':<12}{'p50':>9}{'p95':>9}{'max':>9}{'mean':>9}")
    for name, values in report["latency_ms"].items():
        print(f"  {name:<12}{values['p50']:>9}{values['p95']:>9}{values['max']:>9}{values['mean']:>9}")

    print(f"\n  {'stage':<12}{'p50':>9}{'p95':>9}{'max':>9}{'n':>7}")
    for name, values in sorted(report["stage_ms"].items(), key=lambda kv: -(kv[1]["p50"] or 0)):
        print(f"  {name:<12}{values['p50']:>9}{values['p95']:>9}{values['max']:>9}{values['count']:>7}")

    print(f"\n  realtime factor (compute)     {report['realtime_factor']}x")
    print(f"  realtime factor (wall clock)  {report['wall_clock_realtime_factor']}x")
    print(f"  budget {report['budget_ms']} ms/hop   over budget: {report['windows_over_budget']}"
          f"   reused branch: {report['branch_reuse_windows']}")
    if report["pacing"]["late_frames"]:
        print(f"  LATE FRAMES {report['pacing']['late_frames']}"
              f" (worst {report['pacing']['max_lateness_ms']} ms) - could not keep up")
    print(f"\n  {report['measurement_note']}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--wav", help="path to a 16 kHz-convertible audio file")
    source.add_argument("--scenario", choices=sorted(SCENARIOS), default="steady")
    parser.add_argument("--seconds", type=int, default=40, help="scenario length")
    parser.add_argument("--max-seconds", type=int, default=600)
    parser.add_argument("--mode", choices=["accelerated", "realtime"], default="accelerated")
    parser.add_argument("--window", type=float, default=2.0)
    parser.add_argument("--hop", type=float, default=1.0)
    parser.add_argument("--frame", type=float, default=1.0, help="transport frame size in seconds")
    parser.add_argument("--multi-rate", action="store_true", help="enable SCH-03 branch cadences")
    parser.add_argument("--language", default="auto")
    parser.add_argument("--index", help="reference index .npz (defaults to the demo fixture index)")
    parser.add_argument("--codec", default="none", help="codec label recorded in the report")
    parser.add_argument("--benchmark", action="store_true", help="print the LAT-03 report")
    parser.add_argument("--events", help="write one risk event per line as JSONL")
    parser.add_argument("--json", help="write the benchmark report as JSON")
    args = parser.parse_args()

    audio, source_name = load_audio(args)
    call = build_call(args)
    try:
        events, pacing = stream(call, audio, args.mode, args.frame)
    finally:
        call.close()

    if args.events:
        target = Path(args.events)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event, allow_nan=False) + "\n")
        print(f"Wrote {len(events)} risk events to {target}")

    report = summarize(events, len(audio) / RATE, pacing, args, source_name)
    if args.json:
        target = Path(args.json)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2, allow_nan=False))
        print(f"Wrote benchmark report to {target}")
    if args.benchmark or not (args.events or args.json):
        print_report(report)


if __name__ == "__main__":
    main()
