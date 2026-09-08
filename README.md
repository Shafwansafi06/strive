# STRIVE — SIH 26104 architecture MVP

**A runnable audio → three-track scoring → dashboard → verification-workflow prototype.**

This implementation follows the supplied STRIVE PDF and Markdown architecture. The VoiceGuard DOCX supplies product requirements only; its four-branch architecture and 4-second/0.5-second timing were not adopted.

## What works now

- Browser microphone capture, WebSocket and REST PCM streaming, and short audio uploads.
- 16 kHz mono audio, sample-accurate 2-second windows, 1-second stride, 50% overlap.
- Real FAISS global retrieval, a per-call bounded profile store, overlap-aware coherence, dynamic weights, EMA, and reason codes.
- Separate acoustic/context/decision risk, a mock transfer hold, and recorded independent verification.
- Score-only SQLite audit, bounded input/session state, sequence checks, token protection outside localhost, and disconnect cleanup.
- Four deterministic audio scenarios, an offline portable replay, tests, setup scripts, Docker configuration, research model adapters, index building and evaluation scripts.

**The default demo uses measured DSP features and procedural audio fixtures. It is not a trained voice-clone detector.** Both reference signal families are synthetic; their labels mean engineering family 0/1. A low score does not establish a genuine speaker. All demo API events carry `demo_only: true`.

The research path loads frozen NII CM and XLSR phoneme models from a checksummed local bundle. Model-weight execution, speech accuracy, and Indian-language performance were **not validated in the build environment**. Vox-Profile's claimed 283-dimensional/2-second interface was not available as described; the implemented research default uses an explicitly named 62-dimensional acoustic profile. See [the model setup and limits](docs/MODELS.md).

## Research upgrade (0.2.0)

The research module is included in this release. A packaging rule in the first archive incorrectly excluded `strive/models/`; the new release builder tests imports and the full suite from a freshly extracted ZIP.

Seven comparable score ablations, validation-only parameter sweeps, per-language/codec/generator reporting, real dataset preparation and an opt-in research acceptance test are now implemented. See [the study guide](docs/RESEARCH_STUDY.md). The richer acoustic backend preserves legacy feature ordering; existing 24-dimensional session vectors cannot be mixed with the new 62-dimensional representation. The default DSP demo is unchanged.

## Try the demo immediately

Open **`STRIVE_Demo.html`** in a current desktop browser. Choose **Mid-call change**, click **Run scenario**, inspect the tracks, then try the mock transfer and verification controls.

This self-contained file replays JSON produced by the actual Python API. It works without installation or internet, but it does not execute the neural models, capture microphone audio, or call a backend. The full local dashboard below supports microphone and upload.

## Run the local app

Use **Python 3.12**. The tested platform is Linux; Windows setup is provided but was not executed here.

### Windows PowerShell

From the extracted `strive-mvp` folder:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-demo.lock
.\.venv\Scripts\python.exe scripts\start.py
```

You can also run `scripts/setup.ps1` to perform the first two steps if your PowerShell policy permits scripts. The direct commands above do not require a policy change.

### Linux / macOS

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-demo.lock
.venv/bin/python scripts/start.py
```

Open **http://127.0.0.1:8000**. The server listens only on loopback by default. The first installation needs internet; the default demo does not need internet afterward. Audio decoding supports WAV/FLAC through SoundFile. Install FFmpeg for other formats; encoded format support depends on the FFmpeg build.

Click **Use microphone**, grant browser permission, and speak. Capture is local to the running backend. Demo-mode microphone results remain surrogate scores, not deepfake verdicts. Use a consenting real speaker and consented spoof samples only when evaluating research models.

## Verify the build

```bash
python -m pytest -q
node --check web/app.js
node --check web/pcm-worklet.js
node tests/audio_worklet.cjs
python scripts/build_demo.py
```

With the server running in another terminal:

```bash
python scripts/smoke.py
```

The checked-in evidence records what was actually executed. See [validation results](docs/VALIDATION.md), [architecture decisions](docs/ARCHITECTURE.md), and [requirement coverage](docs/REQUIREMENTS.md).

## Run with research models

Read [docs/MODELS.md](docs/MODELS.md) first. Download the pinned source models explicitly, export NII using the separate Fairseq environment, seal the model bundle, and build a reference index from your labelled speech corpus. Then:

```bash
python -m pip install -r requirements-research.txt
python scripts/start.py --research
```

Missing models, invalid hashes, fixture indexes, and CM/index version mismatches fail startup. They never silently switch to demo features. No paid model or speech API is required. Neural inference speed depends on the actual models and hardware; this project does not claim the diagram's 200 ms target.

## Docker

```bash
export STRIVE_API_TOKEN='choose-a-long-local-secret'
docker compose up --build
```

On Windows use `$env:STRIVE_API_TOKEN = 'choose-a-long-local-secret'` before `docker compose up --build`. Enter that token using **API access** in the dashboard. It remains in page memory. Do not commit it. Compose binds the host port to loopback. Docker configuration was provided but not executed in the build environment.

For network access, put the app behind your organization's authenticated HTTPS reverse proxy. The MVP uses one shared bearer token, not production role-based access. SMS, bank integration, MFA, and callbacks are not performed by this app; the verification buttons record a **mock** operator confirmation.

## Folder guide

| Path | Purpose |
|---|---|
| `strive/audio.py` | Decode, normalize, VAD interface, and configurable ring buffer |
| `strive/channel.py` | Channel intelligence: bandwidth, SNR, clipping, continuity, quality |
| `strive/capture.py` | Bounded capture queue and backpressure counters |
| `strive/scheduler.py` | Multi-rate branch cadences and staleness |
| `strive/telemetry.py` | Per-stage timers and p50/p95 aggregation |
| `strive/branches.py` | Shared branch result schema and availability masking |
| `strive/features.py` | Demo DSP features and measured acoustic profile |
| `strive/retrieval.py` | Global FAISS partitions and in-session FAISS comparison |
| `strive/engine.py` | Three tracks, bootstrap, gates, weights and EMA |
| `strive/policy.py` | Business context and verification policy |
| `strive/api.py` | FastAPI, HTTP/WebSocket, mock actions, health and metrics |
| `strive/models/research.py` | Local frozen model adapters |
| `web/` | Dashboard and microphone AudioWorklet |
| `scripts/` | Setup, export/download, index, evaluation, augmentation and demo tools |
| `tests/` | Architecture, stream, API, policy, privacy and evaluation checks |
| `evidence/` | Measured test/benchmark results and replay events |
| `docs/` | Architecture decisions, limits, model setup and API reference |
| `docs/BASELINE.md` | Frozen pre-sprint baseline: environment, deps, measured tests |
| `docs/LATENCY.md` | Timers, multi-rate scheduler and measured latency |
| `docs/CODEC_BENCHMARK.md` | Codec condition matrix and paired-manifest rules |

## Push to your GitHub repository

Create an empty repository in GitHub, then run these commands inside this folder, replacing the example remote:

```bash
git init
git add .
git commit -m "Add STRIVE architecture MVP"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPOSITORY.git
git push -u origin main
```

No remote was created or pushed by this build. Model weights, secrets, recorded audio, local databases and indexes are excluded by `.gitignore`. Review the source and third-party model licenses before choosing a license for your own repository.
