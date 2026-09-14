# STRIVE

**Streaming Training-free Real-time Identity-Verification Engine**

AI-Powered Real-Time Detection and Prevention of Voice Cloning Impersonation
Attacks · Smart India Hackathon 2026 · **SIH26104** · **Team Null Pointer**

STRIVE is a real-time call-risk MVP. Audio from a microphone, uploaded recording,
or deterministic presentation scenario passes through the same 16 kHz streaming
pipeline. The dashboard shows artifact, in-call consistency, continuity and
channel evidence; keeps authenticity, business context and policy decision risk
separate; then demonstrates holding a sensitive action for trusted verification.

The default build is **DEMO DSP**. Its procedural signals and reference vectors
prove the streaming and prevention workflow. They do not measure voice-clone
accuracy. Low means **low observed risk**, not identity verified. A fail-closed
research pathway loads sealed local NII/XLSR assets when separately prepared.

## Presentation start

Windows PowerShell:

```powershell
.\scripts\presentation.ps1
```

Linux/macOS/WSL:

```bash
./scripts/presentation.sh
```

The launcher runs preflight, starts a loopback-only server, and opens or prints
<http://127.0.0.1:8000>. On this Windows presentation laptop, Application Control
blocks the FAISS native DLL; `presentation.ps1` automatically uses the tested
Ubuntu/WSL environment when `.venv-linux` is present.

Recommended judge flow: enable **Presentation Mode**, click **Mid-Call Voice
Replacement**, watch the temporary profile become trusted and the source change
at 15 seconds, then click **Hold & Verify** and select **Failed** or **Verified**.
See [the exact runbook](docs/SIH_PRESENTATION_RUNBOOK.md).

## Setup

Python 3.12 is required. Install the pinned CPU/demo environment:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-demo.lock
```

On Windows, use `.venv\Scripts\python.exe`. FFmpeg is optional for WAV/FLAC and
required for MP3/M4A/AAC/OGG/Opus/WebM uploads. Raw uploaded/microphone PCM and
voice embeddings are not persisted by default.

Use consented or licensed real presentation recordings through
[the audio importer guide](data/demo/README.md). No human voice recordings ship
in this repository.

## Validation

```bash
python -m pytest -q
node --check web/app.js
node --check web/pcm-worklet.js
node tests/audio_worklet.cjs
python scripts/build_demo.py
python scripts/presentation_check.py
python scripts/presentation_evidence.py
```

With the server running:

```bash
python scripts/smoke.py
```

Executed results and their limits are in [validation](docs/VALIDATION.md) and
`evidence/sih-final/`. Do not report the DSP scenario scores as neural detection
metrics.

## Architecture

```text
upload / microphone / scenario
             ↓
memory decode → 16 kHz mono → ring buffer → bounded capture queue
             ↓
VAD + channel intelligence + multi-rate evidence branches
             ↓
availability/reliability mask → temporal fusion → authenticity risk
             ↓
business context → explicit policy layer → decision risk
             ↓
hold → callback / MFA / supervisor simulation → release / block / review
```

`AUTHENTICITY RISK != CONTEXT RISK != DECISION RISK`. Channel degradation changes
evidence reliability and never becomes proof of spoofing. Missing or stale evidence
is unavailable, never zero.

Key paths:

- `strive/audio.py`, `capture.py`, `engine.py`, `channel.py`: streaming pipeline.
- `strive/api.py`, `policy.py`, `audit.py`: API, prevention, privacy-safe audit.
- `strive/models/research.py`: sealed frozen-model adapters.
- `web/`: presentation dashboard and AudioWorklet microphone capture.
- `scripts/`: launch, preflight, model preparation, evaluation and evidence tools.
- `tests/`: audio, scheduler, API, workflow, privacy and research contracts.

Read [architecture](docs/ARCHITECTURE.md), [API](docs/API.md),
[models](docs/MODELS.md), [requirements](docs/REQUIREMENTS.md), and
[the audit](docs/SIH_MVP_GAP_ANALYSIS.md) before changing scientific behavior.

## Research neural mode

The intended prototype path uses frozen `nii-yamagishilab/mms-300m-anti-deepfake`
and an XLSR phoneme model with a labelled FAISS reference index. No weights or
speech corpus are committed. NII weights use CC BY-NC-SA 4.0; review suitability
before non-research use.

After preparing, exporting, hashing and sealing the assets exactly as documented:

```bash
python -m pip install -r requirements-research.txt
python scripts/presentation.py --research
```

Research mode refuses missing files, checksum mismatches, wrong input geometry,
fixture indexes, and model/index incompatibility. It does not silently fall back
to demo DSP.

## Offline fallback

Open `STRIVE_Demo.html` directly. It is labelled **OFFLINE REPLAY / FALLBACK
DEMO**, embeds captured API events, runs no model, and supports no live microphone
or upload. Regenerate it with `python scripts/build_demo.py` after behavior changes.

The MVP has no SIP/Asterisk connection, real bank transfer, real callback/MFA,
production IAM, calibrated probability, or validated Indian-language accuracy.
