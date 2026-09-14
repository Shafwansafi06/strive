# SIH presentation audit

Audit base: `f287410` (remote main, Audio and Codec code changes). Local main
was clean at `f1f1dfa`; fetched and created `codex/sih-presentation-ready` from
remote main. No user changes were overwritten.

## Existing implementation

FastAPI REST/WebSocket service; vanilla dashboard and AudioWorklet; memory audio
decode/resampling; configurable windows; bounded capture queue; channel metrics;
audio-time scheduler; FAISS reference and transient session indexes; gated
bootstrap; adjacent-segment coherence; availability masking and EMA; separate
context/decision policy; allow-listed SQLite audit; frozen research adapters,
export/sealing/index/evaluation tools; deterministic procedural fixtures and
portable replay. Existing codec, stream and latency tests must be preserved.

## Baseline execution on presentation laptop

Windows, Python 3.12.13 (uv-managed), Node v24.12.0. Installed the exact demo
dependency lock into `.venv` successfully. Executed:

- `node --check web/app.js`: exit 0.
- `node --check web/pcm-worklet.js`: exit 0.
- `node tests/audio_worklet.cjs`: PASS at 16000, 44100 and 48000 Hz.
- Python pytest: failed loading conftest, before collecting tests.
- `scripts/build_demo.py`: failed importing FAISS.
- `scripts/start.py`: failed importing FAISS; HTTP smoke cannot reach this server.

All three Python failures report: `DLL load failed while importing _swigfaiss:
An Application Control policy has blocked this file.` This is a laptop runtime
blocker, not a passing test. An existing Ubuntu WSL installation is being checked
as the supported Linux runtime. No security policy has been disabled.

## Working versus partial

Frontend/worklet syntax and rate conversion pass locally. Python architecture
has existing upstream tests/evidence, but is not yet validated in this session.
Capture/inference separation exists in `Call`, but the WebSocket invokes `feed`
serially. Uploads use the engine but return a batch and close the session.
Scenario API calculates a batch before frontend animation. Verification only
records success. Scheduler caches all three tracks under artifact cadence.
Channel reliability is computed but not connected to fusion. Dashboard lacks
channel evidence, onset markers, live progress and detailed health.

## Missing / presentation blockers

Realtime upload/scenario transport, independently paced capture, streamed events,
failure/review verification outcomes, explicit hold/audit workflow, projector
layout, scenario manifest/import, preflight, one-command presentation launchers,
final evidence and runbook. Existing UI incorrectly mixes policy alert level
with acoustic status. No real speech assets ship; synthetic signals must remain
explicitly labelled. Startup runtime blocker above must be resolved or reported.

## Research blockers

No sealed model bundle or licensed/consented reference/evaluation corpus locally.
NII export needs a separate legacy Python 3.10/Fairseq environment. No measured
neural latency, accuracy, calibration or Hindi/Hinglish performance. Exact Vox
trait exports are unspecified; preserve documented acoustic profile fallback.
Model download/license verification and export feasibility remain to be checked.

## Bugs / risks found by inspection

- FFmpeg timeout is `subprocess.TimeoutExpired`, not the caught `TimeoutError`.
- Queue overflow resets channel continuity but can reuse cached branch evidence.
- Gap reset uses a nonzero window start, so first post-gap coherence may be scored.
- Research manifest input sample count is not checked against configured geometry.
- Model/index compatibility needs dimension/pipeline validation before calls.
- Audit lacks explicit risk-transition and verification-failure events.
- Known age-weight dilution and EMA delay remain documented; do not tune them to
  manufacture a presentation HIGH.

## Implementation order

1. Establish runnable runtime and record the full baseline.
2. Extend streaming API, playback, session lifecycle and workflow without breaking
   legacy clients; add integration/regression tests.
3. Expose branch reliability/freshness, fix gap handling and model contracts.
4. Build presentation dashboard, scenario manifest and privacy-safe importer.
5. Add launchers, preflight, live socket smoke and reproducible evidence capture.
6. Regenerate offline replay, perform browser QA, document actual results and limits.
7. Commit milestones, final tests and clean restart, push without rewriting history.
