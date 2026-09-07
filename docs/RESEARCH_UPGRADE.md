# STRIVE 0.2.0 delivery and verification

The research upgrade adds the nine requested implementation areas. It does **not** establish that the ensemble beats Track 1. That outcome requires actual model inference on appropriate held-out speech, and must be reported even if the ensemble loses.

## Changes

| Requested area | Delivered implementation |
|---|---|
| Research module | Included `strive/models` package; checksummed local NII TorchScript, XLSR CTC processor/hidden-state pooling, acoustic/Vox backends, SpeechBrain confidence mapping, frozen parallel inference and explicit cleanup. |
| Seven-way evaluation | All singletons, pairs and full fusion; independent comparable EMAs, raw means, abstentions, common-cohort comparison and generator slices with genuine controls. |
| Documentation | Corrected copy of the supplied architecture: MMS 1,024 / XLS-R 1,920 dimensions, CC-BY-NC-SA-4.0 NII checkpoint licenses, exact EMA arithmetic and `None` cold-start semantics. |
| Study runner | JSON/Markdown report, language/codec/generator tables, separate validation sweeps, actual latency comparisons for available bundles. |
| Dataset tooling | Official ASVspoof downloads/checksums, protocol conversion, speaker-disjoint validation, authorized Common Voice archive/URL support and explicit accent filters. |
| Acoustic profile | 62 dimensions from NumPy/SciPy, including 26 MFCC statistics, spectral features, energy dynamics, jitter, shimmer and pause ratio. Demo retains the original 24-dimensional output. |
| Runtime fixes | Persistent incremental FAISS SPS indexes; eviction-only rebuild; parallel model jobs; missing session evidence stays unknown. |
| Research smoke | Real audio/model/index acceptance checks plus a one-second maximum window budget; skips when NII weights are absent, fails honestly on unmet gates when enabled. |
| Research startup | Explicit research config/mode, offline flags, portable path handling and Uvicorn launch. Windows execution still requires checking on Windows. |

## Verification in this environment

- **44 software tests passed**, including the original 32; **1 real-model test skipped** because no local NII weights were available.
- The demo was regenerated through the Python API. Mid-call change: warning at 22 s and alert at 36 s. Suspicious start: bootstrap blocked, alert at 8 s. Silence: no acoustic score. These are procedural architecture checks, not deepfake accuracy results.
- A live Uvicorn HTTP smoke check passed all 39 windows and the mock hold → verification → release flow.
- AudioWorklet tests passed for 16 kHz, 44.1 kHz and 48 kHz input; JavaScript syntax checks passed.
- The release builder verifies every archived file against SHA256SUMS, imports `ResearchExtractor` from the extracted folder, checks five command help interfaces and runs the entire suite from that fresh extraction. Its receipt is delivered alongside the archive.
- The actual Transformers 4.51.3 audio processor passed a local configuration test without an espeak text backend; this verifies preprocessing compatibility, not pretrained inference.
- Two upstream Starlette/httpx deprecation warnings remain; they do not fail the suite.

The first release's ZIP filter erroneously removed the source `strive/models/` directory along with root model weights. This release fixes that error, adds a regression test and makes extracted-archive verification a CI gate. Root weights and private corpora remain outside the archive.

## Experiments still blocked

There is no local pretrained NII/phoneme/language bundle, real labelled evaluation corpus or CUDA GPU available to this build. Direct model access could not complete under the environment's network controls. Consequently, no actual neural ablation EER/AUC, Hindi/Tamil spoof performance, held-out-generator generalization, Vox trait inference or T4 latency result is supplied. No values were invented to fill those cells.

The real smoke test, model export parity and downloaded-corpus preparation must execute on the research machine. The code includes an acoustic alternative to Vox; exact frozen Vox trait exports are still external inputs. This is a delivered implementation and reproducible experiment workflow, not a completed publishable research study.

To run the study, follow `RESEARCH_STUDY.md` and `MODELS.md`. Supply a GPU machine, the checksummed model bundle, speaker-disjoint reference/validation/test manifests and consented genuine-to-spoof long calls. Common Voice alone supplies only genuine clips; short ASVspoof utterances may abstain before STRIVE's warm-up and do not establish mid-call performance.

## Demo and source

Open `STRIVE_Demo.html` for the portable replay, or install `requirements-demo.lock` and run `python scripts/start.py` for the microphone/upload dashboard at http://127.0.0.1:8000. The project includes all application code, tests, CI and preparation scripts. Model weights and corpora must be obtained separately. The README contains GitHub push commands; no external repository was created or pushed.
