# STRIVE — Agent Execution Plan & Ticket Board
## SIH26104: AI-Powered Real-Time Detection and Prevention of Voice Cloning Impersonation Attacks

**Purpose:** turn STRIVE from a research-heavy prototype into a reliable, measurable, demo-ready product while preserving enough novelty for research and SIH differentiation.

**Operating principle:** **thin slice first, evidence second, sophistication third.**

---

# 0. Product Contract

STRIVE should continuously analyze live or near-live call audio and produce:

1. **Authenticity risk** — evidence that the audio is synthetic/manipulated.
2. **Context risk** — business/workflow risk kept separate from acoustic authenticity.
3. **Decision risk** — policy-level combination used to Allow / Verify / Hold / Escalate.
4. **Reason codes** — why the score changed.
5. **Confidence / reliability** — whether the current channel and evidence are trustworthy.

## P0 demo flow

```text
Browser/WebRTC or deterministic WAV stream
            ↓
VAD + resample + ring buffer
            ↓
Channel Intelligence
(codec / bandwidth / SNR / clipping / continuity)
            ↓
Parallel evidence branches
├── Artifact / spoof
├── Prosody
├── Session consistency
└── Identity (optional)
            ↓
Reliability-aware temporal fusion
            ↓
Authenticity risk
            ↓
Context + policy
            ↓
Dashboard / API
```

## Non-negotiables

- [ ] No raw audio persisted by default.
- [ ] Silence / timeout / branch failure must never silently become `LOW`.
- [ ] Core path must run without paid APIs.
- [ ] Every score event must carry model/version metadata.
- [ ] Every stage must expose latency.
- [ ] Context risk must remain separate from authenticity risk.
- [ ] P1 features may be disabled if they harm latency or reliability.
- [ ] No new "novel" feature enters the demo without an ablation or measurable benefit.

---

# 1. Architecture Freeze for Sprint 1

Do **not** redesign the full architecture during Sprint 1.

### Keep

- streaming audio ingestion
- 16 kHz mono canonical waveform
- rolling window analysis
- artifact/spoof branch
- existing session/SPS work
- temporal smoothing / EMA
- policy engine
- current dashboard/API skeleton
- codec augmentation tooling

### Add now

1. **Channel Intelligence**
2. **Configurable 0.5 s hop**
3. **Per-stage latency instrumentation**
4. **Multi-rate branch scheduler**
5. **Reliability-aware fusion hooks**
6. **Codec robustness evaluation**

### Defer until P0 is stable

- full SIP/Asterisk integration
- TensorRT rewrite
- large-scale ASVspoof sweeps
- learned fusion controller
- new TTS generation pipeline
- advanced phoneme-coherence claims
- cross-call biometric enrollment
- production IAM / multi-tenancy

---

# 2. Repository Target Structure

Do not force this refactor immediately. Move toward it incrementally.

```text
strive/
├── audio/
│   ├── ingest.py
│   ├── buffer.py
│   ├── resample.py
│   └── vad.py
│
├── channel/
│   ├── quality.py
│   ├── continuity.py
│   ├── codec.py
│   └── reliability.py
│
├── branches/
│   ├── artifact.py
│   ├── prosody.py
│   ├── session.py
│   └── identity.py
│
├── fusion/
│   ├── controller.py
│   ├── temporal.py
│   └── calibration.py
│
├── runtime/
│   ├── scheduler.py
│   ├── state.py
│   └── telemetry.py
│
├── policy/
│   └── engine.py
│
├── api/
│   ├── rest.py
│   └── websocket.py
│
└── evaluation/
    ├── codecs.py
    ├── latency.py
    └── streaming.py
```

---

# 3. Agent Rules

Every coding agent receives **one ticket or one tightly related ticket pair**.

## Agent must

- read only the files necessary for the ticket first
- state the files it plans to modify
- avoid unrelated refactors
- preserve public interfaces unless ticket says otherwise
- add/update tests
- run targeted tests before broad tests
- return:
  - changed files
  - implementation summary
  - tests run
  - measured results
  - remaining risks

## Agent must NOT

- introduce a new framework without approval
- rename large parts of the repository
- rewrite working code "for cleanliness"
- modify another agent's owned file without coordination
- change thresholds to make demo outputs look better
- fabricate benchmark numbers
- make unsupported scientific claims

## Branch naming

```text
feat/strive-<ticket-id>-short-name
fix/strive-<ticket-id>-short-name
test/strive-<ticket-id>-short-name
```

Example:

```text
feat/strive-CH-01-channel-state
```

## Commit format

```text
[CH-01] Add ChannelState schema and quality metrics
```

---

# 4. Ticket Priority

- **P0** = required for reliable SIH prototype
- **P1** = high-value after P0 stable
- **P2** = research/product extension

Suggested ticket sizing:

- **XS**: 20–40 min
- **S**: 40–90 min
- **M**: 1.5–3 h
- **L**: 3–5 h — split further whenever possible

---

# 5. Sprint 0 — Baseline & Guardrails

## BASE-01 — Freeze current baseline
**Priority:** P0  
**Size:** S  
**Agent:** Repo / QA Agent  
**Depends on:** none

### Task
Record the exact current baseline before architecture changes.

### Deliverables
- create `docs/BASELINE.md`
- record:
  - current commit hash
  - Python version
  - major dependency versions
  - reference hardware
  - current window / hop configuration
  - current available tests
  - current model mode: demo vs research
- add exact commands to start backend and frontend

### Acceptance
- [ ] fresh clone can follow documented startup steps
- [ ] baseline test command exits successfully or known failures are documented
- [ ] no functional code changed

---

## BASE-02 — Add central runtime configuration
**Priority:** P0  
**Size:** S  
**Agent:** Backend Agent  
**Depends on:** BASE-01

### Task
Ensure streaming parameters are configured centrally rather than hard-coded.

### Minimum config
```yaml
sample_rate: 16000
window_seconds: 2.0
hop_seconds: 0.5
min_voiced_seconds: 4.0
```

### Acceptance
- [ ] 1.0 s and 0.5 s hop are both configurable
- [ ] default can be changed without editing inference code
- [ ] unit test verifies sample counts

---

## BASE-03 — Add benchmark result schema
**Priority:** P0  
**Size:** XS  
**Agent:** Evaluation Agent  
**Depends on:** BASE-01

### Task
Define a machine-readable result schema.

Suggested output:

```json
{
  "run_id": "...",
  "git_commit": "...",
  "hardware": "...",
  "mode": "demo|research",
  "dataset": "...",
  "codec": "...",
  "window_s": 2.0,
  "hop_s": 0.5,
  "metrics": {},
  "latency_ms": {}
}
```

### Acceptance
- [ ] JSON serializable
- [ ] run metadata is sufficient to reproduce experiment

---

# 6. Workstream A — Streaming Audio Edge

## AUD-01 — Verify canonical audio normalization
**Priority:** P0  
**Size:** S  
**Agent:** Audio Agent  
**Depends on:** BASE-01

### Task
Verify every source is converted to:
- mono
- 16 kHz
- float32 or documented canonical PCM format

### Acceptance
- [ ] stereo input test
- [ ] 8 kHz input test
- [ ] 44.1/48 kHz input test
- [ ] output duration stays within tolerance
- [ ] no unexpected amplitude clipping

---

## AUD-02 — Make ring-buffer hop configurable
**Priority:** P0  
**Size:** S  
**Agent:** Audio Agent  
**Depends on:** BASE-02

### Task
Support at minimum:

```text
2 s window / 1 s hop
2 s window / 0.5 s hop
4 s window / 0.5 s hop
```

### Acceptance
- [ ] no concatenation-based unbounded memory growth
- [ ] emitted window timestamps are monotonic
- [ ] 0.5 s hop emits ~2 windows/sec after warm-up
- [ ] test covers overlap behavior

---

## AUD-03 — Add explicit evidence warm-up state
**Priority:** P0  
**Size:** S  
**Agent:** Backend Agent  
**Depends on:** AUD-02

### Task
Before minimum voiced evidence is reached, emit:

```json
{
  "state": "ANALYZING",
  "reason": "LOW_EVIDENCE"
}
```

### Acceptance
- [ ] silence never produces `LOW`
- [ ] stream startup never produces a green state before threshold
- [ ] UI/API can distinguish `ANALYZING` from numeric low risk

---

## AUD-04 — Protect capture loop from inference stalls
**Priority:** P1  
**Size:** M  
**Agent:** Streaming Systems Agent  
**Depends on:** AUD-02

### Task
Ensure model inference cannot block audio ingestion.

### Acceptance
- [ ] capture loop and inference execution are separate
- [ ] bounded queue / backpressure strategy documented
- [ ] dropped/late frame counter exposed
- [ ] test simulates intentionally slow inference

---

# 7. Workstream B — Channel Intelligence

## CH-01 — Define `ChannelState`
**Priority:** P0  
**Size:** XS  
**Agent:** Audio / DSP Agent  
**Depends on:** BASE-01

### Add schema

```python
@dataclass
class ChannelState:
    sample_rate: int
    estimated_bandwidth_hz: float | None
    snr_db: float | None
    clipping_ratio: float
    rms_dbfs: float | None
    discontinuity_score: float
    packet_loss_rate: float | None = None
    jitter_ms: float | None = None
    codec: str | None = None
    quality: float | None = None
```

### Acceptance
- [ ] schema is stable and serializable
- [ ] unavailable values are explicit `None`, not fake zeros

---

## CH-02 — Implement clipping ratio
**Priority:** P0  
**Size:** XS  
**Agent:** DSP Agent  
**Depends on:** CH-01

### Acceptance
- [ ] detects synthetic hard clipping test case
- [ ] near-zero for normal speech fixture
- [ ] no model dependency

---

## CH-03 — Implement effective bandwidth estimate
**Priority:** P0  
**Size:** S  
**Agent:** DSP Agent  
**Depends on:** CH-01

### Task
Estimate occupied/effective spectral bandwidth.

### Acceptance
- [ ] differentiates 8 kHz narrowband from 16 kHz wideband fixture
- [ ] deterministic
- [ ] documented method and threshold assumptions

---

## CH-04 — Implement rough SNR/noise estimate
**Priority:** P0  
**Size:** S  
**Agent:** DSP Agent  
**Depends on:** CH-01

### Task
Add a lightweight SNR proxy; avoid claiming laboratory-grade SNR.

### Acceptance
- [ ] noisy fixture scores worse than clean fixture
- [ ] no negative/NaN explosions
- [ ] output documented as an estimate

---

## CH-05 — Implement continuity/discontinuity score
**Priority:** P0  
**Size:** M  
**Agent:** DSP Agent  
**Depends on:** CH-01, AUD-02

### Task
Compute a cheap channel continuity signal across adjacent windows.

Possible inputs:
- energy jump
- spectral centroid jump
- noise-floor jump
- boundary sample discontinuity

### Acceptance
- [ ] injected cut/splice fixture scores higher than continuous fixture
- [ ] output bounded or normalized
- [ ] no deep model required

---

## CH-06 — Channel quality aggregation
**Priority:** P1  
**Size:** S  
**Agent:** DSP Agent  
**Depends on:** CH-02, CH-03, CH-04, CH-05

### Task
Produce a conservative quality scalar from measured channel features.

### Rule
This value is **reliability**, not "spoof probability".

### Acceptance
- [ ] quality decreases for deliberately degraded fixtures
- [ ] feature values remain available individually
- [ ] heuristic constants live in config

---

## CH-07 — Surface channel state through API
**Priority:** P0  
**Size:** S  
**Agent:** API Agent  
**Depends on:** CH-01

### Acceptance
Risk event includes:

```json
"channel": {
  "codec": null,
  "sample_rate": 16000,
  "estimated_bandwidth_hz": 7600,
  "snr_db": 18.2,
  "clipping_ratio": 0.001,
  "discontinuity_score": 0.12,
  "quality": 0.84
}
```

- [ ] schema documented
- [ ] backward compatibility handled

---

# 8. Workstream C — Codec Robustness Lab

## CODEC-01 — Audit existing augmentation script
**Priority:** P0  
**Size:** XS  
**Agent:** Evaluation Agent  
**Depends on:** BASE-01

### Task
Document current support for:
- Opus
- G.711 μ-law
- G.711 A-law
- narrowband
- noise
- packet loss

### Deliverable
`docs/CODEC_BENCHMARK.md`

---

## CODEC-02 — Add bitrate matrix
**Priority:** P0  
**Size:** S  
**Agent:** Evaluation Agent  
**Depends on:** CODEC-01

### Minimum Opus set
```text
6 kbps
12 kbps
16 kbps
24 kbps
32 kbps
```

### Acceptance
- [ ] deterministic output names
- [ ] metadata preserves original `source_id`
- [ ] codec failure returns explicit error

---

## CODEC-03 — Add paired clean/degraded manifest
**Priority:** P0  
**Size:** S  
**Agent:** Data Agent  
**Depends on:** CODEC-01

### Schema
```csv
source_id,label,speaker_id,language,condition,path
```

### Acceptance
- [ ] clean and all derived variants share `source_id`
- [ ] no accidental split leakage
- [ ] validator catches duplicate/conflicting metadata

---

## CODEC-04 — Small smoke benchmark
**Priority:** P0  
**Size:** M  
**Agent:** Evaluation Agent  
**Depends on:** CODEC-02, CODEC-03

### Run
Use a **small licensed/consented set first**.

Conditions:
- clean
- Opus 16k
- Opus 32k
- G.711
- 8 kHz narrowband
- one noise condition

### Metrics
- score distributions
- EER if cohort permits
- ROC-AUC if cohort permits
- latency
- failure count

### Acceptance
- [ ] results written to machine-readable JSON/CSV
- [ ] no fabricated values
- [ ] experiment command documented

---

## CODEC-05 — Codec degradation delta report
**Priority:** P1  
**Size:** S  
**Agent:** Evaluation Agent  
**Depends on:** CODEC-04

### Compute
```text
ΔEER(codec) = EER(codec) - EER(clean)
```

Also report:
- ΔAUC
- score drift
- false-positive drift

### Acceptance
- [ ] paired result table generated automatically

---

## CODEC-06 — Embedding preservation study
**Priority:** P1  
**Size:** M  
**Agent:** Research Agent  
**Depends on:** CODEC-04

### Compute
For encoder `f`:

```text
cos(f(clean), f(codec(clean)))
```

for:
- artifact embedding
- session embedding
- phoneme embedding if available

### Acceptance
- [ ] paired by `source_id`
- [ ] mean + spread reported by codec
- [ ] no claim beyond measured encoders

---

# 9. Workstream D — Evidence Branch Interfaces

## BR-01 — Standardize branch result schema
**Priority:** P0  
**Size:** S  
**Agent:** ML Platform Agent  
**Depends on:** BASE-01

### Proposed schema

```python
@dataclass
class BranchResult:
    name: str
    score: float | None
    confidence: float
    reliability: float
    timestamp: float
    latency_ms: float
    available: bool
    reason_codes: list[str]
    metadata: dict
```

### Acceptance
- [ ] artifact branch conforms
- [ ] missing branch uses `available=False`
- [ ] fusion no longer assumes every branch exists

---

## BR-02 — Wrap current artifact model
**Priority:** P0  
**Size:** S  
**Agent:** ML Agent  
**Depends on:** BR-01

### Acceptance
- [ ] no model architecture change
- [ ] output normalized through `BranchResult`
- [ ] model/checkpoint/version metadata present
- [ ] latency reported

---

## BR-03 — Wrap current session/SPS score
**Priority:** P1  
**Size:** S  
**Agent:** ML Agent  
**Depends on:** BR-01

### Acceptance
- [ ] SPS cold-start is explicit
- [ ] no fake zero interpreted as confident genuine
- [ ] profile updates preserve existing safety gate behavior
- [ ] latency reported

---

## BR-04 — Minimal prosody branch
**Priority:** P1  
**Size:** M  
**Agent:** Speech Agent  
**Depends on:** BR-01

### P0/P1 features only
- F0 statistics
- energy variation
- pause ratio / voiced ratio
- speaking-rate proxy if already available

### Do not
Treat any single cue as proof of spoofing.

### Acceptance
- [ ] branch outputs supporting evidence only
- [ ] codec/noise sensitivity documented
- [ ] gracefully unavailable when insufficient voiced audio

---

## BR-05 — Identity branch adapter
**Priority:** P2  
**Size:** M  
**Agent:** Speech Agent  
**Depends on:** BR-01

### Rule
Optional. Do not block demo if unfinished.

### Acceptance
- [ ] fusion works identically when identity unavailable
- [ ] enrolled embedding never logged in plaintext debug output

---

# 10. Workstream E — Multi-Rate Scheduler & Latency

## SCH-01 — Define branch cadence config
**Priority:** P0  
**Size:** XS  
**Agent:** Runtime Agent  
**Depends on:** BR-01

### Default proposal
```yaml
channel_ms: 500
prosody_ms: 500
artifact_ms: 1000
session_ms: 2000
identity_ms: 3000
fusion_ms: 500
```

### Acceptance
- [ ] config-driven
- [ ] no branch-specific hard-coded sleep loops

---

## SCH-02 — Implement `BranchState`
**Priority:** P0  
**Size:** S  
**Agent:** Runtime Agent  
**Depends on:** SCH-01

### Schema
```python
BranchState(
    result,
    updated_at,
    stale_after_ms
)
```

### Acceptance
- [ ] stale results detected
- [ ] missing results explicit
- [ ] thread/task safe for current runtime model

---

## SCH-03 — Implement multi-rate scheduler
**Priority:** P0  
**Size:** M  
**Agent:** Runtime Agent  
**Depends on:** SCH-01, SCH-02, BR-02

### Acceptance
- [ ] fusion can update at 500 ms
- [ ] artifact model need not run every 500 ms
- [ ] scheduler exposes queue delay
- [ ] branch exception does not kill full call session

---

## LAT-01 — Per-stage timer utility
**Priority:** P0  
**Size:** XS  
**Agent:** Observability Agent  
**Depends on:** BASE-01

### Required stages
- decode
- resample
- VAD
- buffer wait
- channel features
- artifact inference
- session inference
- fusion
- API push

### Acceptance
- [ ] timers add negligible overhead
- [ ] p50/p95 can be aggregated

---

## LAT-02 — End-to-end latency event
**Priority:** P0  
**Size:** S  
**Agent:** Observability Agent  
**Depends on:** LAT-01

### Acceptance
Every risk event can expose:

```json
"latency_ms": {
  "compute": 86.3,
  "queue": 4.1,
  "end_to_end": 102.4
}
```

---

## LAT-03 — Latency benchmark command
**Priority:** P0  
**Size:** S  
**Agent:** Evaluation Agent  
**Depends on:** LAT-02, SCH-03

### Output
- p50
- p95
- max
- realtime factor
- per-stage breakdown

### Acceptance
- [ ] same test can run on CPU or GPU
- [ ] hardware metadata captured

---

# 11. Workstream F — Reliability-Aware Fusion

## FUS-01 — Preserve existing temporal EMA
**Priority:** P0  
**Size:** XS  
**Agent:** Fusion Agent  
**Depends on:** BR-01

### Task
Add tests around current behavior before changing weighting logic.

### Acceptance
- [ ] deterministic unit test
- [ ] one anomalous frame cannot accidentally generate permanent high state
- [ ] sustained high inputs eventually elevate risk

---

## FUS-02 — Add availability mask
**Priority:** P0  
**Size:** S  
**Agent:** Fusion Agent  
**Depends on:** BR-01, FUS-01

### Acceptance
- [ ] identity absent does not contribute zero as if genuine
- [ ] stale branch handled explicitly
- [ ] normalized weights sum correctly across available branches

---

## FUS-03 — Add channel reliability hook
**Priority:** P0  
**Size:** S  
**Agent:** Fusion Agent  
**Depends on:** CH-06, FUS-02

### Rule
Start with conservative **configurable heuristics**.

Example concept only:
```text
degraded channel
→ reduce unreliable prosody contribution
→ never automatically reduce primary spoof risk to "safe"
```

### Acceptance
- [ ] rule coefficients live in config
- [ ] unit tests cover clean/degraded channel
- [ ] feature can be disabled with flag

---

## FUS-04 — Compare fixed vs channel-aware fusion
**Priority:** P1  
**Size:** M  
**Agent:** Evaluation Agent  
**Depends on:** FUS-03, CODEC-04

### Report
- fixed fusion
- availability-only fusion
- channel-aware fusion

### Acceptance
- [ ] common test cohort
- [ ] report both security quality and latency
- [ ] do not adopt adaptive fusion if it worsens low-FPR behavior

---

# 12. Workstream G — Risk API & Policy

## API-01 — Version risk event schema
**Priority:** P0  
**Size:** S  
**Agent:** API Agent  
**Depends on:** BR-01, CH-07, LAT-02

### Required fields
```json
{
  "call_id": "...",
  "state": "ANALYZING|LOW|REVIEW|HIGH|CRITICAL",
  "authenticity_risk": 0.0,
  "context_risk": 0.0,
  "decision_risk": 0.0,
  "confidence": 0.0,
  "branches": {},
  "channel": {},
  "reasons": [],
  "latency_ms": {},
  "model_version": "..."
}
```

### Acceptance
- [ ] JSON schema / Pydantic model
- [ ] schema version added
- [ ] malformed branch payload rejected

---

## POL-01 — Keep authenticity and context separate
**Priority:** P0  
**Size:** S  
**Agent:** Policy Agent  
**Depends on:** API-01

### Acceptance
- [ ] context metadata cannot alter `authenticity_risk`
- [ ] only `decision_risk` combines both
- [ ] unit test proves separation

---

## POL-02 — Implement safe default bands
**Priority:** P0  
**Size:** S  
**Agent:** Policy Agent  
**Depends on:** POL-01

Suggested conceptual states:
- ANALYZING
- LOW
- REVIEW
- HIGH
- CRITICAL

### Rule
Default behavior protects the **action**, not automatically terminates the call.

### Acceptance
- [ ] REVIEW → secondary verification
- [ ] HIGH → hold sensitive action
- [ ] CRITICAL → escalate
- [ ] thresholds configurable

---

# 13. Workstream H — Dashboard

## UI-01 — Add explicit analyzing state
**Priority:** P0  
**Size:** S  
**Agent:** Frontend Agent  
**Depends on:** API-01

### Acceptance
- [ ] never displays green while evidence insufficient
- [ ] reason `LOW_EVIDENCE` visible

---

## UI-02 — Show three risks separately
**Priority:** P0  
**Size:** S  
**Agent:** Frontend Agent  
**Depends on:** API-01

Display:
- authenticity
- context
- decision

### Acceptance
- [ ] labels cannot be confused
- [ ] no single opaque score only

---

## UI-03 — Show branch + channel explanations
**Priority:** P1  
**Size:** M  
**Agent:** Frontend Agent  
**Depends on:** CH-07, API-01

Example:
```text
Spoof artifact: Strong
Session consistency: Moderate
Prosody: Low confidence
Channel: Degraded / Opus / low SNR
```

### Acceptance
- [ ] raw technical values available in expandable view
- [ ] main UI stays understandable to non-ML user

---

## UI-04 — Live latency indicator
**Priority:** P1  
**Size:** XS  
**Agent:** Frontend Agent  
**Depends on:** LAT-02

### Acceptance
- [ ] update latency visible in debug/demo mode
- [ ] not shown as fake rounded number when missing

---

# 14. Workstream I — Evaluation & Research Evidence

## EVAL-01 — Streaming WAV simulator
**Priority:** P0  
**Size:** M  
**Agent:** Evaluation Agent  
**Depends on:** AUD-02, API-01

### Task
Stream a WAV file as if it were live audio.

### Acceptance
- [ ] real wall-clock mode
- [ ] accelerated deterministic mode
- [ ] outputs risk events per hop

---

## EVAL-02 — Mixed real→spoof scenario
**Priority:** P0  
**Size:** S  
**Agent:** Evaluation Agent  
**Depends on:** EVAL-01

### Task
Create a consented/licensed test scenario:

```text
genuine segment
→ attack onset timestamp
→ spoof segment
```

### Acceptance
- [ ] onset timestamp stored in manifest
- [ ] no deceptive/unconsented voice cloning

---

## EVAL-03 — Time-to-alert metric
**Priority:** P0  
**Size:** S  
**Agent:** Evaluation Agent  
**Depends on:** EVAL-02, POL-02

### Define
```text
detection_delay = first_stable_high_risk_time - attack_onset_time
```

### Acceptance
- [ ] configurable stable-state rule
- [ ] no negative values
- [ ] missed detection recorded explicitly, not dropped

---

## EVAL-04 — Common metrics report
**Priority:** P0  
**Size:** M  
**Agent:** Evaluation Agent  
**Depends on:** CODEC-04, EVAL-03

### Report when cohort supports them
- EER
- ROC-AUC
- PR-AUC
- TPR at fixed FPR
- Brier / calibration
- time-to-alert
- per-codec metrics
- per-language metrics where available
- p50/p95 latency

---

## EVAL-05 — Ablation runner
**Priority:** P1  
**Size:** M  
**Agent:** Research Agent  
**Depends on:** FUS-04, EVAL-04

### Minimum configurations
```text
A: artifact only
B: artifact + EMA
C: artifact + session
D: artifact + session + prosody
E: D + channel-aware reliability
```

### Acceptance
- [ ] exact same cohort across configurations
- [ ] output includes quality + latency
- [ ] no cherry-picked subset

---

# 15. Workstream J — Privacy, Security & Reproducibility

## SEC-01 — Assert no raw-audio persistence
**Priority:** P0  
**Size:** S  
**Agent:** Security Agent  
**Depends on:** AUD-01

### Acceptance
- [ ] integration test runs a call and checks output/storage directories
- [ ] no `.wav`, raw PCM, or hidden temporary audio persists in default mode
- [ ] debug recording requires explicit opt-in flag

---

## SEC-02 — Pseudonymous call IDs
**Priority:** P0  
**Size:** XS  
**Agent:** Backend Agent  
**Depends on:** API-01

### Acceptance
- [ ] phone numbers are not used as IDs
- [ ] IDs are safe for logs

---

## SEC-03 — Model/version provenance
**Priority:** P0  
**Size:** S  
**Agent:** MLOps Agent  
**Depends on:** BR-02

### Record
- model name
- checkpoint hash if practical
- code commit
- runtime mode
- dependency version

### Acceptance
- [ ] every benchmark result can identify model version
- [ ] every API event exposes a model release version

---

## SEC-04 — License manifest
**Priority:** P0  
**Size:** S  
**Agent:** Research / Compliance Agent  
**Depends on:** BASE-01

### Deliverable
`docs/LICENSE_MANIFEST.md`

Columns:
```text
asset | source | code license | weights license | data license | demo allowed? | production allowed? | notes
```

### Acceptance
- [ ] unknown licenses marked UNKNOWN
- [ ] no "free" == "production-safe" assumption

---

# 16. Workstream K — Demo & Packaging

## DEMO-01 — Single-command local startup
**Priority:** P0  
**Size:** M  
**Agent:** DevOps Agent  
**Depends on:** API-01, UI-01

### Goal
One documented command/process starts:
- backend
- frontend
- required local services

### Acceptance
- [ ] works without outbound internet after models/deps installed
- [ ] health check available

---

## DEMO-02 — Deterministic demo scenarios
**Priority:** P0  
**Size:** M  
**Agent:** Demo Agent  
**Depends on:** EVAL-01, UI-02

Create:
1. genuine call
2. obvious spoof
3. mixed genuine→spoof
4. degraded codec example
5. offline/network-disconnect demonstration

### Acceptance
- [ ] all scenarios use consented/licensed audio
- [ ] each has expected state progression documented
- [ ] no threshold tuning performed per scenario

---

## DEMO-03 — Evidence bundle
**Priority:** P1  
**Size:** M  
**Agent:** Documentation Agent  
**Depends on:** EVAL-04, LAT-03, SEC-04

Bundle:
- architecture image
- latency table
- codec robustness table
- time-to-alert plot
- model card
- license manifest
- known failures
- demo commands

---

# 17. Suggested Parallel Agent Groups

Avoid giving multiple agents the same hot files.

## Group A — Audio + Channel
Own:
```text
audio/*
channel/*
```

Tickets:
`AUD-01 → AUD-02 → CH-01 → CH-02/03/04/05 → CH-06`

---

## Group B — Runtime + Latency
Own:
```text
runtime/*
telemetry/*
```

Tickets:
`SCH-01 → SCH-02 → SCH-03`
and
`LAT-01 → LAT-02 → LAT-03`

---

## Group C — ML Branches
Own:
```text
branches/*
models/*
retrieval/*
```

Tickets:
`BR-01 → BR-02`
then
`BR-03 / BR-04`

---

## Group D — Fusion + Policy
Own:
```text
fusion/*
policy/*
```

Tickets:
`FUS-01 → FUS-02 → FUS-03`
`POL-01 → POL-02`

---

## Group E — Evaluation
Own:
```text
evaluation/*
scripts/augment*
benchmarks/*
```

Tickets:
`CODEC-01 → CODEC-02/03 → CODEC-04`
`EVAL-01 → EVAL-02 → EVAL-03`

---

## Group F — API + UI
Own:
```text
api/*
frontend/*
```

Tickets:
`API-01`
then
`UI-01 / UI-02`
then
`UI-03 / UI-04`

---

# 18. Dependency Graph

```text
BASE-01
├── BASE-02
│   └── AUD-02
│       ├── AUD-03
│       ├── CH-05
│       └── EVAL-01
│
├── CH-01
│   ├── CH-02
│   ├── CH-03
│   ├── CH-04
│   └── CH-05
│       └── CH-06
│           └── FUS-03
│
├── BR-01
│   ├── BR-02
│   │   └── SCH-03
│   ├── BR-03
│   └── BR-04
│
├── FUS-01
│   └── FUS-02
│       └── FUS-03
│
└── LAT-01
    └── LAT-02
        └── LAT-03

CODEC-01
├── CODEC-02
├── CODEC-03
└── CODEC-04
    ├── CODEC-05
    └── CODEC-06

API-01
├── UI-01
├── UI-02
└── POL-01
    └── POL-02
        └── EVAL-03
```

---

# 19. What to Execute First — 48-Hour Coding Sprint

This is the recommended starting order.

## Block 1 — First 3 hours

Run in parallel:

### Agent A
- BASE-01
- BASE-02

### Agent B
- CODEC-01
- BASE-03

### Agent C
- LAT-01
- BR-01

### Agent D
- CH-01
- CH-02

**Exit condition:** stable baseline, central config, result schemas.

---

## Block 2 — Hours 3–8

Parallel:

### Agent A
- AUD-02
- AUD-03

### Agent B
- CH-03
- CH-04

### Agent C
- BR-02
- FUS-01

### Agent D
- CODEC-02
- CODEC-03

**Exit condition:** 0.5 s hop works, channel metrics exist, artifact branch standardized, codec matrix ready.

---

## Block 3 — Hours 8–14

Parallel:

### Agent A
- CH-05
- CH-07

### Agent B
- SCH-01
- SCH-02

### Agent C
- LAT-02
- API-01

### Agent D
- CODEC-04

**Exit condition:** channel data visible in API; first codec smoke results generated.

---

## Block 4 — Hours 14–24

Parallel:

### Agent A
- SCH-03

### Agent B
- FUS-02
- FUS-03

### Agent C
- EVAL-01
- EVAL-02

### Agent D
- UI-01
- UI-02

**Exit condition:** multi-rate execution, reliability hook, live-like WAV simulation, three-risk dashboard.

---

## Block 5 — Hours 24–36

Parallel:

### Agent A
- LAT-03

### Agent B
- EVAL-03
- EVAL-04

### Agent C
- POL-01
- POL-02

### Agent D
- SEC-01
- SEC-03
- SEC-04

**Exit condition:** measurable time-to-alert, reproducible latency report, safe policy states, license/provenance documentation.

---

## Block 6 — Hours 36–48

Only integration + hardening:

- fix failing integration tests
- DEMO-01
- DEMO-02
- CODEC-05
- UI-03 if stable
- produce one clean benchmark report
- no architecture rewrites

**48-hour success condition:**

```text
deterministic stream
→ 0.5 s risk refresh
→ real ANALYZING state
→ artifact score
→ channel quality
→ temporal fusion
→ decision policy
→ dashboard
→ measured latency
→ codec benchmark
```

---

# 20. Pull Request Gate

Every PR must answer:

```text
Ticket:
Files changed:
Why:
Public interface changed?:
Tests added/updated:
Commands run:
Results:
Latency impact:
Security/privacy impact:
Known limitations:
```

## Merge only if

- [ ] ticket acceptance criteria pass
- [ ] tests pass
- [ ] no unrelated refactor
- [ ] benchmark regression checked when hot path changes
- [ ] API schema change is documented
- [ ] no raw audio accidentally persisted

---

# 21. Agent Prompt Template

Copy this into a coding agent.

```text
You are implementing STRIVE SIH26104.

Ticket: <TICKET_ID> — <TITLE>

Goal:
<copy ticket task>

Repository constraints:
1. Read the relevant existing implementation before coding.
2. Do not perform unrelated refactors.
3. Preserve current public behavior unless the ticket explicitly changes it.
4. Add or update focused tests.
5. Avoid introducing new dependencies unless clearly necessary.
6. Do not change model thresholds to force desired outputs.
7. Never fabricate performance numbers.
8. Do not persist raw audio in default mode.

Before coding:
- list the files you expect to change
- describe your implementation plan in <= 6 bullets

After coding:
- run targeted tests
- run the relevant benchmark/smoke command if this touches runtime performance
- report exact files changed
- report test commands and results
- report unresolved risks or follow-up tickets

Acceptance criteria:
<copy acceptance criteria exactly>
```

---

# 22. Reviewer Agent Prompt

Use a separate agent to review completed tickets.

```text
Review this STRIVE ticket implementation as a strict senior engineer.

Check only against:
1. ticket acceptance criteria
2. correctness
3. concurrency/state bugs
4. real-time performance risks
5. privacy/raw-audio persistence
6. API compatibility
7. test quality
8. scientific overclaiming

Return:
- BLOCKERS
- SHOULD FIX
- NICE TO HAVE
- TESTS MISSING
- MERGE: YES/NO

Do not rewrite the implementation unless a blocker requires a minimal patch.
```

---

# 23. Benchmark Agent Prompt

```text
Act as the STRIVE evaluation engineer.

Do not modify model thresholds.

Run the requested benchmark on the exact same cohort for each condition.
Capture:
- git commit
- model/checkpoint version
- hardware
- dataset manifest
- codec condition
- window/hop
- p50/p95 latency
- EER/ROC-AUC/TPR@fixed-FPR where statistically meaningful
- time-to-alert where attack onset exists

If the cohort is too small for a reliable metric, explicitly label the result as a smoke test rather than presenting it as final performance.

Write both:
1. machine-readable result file
2. short Markdown summary
```

---

# 24. Definition of Done — SIH MVP

## End-to-end
- [ ] microphone/WebRTC or deterministic live-like stream works
- [ ] 0.5 s refresh after warm-up
- [ ] explicit ANALYZING state
- [ ] risk + reasons reach dashboard

## Detection
- [ ] artifact branch operational
- [ ] channel intelligence operational
- [ ] prosody/session branches only included if quality gates pass
- [ ] uncertainty/missing branches handled

## Evaluation
- [ ] codec smoke benchmark
- [ ] latency p50/p95
- [ ] time-to-alert test
- [ ] at least one mixed real→spoof scenario
- [ ] no invented benchmark values

## Product
- [ ] authenticity/context/decision risk separated
- [ ] allow / verify / hold / escalate policy
- [ ] no mandatory paid API
- [ ] offline demo path

## Privacy
- [ ] raw audio not persisted by default
- [ ] pseudonymous call IDs
- [ ] model/version logged
- [ ] license manifest maintained

---

# 25. Post-MVP Research Backlog

Only start these after the P0 release is reliable.

## R-01 — SPS poisoning ablation
Compare:
- no SPS
- SPS without self-filtering
- SPS with dual gate

## R-02 — Phoneme coherence ablation
Determine whether inter-window phoneme coherence improves:
- EER
- fixed-FPR TPR
- time-to-alert
under:
- clean
- Opus
- G.711
- narrowband

## R-03 — Codec-aware reliability learning
Replace heuristics only if enough validation data exists.

## R-04 — Encoder compression
Compare:
- PyTorch FP32
- FP16
- ONNX
- INT8
- TensorRT where appropriate

Track quality and latency together.

## R-05 — Window/hop ablation
Compare:
```text
2/1
2/0.5
4/1
4/0.5
```

Optimize for:
```text
security quality
+
time-to-alert
+
compute cost
```

## R-06 — Leave-one-generator-out evaluation
Use generator-disjoint testing; do not claim zero-day robustness without results.

---

# 26. North-Star Metrics

The project should optimize these jointly:

### Security
- TPR at practical low FPR
- EER
- ROC/PR-AUC
- false-negative examples

### Real-time
- time-to-alert
- p50/p95 compute latency
- dropped frames
- realtime factor

### Robustness
- degradation under Opus/G.711/8 kHz
- per-language gap
- noisy-channel failure rate

### Product
- false-positive action cost
- explicit uncertainty
- offline readiness
- no raw-audio persistence

---

# 27. Final Principle

When choosing between:

```text
a complicated model that looks impressive
```

and

```text
a measurable streaming system that works under realistic telephony degradation
```

choose the second one.

STRIVE wins when it can prove:

> **We detect and react during the call, we know when the channel weakens our evidence, and we can show exactly how fast and how reliably the system behaves.**
