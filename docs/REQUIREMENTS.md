# MVP requirement traceability

Status meanings: **Implemented** = code and relevant automated checks exist; **Research path** = adapter/scripts exist but pretrained execution is not validated here; **Open** = not completed. A fixture replay does not satisfy a detection-quality release gate.

| Requirement from DOCX | STRIVE implementation | Status / boundary |
|---|---|---|
| FR-01 live ingestion | Browser AudioWorklet → PCM WebSocket; REST PCM | Implemented API; physical microphone/browser permission flow not exercised here |
| FR-02 preprocessing | 16 kHz mono, 2 s windows / 1 s stride; research WebRTC VAD | STRIVE timing intentionally overrides DOCX's 4 s / 0.5 s; demo uses an energy activity surrogate |
| FR-03 evidence state | Null risk and Analyzing until enough unique active audio | Implemented; tested silence, warm-up and failure paths |
| FR-04 calibrated artifact detection | NII frozen CM → language FAISS reference ratio | Research path; calibrated voice-clone detection not validated |
| FR-05 prosody | 62 measured acoustic descriptors in research Track 2; legacy 24 in demo | Implemented features; not the separate DOCX prosody branch; Vox-Profile remains open |
| FR-06 enrolled identity | STRIVE zero-enrollment within-call store | Cross-session enrollment intentionally omitted |
| FR-07 channel/replay | Overlap-seam coherence; offline codec augmentation script | Supporting cue implemented; replay detector quality unvalidated |
| FR-08 fusion | Three-track availability mask, exact age schedule and EMA | Implemented; probability calibration remains open |
| FR-09 context risk | Amount, urgency, beneficiary and privileged-request metadata | Implemented; ASR/context understanding not included |
| FR-10 policy | Continue, verify, hold and recorded mock verification | Implemented mock; no actual bank/MFA/callback integration |
| FR-11 explanations | Reason codes, individual scores and weights | Implemented |
| FR-12 dashboard | Risk chart, three tracks, SPS and workflow controls | Implemented; JavaScript syntax checked, browser visual QA not performed |
| FR-13 offline | Local demo/API; self-contained replay; local-only research load | Demo verified; neural offline run pending model bundle |
| FR-14 Indian languages | Routing tags and per-language evaluation scripts | Language accuracy, code-mix robustness and live Indic demo remain open |
| FR-15 interfaces | Versioned REST and WebSocket event schema | Implemented; gRPC not included |
| FR-16 alerts | In-app events and audit | Implemented baseline; no outgoing webhook/email/SMS |
| FR-17 privacy | Raw audio transient; audit whitelist; profile destruction | Implemented and tested; no legal certification claim |
| FR-18 admin | Config file, startup env settings, context controls | Basic implementation; role-based admin UI not included |
| FR-19 observability | Health, readiness, counters and stage timings | Implemented; full monitoring stack not included |
| FR-20 enterprise adapters | Documented API integration seam | SIP/Asterisk, CRM, telecom and collaboration adapters remain open |

## Release decision

This is suitable for **inspecting and testing the architecture mechanics**. It does **not** meet the DOCX's complete detection-quality/SIH release gate yet. Required remaining evidence: exact Vox trait model selection or an approved architecture change, validated pretrained inference, consented genuine/spoof reference and held-out speech, calibration, per-language/code-mixed and codec metrics, unseen-generator testing, actual reference-hardware latency, and a microphone demo on the target laptop.

Changing the demo label from “engineering fixture” to “real/fake voice detection” without those steps would misrepresent the evidence.
