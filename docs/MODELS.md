# Research models: preparation, contracts and limits

## Current presentation status

The operational presentation runtime is `DEMO DSP` with `dsp-surrogate-v1` and a
48-vector procedural FAISS index. It is shown in the UI as **not a neural accuracy
benchmark**. No NII, XLSR phoneme or SpeechBrain language weights are present in
this repository or were executed for the final presentation validation.

The preferred research prototype remains the frozen NII MMS-300M countermeasure
path because its 1,024-dimensional export is more practical for a presentation
laptop than XLS-R-2B. This preference is operational, not a measured accuracy
claim. Research startup checks the sealed manifest hash, exact `input_samples`
against active window geometry, CM dimension, every pinned dependency, fixture
index prohibition and extractor/index ID compatibility. Any mismatch fails startup;
there is no silent DSP fallback.

## Verified upstream facts

| Component | Source / finding |
|---|---|
| XLS-R-2B CM | The [NII model card](https://huggingface.co/nii-yamagishilab/xls-r-2b-anti-deepfake) specifies a 1,920-dimensional encoder, rather than the supplied document's 1,024. |
| MMS-300M demo-size CM | The [NII MMS model card](https://huggingface.co/nii-yamagishilab/mms-300m-anti-deepfake) uses 1,024 dimensions. Class 0 is fake, class 1 real. |
| NII licensing | Both model cards specify **CC BY-NC-SA 4.0** for checkpoints. The [upstream project](https://github.com/nii-yamagishilab/AntiDeepfake) separately lists BSD-3-Clause for its code. Do not treat these weights as Apache-licensed government/commercial deployment assets. |
| Phoneme extractor | [facebook/wav2vec2-xlsr-53-espeak-cv-ft](https://huggingface.co/facebook/wav2vec2-xlsr-53-espeak-cv-ft); local CTC predictions and hidden-state pooling are used. |
| Language identifier | [SpeechBrain VoxLingua107](https://huggingface.co/speechbrain/lang-id-voxlingua107-ecapa) supplies language identification. Country/accent is not inferred from it. |
| Vox-Profile | The [repository](https://github.com/tiantiaf0627/vox-profile-release) describes an English speech-trait benchmark with multiple model wrappers. It cautions about predictions below three seconds. A universal 283-value two-second API was not established. |

The source-reported runtime and accuracy numbers are not this project's measurements. No claim of zero-day robustness, multilingual fairness or sub-200 ms neural inference is made.

## What was executed here

DSP surrogate extraction, actual FAISS, all streaming/policy APIs and the procedural scenarios. Neural weights were not available locally; a direct model-file network attempt could not complete under this environment's network access controls. No NII export, pretrained phoneme inference, pretrained language inference, or Vox-Profile checkpoint inference is recorded as passing.

The adapter code is provided for running those experiments on your own machine. Dependency compatibility and export parity must be checked there. Missing weights are an explicit blocker, not a trigger for random-weight inference.

## Prepare NII and XLSR

The application uses Python 3.12. NII's Fairseq export requires a **separate Python 3.10 environment**, because legacy Fairseq is not a drop-in dependency for this application's runtime. A GPU is optional for export but strongly useful for large-model experimentation. The 2B option needs substantially more memory than the 300M option; no laptop-fit guarantee is provided.

1. In the application environment, install `requirements-research.txt`. For CPU-only PyTorch, use PyTorch's appropriate CPU wheels for your platform before installing the remaining requirements.
2. Run the explicit online preparation step:

```bash
python scripts/prepare_models.py --download --variant mms-300m --include-language
```

`revisions.json` records exact upstream commit SHAs. Subsequent preparations reuse those revisions. Source files land under `models/nii-source`, `models/phoneme` and optionally `models/language`.

3. Create a separate export environment. These are the legacy dependencies expected by the exporter, not a claim that this environment was tested here:

```bash
conda create -n strive-export python=3.10 -y
conda activate strive-export
python -m pip install 'pip<24.1' 'setuptools<70'
python -m pip install torch==2.6.0 torchaudio==2.6.0 numpy==1.26.4 fairseq==0.12.2 safetensors==0.5.3
python scripts/export_nii.py --variant mms-300m --weights models/nii-source/model.safetensors --output models/cm.pt
```

The exporter reconstructs the published NII architecture, strictly loads all safetensor keys, freezes it, exports a fixed **32,000-sample** input contract, and compares the export against eager inference. A parity failure stops export. It writes `cm-export.json`, including source/output hashes. It does not train a classifier.

Use `--variant xls-r-2b` in both preparation and export to try the full model. Never use MMS weights with the 2B configuration or reuse an index from a different model/hash.

4. Return to the application environment and seal the local bundle:

```bash
python scripts/prepare_models.py --seal
```

5. Provide a reference CSV using the header in `data/manifest.example.csv`, with both genuine and spoof speech, then build the index:

```bash
python scripts/build_index.py path/to/reference.csv --models models --output data/reference.npz
python scripts/start.py --research
```

Runtime uses local-only loads and checksums. `scripts/start.py` enables offline Hugging Face/Transformers environment flags. No endpoint downloads models or invokes a paid API.

## Vox-Profile decision

The default research configuration explicitly uses `profile_backend: acoustic`, supplying 62 measured acoustic descriptors (legacy features, MFCC statistics, spectral statistics, energy dynamics, jitter and shimmer). This is a documented substitution for the missing 283-dimensional API, not an implementation of that claim.

`profile_backend: vox` supports explicit, pre-exported, frozen trait modules. Each TorchScript module must accept `[1,32000]` 16 kHz float input and return a finite flat trait vector. Place exports under `models/vox/` and describe them in `models/vox/spec.json` using objects with `trait`, `file` (relative to `models/vox/`, with model-root-relative `vox/...` also accepted) and `dimension`. Required traits are `pitch`, `volume`, `clarity`, `rhythm` and `texture`; each is independently normalized before concatenation. Dimensions come from the actual exports; they are not padded to a claimed 283.

After adding verified exports, seal the bundle again. The server refuses Vox mode if required traits or hashes are absent. **Those trait exports are not supplied**, because the source files do not specify the exact wrappers/checkpoints or justify two-second operation. Deciding those components and validating short Indic speech remains necessary to test the full proposed neural architecture.

## Evaluation

Each manifest row requires `path,label,language,speaker_id,generator,codec,source_id,split,license`. Label 0 is genuine; label 1 spoof. `source_id` must stay identical for augmentations of the same source. Index rows use `reference`; evaluation rows use `test`. Paths are relative to the CSV. Provide consented, licensed data. No speech dataset or cloned voice is bundled.

```bash
python scripts/evaluate.py path/to/test.csv --index data/reference.npz --models models
python scripts/evaluate.py path/to/test.csv --holdout-generator YOUR_HELD_OUT_GENERATOR
```

The evaluator rejects reference/test overlap in audio hash, source ID and speaker ID. The holdout argument rejects a generator present in the reference corpus; it does **not** prove that generator was absent from NII's original pretraining/post-training data. Metrics include abstention counts, ROC-AUC, PR-AUC, an empirical EER estimate, TPR at 1% FPR, threshold-specific FPR/FNR, Brier error, ECE, language/codec slices, alert time and a global-only comparison.

Clip scores average eligible windows. Mixed attacks should additionally use onset-labelled streaming scenarios to measure detection delay. Keep short clips that produce no score in the abstention report. The supplied score is uncalibrated; a reference ratio or EMA value is not a probability of fraud.

Offline codec preparation is available through `scripts/augment.py`. It implements actual FFmpeg G.711 or Opus round trips, narrowband resampling, seeded additive noise and zero-filled packet loss. It explicitly writes an evaluation artifact at the requested path and is separate from live privacy defaults.
