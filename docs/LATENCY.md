# REAL-TIME PERFORMANCE — instrumentation, scheduling and measured latency

Tickets: LAT-01 (stage timers), LAT-02 (latency events), LAT-03 (benchmark command),
SCH-01/02/03 (multi-rate scheduler), EVAL-01 (streaming simulator).

## LAT-01 — per-stage timers

`strive/telemetry.py`. `StageTimer.stage(name)` is a context manager that records
wall-clock milliseconds per stage and accumulates repeated entries. A stage that raises
is still recorded, so failed work never disappears from the budget.

Measured overhead: **< 20 µs per stage** (asserted by
`tests/test_telemetry.py::test_timer_overhead_is_negligible`). Cheap enough to leave on
permanently rather than hiding behind a debug flag.

Declared stage names (`telemetry.STAGES`): `decode`, `resample`, `vad`, `buffer_wait`,
`channel`, `artifact`, `session`, `fusion`, `api_push`. A stage that did not run is
**absent**, not zero.

`percentiles()` uses nearest-rank — the p-th percentile is element `ceil(p/100 * N)` of
the sorted sample, 1-indexed. It returns `None` for an empty sample rather than `0.0`,
which would read as "instant".

## LAT-02 — latency on every risk event

**Breaking change, `schema_version` bumped `1.0` → `1.1`.** `latency_ms` was a float; it
is now an object:

```json
"latency_ms": { "compute": 23.29, "queue": 0.09, "end_to_end": 23.38 }
```

| Field | Meaning |
|---|---|
| `compute` | Time spent scoring this window. |
| `queue` | How long the completed window waited before compute began, measured from `Window.enqueued`. Near zero while capture and inference share a thread; becomes real once AUD-04 separates them. |
| `end_to_end` | `compute + queue`, derived from the rounded parts so the three always agree. |

Updated consumers: `strive/api.py` metrics, `web/app.js`, `scripts/build_demo.py`,
`scripts/evaluate.py`, `tests/test_research_smoke.py`. `/metrics` gained
`strive_queue_ms_sum`.

`COMPUTE_EXCEEDS_STRIDE` now fires against **`stride_s * 1000`**, not a hard-coded
1000 ms. At a 0.5 s hop the real-time budget is 500 ms, and the reason code follows it.

## SCH-01/02/03 — multi-rate scheduler

`strive/scheduler.py`. Off by default (`Settings.multi_rate = False`), so existing
behaviour is unchanged unless enabled.

Default cadences in milliseconds (`DEFAULT_CADENCE_MS`, overridable via
`Settings.branch_cadence_ms`):

```
channel 500   prosody 500   artifact 1000   session 2000   identity 3000   fusion 500
```

**Cadence runs on the audio timeline, not wall clock.** This is the key design decision:
an accelerated offline replay schedules branches exactly as a live call would, so
benchmarks and ablations are reproducible. Wall-clock cadence would have skipped almost
every branch during a fast offline run.

`BranchState` (SCH-02) separates three states that must never be confused:

| State | `available` | `score` | Reason code |
|---|---|---|---|
| Never ran | `False` | `None` | `BRANCH_NOT_YET_RUN` |
| Ran, still fresh | `True` | value | — |
| Ran, expired | `False` | `None` | `BRANCH_STALE` |

Results expire after **3 cadences** — long enough to survive one skipped run, short
enough that a dead branch stops contributing instead of silently freezing the risk
score. A skipped-but-fresh window reuses the cached result and adds
`BRANCH_RESULT_REUSED` to its reasons.

A branch exception publishes explicit unavailability and the call continues
(SCH-03 acceptance). The scheduler is `RLock`-guarded and exercised by a 6-thread
race test.

Per-event telemetry under `event["scheduler"]`: `queue_delay_ms`, `cadence_ms`, and
per-branch `runs` / `skips` / `failures` / `age_ms` / `stale` / `missing`.

## EVAL-01 — streaming simulator

`scripts/stream_wav.py` streams a WAV or a built-in scenario as if it were a live call.

```bash
# deterministic, as fast as the machine allows
python -E scripts/stream_wav.py --scenario switch --mode accelerated --hop 0.5

# paced to 1x wall clock, to observe queue delay
python -E scripts/stream_wav.py --wav call.wav --mode realtime --events out.jsonl

# LAT-03 report
python -E scripts/stream_wav.py --scenario switch --hop 0.5 --multi-rate \
       --benchmark --json evidence/latency-benchmark.json
```

`--mode accelerated` is deterministic: identical scores, ages and reason codes across
runs (asserted in `tests/test_stream_simulator.py`). `--mode realtime` paces frames to
their slot and reports `late_frames` when the machine cannot keep up (tolerance 1 ms).

## LAT-03 — measured results

Hardware: 12th Gen Intel Core i5-1235U, 12 cores, **CPU only, no GPU**. Python 3.12.3.
Commit `f1f1dfa`. DSP surrogate extractor, 48-vector fixture index. Scenario `switch`,
40 s. Full report: `evidence/latency-benchmark.json`.

| Window / hop | multi-rate | Windows | p50 e2e (ms) | p95 e2e (ms) | Realtime factor | Reused |
|---|---|---:|---:|---:|---:|---:|
| 2.0 s / 1.0 s | off | 39 | 15.46 | 18.89 | 64.3× | 0 |
| 2.0 s / 0.5 s | off | 77 | 21.77 | 36.39 | 32.7× | 0 |
| **2.0 s / 0.5 s** | **on** | 77 | **17.06** | **22.92** | **54.4×** | 38 |
| 4.0 s / 0.5 s | on | 73 | 31.00 | 39.85 | 31.8× | 36 |
| 4.0 s / 1.0 s | off | 37 | 28.49 | 34.16 | 37.1× | 0 |

Per-stage breakdown at 2 s / 0.5 s with multi-rate on:

| Stage | p50 (ms) | p95 (ms) | Runs |
|---|---:|---:|---:|
| artifact | 17.18 | 18.57 | 39 |
| channel | 5.33 | 6.10 | 77 |
| session | 2.48 | 3.60 | 39 |
| vad | 0.11 | 0.15 | 77 |
| fusion | 0.05 | 0.10 | 77 |

### Findings

1. **Halving the hop roughly halves throughput headroom** (64.3× → 32.7×) because the
   artifact branch runs twice as often for the same audio.
2. **Multi-rate recovers most of it.** At 2 s / 0.5 s, enabling SCH-03 raises the
   realtime factor 32.7× → 54.4× (**1.67×**) and drops p95 end-to-end 36.4 → 22.9 ms,
   while still emitting all 77 windows. The artifact branch ran 39 times instead of 77.
3. **Nothing exceeded budget.** Zero `COMPUTE_EXCEEDS_STRIDE` in any geometry; p95 stays
   under 40 ms against a 500 ms hop budget.
4. **Channel intelligence costs ~5 ms/window** and runs every hop, as CH cadence
   requires.

### What these numbers are not

Wall-clock CPU measurements of the **DSP surrogate** against a 48-vector fixture index.
They exclude neural inference, large-index retrieval, network transport and browser
capture. They are **not** detection metrics, and they cannot substantiate a production
or GPU real-time claim. Research-mode latency depends entirely on the actual models and
hardware and has not been measured — no weights are installed.

The benchmark records `device` and `gpu` from `torch` when the research extras are
present, so the same command produces a comparable report on CPU or GPU.

## AUD-04 — inference stalls cannot block ingestion

`strive/capture.py`. `Call` now has two paths joined by a bounded queue of completed
windows:

| Method | Path | Cost |
|---|---|---|
| `Call.ingest(samples, sequence)` | capture | Validate, buffer, enqueue. **Never touches a model.** Returns the number of windows dropped. |
| `Call.drain(limit=None)` | inference | Scores queued windows, oldest first. |
| `Call.feed(samples, sequence)` | both | `ingest` then `drain`. Unchanged signature, so the REST contract and every existing caller still work. |

Measured: ingesting 6 frames against a deliberately 200 ms-per-window extractor takes
**< 200 ms total with zero model calls**
(`tests/test_capture.py::test_ingest_never_runs_a_model`).

### Backpressure strategy

Capacity is `Settings.capture_queue_windows`, default **8 windows** — 4 s of audio at a
0.5 s hop. On overflow the **oldest** window is discarded and counted.

Dropping the oldest rather than the newest is deliberate. A live risk score is only
useful if it describes what the caller is saying now. Discarding the newest window would
freeze the dashboard in the past while the backlog drains — exactly the failure the
score exists to catch. Dropping the oldest keeps the view current and makes the loss
explicit instead of letting latency grow without bound.

Ingestion never blocks and never raises on overflow: a stalled model degrades the
evidence rate, it does not break the call.

### Reported loss

A drop is a real break in the audio the analyzer saw, so the next scored window:

- adds `CAPTURE_QUEUE_OVERFLOW` to `reasons` (once — the flag is consumed on read),
- carries `dropped_windows` with the count,
- **resets channel continuity**, so the gap is not scored as a splice in the source.
  Without this, every overflow would manufacture a false `discontinuity_score` spike.

Per-event telemetry under `event["capture"]`: `capacity`, `windows_queued`,
`windows_scored`, `windows_dropped`, `frames_ingested`, `overflow_events`, `max_depth`,
`current_depth`. `/metrics` gained `strive_dropped_windows_total`.

### Scope note

The WebSocket wire protocol is **unchanged** — still one `{type: "events", sequence,
events}` reply per frame, now with a `queued` depth field. Moving to fully asynchronous
event delivery would break the dashboard and every existing client, which is beyond what
AUD-04 asks for. The separation the ticket requires is in the engine, where it is tested;
deploying it as independent capture and inference tasks is a follow-up once a client can
handle out-of-band events.

## Not yet done

- No research-mode latency numbers, pending models and a GPU.
- Fully asynchronous WebSocket event delivery (see scope note above).
