# Model card — STRIVE prototype v0.1

| Field | Current evidence |
|---|---|
| Intended use | Research/education and architecture verification for SIH 26104 |
| Validated runtime mode | DSP engineering surrogate with actual FAISS and streaming engine |
| Default feature version | `dsp-surrogate-v1` |
| Reference data | 48 procedural signals; two synthetic signal families, 24 examples each |
| Demonstration data | Separate fixed seeds; 40-second stable, switched, suspicious-start and silent signals |
| Human voice data | None bundled or evaluated |
| Neural model execution | Not completed in this environment |
| Acoustic profiling | Measured 24-value surrogate; not an established speaker identity representation |
| Risk calibration | None; scores are anomaly indices |
| EER / ROC-AUC / FPR / FNR | Not measured on speech; intentionally not reported for fixtures |
| Indian-language accuracy | Not measured; routing tags are not tested language support |
| Codec robustness | Augmentation script provided; speech detection under codecs unmeasured |
| Generalization | Unseen-generator voice-cloning detection unmeasured |
| Runtime measurements | `evidence/benchmark.json`, single CPU fixture run only |
| Privacy | No live raw audio persistence; per-call vectors transient; audit whitelist |
| Known failures | Fusion can suppress high global evidence; slow switch alert; boundary-content confounding; false trust if bootstrap is spoofed but global retrieval is fooled |

Research CM choice is NII MMS-300M or XLS-R-2B, paired with the supplied XLSR phoneme model and optional VoxLingua language model. Research startup verifies bundle hashes. `model_version` identifies the CM; `pipeline_version` hashes the complete sealed manifest for profile/phone/language traceability.

Do not use this prototype to label people as fraudulent, certify a call as genuine, or authorize real transactions. The mock verification flow is not actual MFA, callback verification, or bank integration.
