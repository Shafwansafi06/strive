# Reproducible STRIVE study

This release implements the study machinery; its software checks do not establish detector accuracy. No pretrained-model ablation numbers were produced in this workspace. The neural weights, labelled corpora and target GPU were unavailable. The procedural demo is a separate architecture check.

## Prepare one machine

Use Python 3.12 and the pinned demo/research requirements. Install FFmpeg for MP3/Opus/G.711 corpus preparation. Follow `MODELS.md` to download revision-pinned models, export NII in a separate Python 3.10 Fairseq environment and seal the bundle. Use `--include-language` during preparation; research startup requires the local SpeechBrain language model by default.

```bash
python -m pip install -r requirements-demo.lock
python -m pip install -r requirements-research.txt
python scripts/prepare_models.py --download --variant mms-300m --include-language
# Follow MODELS.md for the separate export environment, then return here.
python scripts/prepare_models.py --seal
```

Model loading verifies local file hashes before inference. A missing asset raises its required path. NII class 0 is spoof; the exported class-0 probability is metadata. Track 1 uses the fraction of spoof neighbours in the CM index, not this classifier probability. Reference IDs encode the CM hash; complete pipeline IDs also encode the bundle and acoustic backend.

The CTC processor disables text-to-phoneme conversion because it consumes audio only; a system espeak text backend is unnecessary for inference.

The adapter runs frozen CM, CTC phoneme and vocal-profile branches in a thread pool. CPU or CUDA is selected explicitly; concurrency does not guarantee lower latency on a particular GPU. SpeechBrain language ID runs once near the five-second bootstrap boundary. Low-confidence or unsupported language labels route as `und`.

## Obtain corpora

The downloader supports explicit HTTPS downloads, published checksums and safe archive extraction. Downloaded speech is kept outside the source release.

```bash
python scripts/download_data.py asv2019 --download --root data/corpora/asv2019 --output data/manifests/asv2019
python scripts/download_data.py asv2021 --download --root data/corpora/asv2021 --output data/manifests/asv2021
```

ASVspoof2019 uses its official train → reference, dev → validation, eval → test assignment. Preparation checks speaker, source and audio-hash separation. ASVspoof2021-DF uses full official metadata and emits the `eval` subset as test; provide a separate reference corpus. Do not mix masked stage-1 keys with full metadata. Keep `LA_...` speaker IDs consistent across 2019/2021 to catch shared speakers. Source IDs alone cannot establish cross-corpus derivative identity; maintain provenance when adding codecs or creating mixed calls.

The 2021 download is about 34.5 GB compressed. The script requires three times archive size as free space before downloading and streams multipart extraction without creating a combined copy. Downloads and extraction were not executed here. Local archives can be used with `--archive`, and already-extracted directories need no `--download` flag.

Common Voice requires an authorized archive from Mozilla Data Collective; this script does not automate accepting terms or obtaining credentials. For an existing archive:

```bash
python scripts/download_data.py commonvoice --archive /path/to/commonvoice.tar.gz --root data/corpora/cv --output data/manifests/cv --languages en --indian-only
```

For a user-authorized HTTPS URL use `--download --url URL --checksum sha256:HASH`. An optional `COMMONVOICE_DOWNLOAD_TOKEN` supplies a bearer token to that host; redirects to a different host with a token are refused. Direct signed download URLs need no token. Exact accent labels can be configured with `--accent-labels`.

`--indian-only` filters self-reported accent metadata (default label `indian`), not nationality. The English dataset's label may include broader South Asian accents. Unknown accents are excluded. Use `--languages hi,ta,bn` without the accent filter for those locales; language is not evidence of a speaker's country. Speaker hashing creates deterministic disjoint 60/20/20 assignments; small subsets may not populate every split. Common Voice contains genuine speech only: it cannot independently yield EER or supply a two-class reference index. Consented, labelled spoof samples in the same languages and channels are still required.

Dataset preparation hashes every recording. Keep audio and manifests locally; comply with the originating corpus terms. Do not publish Common Voice audio in your GitHub repository. ASVspoof manifests deliberately identify corpus terms rather than inventing a permissive license.

## Build and evaluate

```bash
python scripts/build_index.py data/manifests/asv2019/reference.csv --models models --output data/reference.npz --device cuda
python scripts/run_ablation.py --manifest data/manifests/asv2019/test.csv --sweep-manifest data/manifests/asv2019/validation.csv --index data/reference.npz --models models --device cuda --output evidence/ablation
```

This writes `ablation_report.json` and `ablation_table.md`, including all seven configurations and language/codec/generator subtables. The default validation sweeps test five alpha values, five neighbour counts, five global gates and four weight presets, one factor at a time. Each case reruns calls with fresh bootstrap/SPS state. These are 19 additional corpus passes and can take substantial time. Without a validation manifest, only the main seven score configurations run; the report explicitly records that sweeps were not run.

The seven configurations are **conditional score-fusion ablations**: identical extracted features and trust history are replayed through independent masks/EMAs. Track 1 still gates SPS admission even in `session_only` or `track23`. This answers whether a track contributes to score fusion; it does not establish an independently deployable detector without that model. Running seven duplicate neural passes would not change these deterministic masked scores and would give misleading compute comparisons.

Every primary configuration applies the same alpha EMA, including Track 1 alone. Unsmoothed means are retained in `raw_scores` for the literal raw-track comparisons. Single-track scores use their one available track at every age; paired scores use the masked, renormalized age schedule. Missing tracks produce abstentions, not zero-risk recordings. The JSON retains both available-cohort and common-cohort metrics. Compare coverage, class counts and common-cohort EER together: rejected bootstrap calls can otherwise make SPS appear artificially strong.

Generator slices reuse genuine controls matching each attack's language/codec strata; a spoof-only slice cannot have EER. Results lacking either scored class remain `N/A`. TPR@1%FPR is an empirical step on the observed ROC; fewer than 100 genuine clips cannot resolve 1% FPR adequately. EER uses linear interpolation at the ROC crossing. Brier/ECE are descriptive errors of uncalibrated anomaly scores, not evidence of calibrated fraud probabilities.

Parameter selection belongs on validation. The main report evaluates the specified base configuration on test; it does not auto-select a winner. After choosing parameters, freeze them and run a final test evaluation once. For inferential claims, add speaker-level confidence intervals and an independently collected test set; a table of point estimates alone does not prove general improvement.

Use the lower-level evaluator for exact choices:

```bash
python scripts/evaluate.py data/manifests/asv2019/test.csv --models models --index data/reference.npz --device cuda --alpha 0.7 --k 20 --global-gate 0.3 --weights proposed --ablation-table
```

Default language routing is predicted by SpeechBrain. `--language-routing manifest` is an explicitly labelled oracle/hint comparison; `--skip-language-model` is allowed only with that routing. Do not present hinted routing as language-ID accuracy.

## Streaming attacks and duration

An ASVspoof utterance may be too short for four seconds of voiced evidence, five-second bootstrap or the fifteen-second session weight transition. Preserve such abstentions. Concatenating unrelated short utterances does not create an authentic long-call benchmark.

For consented genuine-to-spoof calls, add `attack_onset_s` to the manifest. Each score configuration records first warning/alert, post-onset warning/alert, pre-onset false alarms, nonnegative detection/alert delay and undetected attacks. A pre-onset false alarm is not a negative detection delay. Alert time is measured from the start of the clip; detection delay is measured from attack onset. Clip EER averages eligible windows and can dilute brief attacks, so report streaming delay and misses alongside it.

Maintain the original source and speaker ID across G.711/Opus variants. Use `scripts/augment.py --help` for actual codec round trips. Keep generators intended for holdout out of reference and validation data. `--holdout-generator` checks reference/test separation; the checkpoint may still have seen that generator during NII training. Report that scope accurately.

## Latency and acceptance

The runner measures feature p50/p95 and full-window p50/p95/max on the actual machine, including first-window inference. The DSP comparison uses up to 100 real-corpus windows and is explicitly a feature-only surrogate measurement. Add another genuinely prepared neural bundle/index with:

```bash
python scripts/run_ablation.py --manifest data/manifests/asv2019/test.csv --models models --index data/reference.npz --device cuda --compare XLS-R-2B models-2b data/reference-2b.npz
```

Missing variants are `N/A`; no MMS-to-2B extrapolation is made. Model loading and disk decoding are excluded from per-window timing. Record GPU, dependency versions, batch size, corpus and model hashes with any latency claim. Full pipeline time includes once-per-call language inference and is the relevant streaming budget.

The real-model test automatically skips when `cm.pt` is absent. When it is present it requires all dependencies, a genuine 20+ second audio clip and a matching real reference index; missing inputs cause failure. It checks all three tracks and a maximum one-second window budget, including cold inference. It never relaxes trust gates to manufacture a passing result.

Linux:

```bash
STRIVE_RESEARCH_MODELS=models STRIVE_RESEARCH_INDEX=data/reference.npz STRIVE_RESEARCH_AUDIO=/path/to/genuine-call.wav STRIVE_DEVICE=cuda python -m pytest tests/test_research_smoke.py -q
```

Windows PowerShell:

```powershell
$env:STRIVE_RESEARCH_MODELS = 'models'
$env:STRIVE_RESEARCH_INDEX = 'data/reference.npz'
$env:STRIVE_RESEARCH_AUDIO = 'C:\speech\genuine-call.wav'
$env:STRIVE_DEVICE = 'cuda'
python -m pytest tests/test_research_smoke.py -q
```

`STRIVE_STRIDE_BUDGET_MS` can explicitly select another acceptance target (e.g. 200); changing the budget changes the tested claim. Neither a one-second pass nor a DSP timing establishes sub-200 ms on a T4.

## Source references

- [NII MMS model](https://huggingface.co/nii-yamagishilab/mms-300m-anti-deepfake) and [NII XLS-R model](https://huggingface.co/nii-yamagishilab/xls-r-2b-anti-deepfake): dimensions, class semantics and checkpoint licensing.
- [ASVspoof2019 record](https://zenodo.org/records/6906306) and [ASVspoof2021-DF record](https://zenodo.org/records/4835108): official archives.
- [Official ASVspoof2021 evaluation package](https://github.com/asvspoof-challenge/2021/blob/main/eval-package/README.md): full metadata format and key checksums.
- [Mozilla Data Collective](https://mozilladatacollective.com): authorized Common Voice releases and corpus-specific terms.
