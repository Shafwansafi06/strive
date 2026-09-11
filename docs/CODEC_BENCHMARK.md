# CODEC ROBUSTNESS — augmentation audit and condition matrix

Tickets: CODEC-01 (audit), CODEC-02 (bitrate matrix), CODEC-03 (paired manifest).

Tool: `scripts/augment.py`. It is **offline evaluation preprocessing only**. The server
never calls it, and it is not part of the live audio path.

```bash
python -E scripts/augment.py list
python -E scripts/augment.py one clean.wav out.wav --condition opus_16k
python -E scripts/augment.py matrix --manifest data/manifest.csv \
        --out-dir data/degraded --out-manifest data/manifest_matrix.csv
```

## CODEC-01 — support audit

State of the augmentation tool after this ticket:

| Requirement | Before | Now | Notes |
|---|---|---|---|
| Opus | partial — single hard-coded 16 kbps | **yes** | Full 6/12/16/24/32 kbps ladder |
| G.711 μ-law | yes | **yes** | 8 kHz `pcm_mulaw` round trip |
| G.711 A-law | **no** | **yes** | Added; `pcm_alaw` |
| Narrowband | yes | **yes** | 8 kHz resample round trip, no companding |
| Noise | yes | **yes** | Named 20/10/5 dB SNR conditions |
| Packet loss | yes | **yes** | Named 1/3/5% conditions, 20 ms erasure granularity |
| Bitrate matrix | **no** | **yes** | CODEC-02 |
| Paired manifest | **no** | **yes** | CODEC-03 |
| Deterministic naming | **no** | **yes** | `<out_dir>/<condition>/<source_id>.wav` |
| Explicit codec failure | partial — `check=True` only | **yes** | Non-zero exit *or* empty output raises with ffmpeg stderr |
| Batch mode | **no** | **yes** | `matrix` subcommand |

### Defect found and fixed during the audit

`degrade()` mutated the caller's array in place. The packet-loss step writes
`x[start:start+320] = 0`, and the no-codec path returned the input array unchanged
rather than a copy. In `build_matrix` a single decoded source array is reused across
every condition, so each condition would have inherited the previous condition's
erasures, and a caller's clean audio was silently destroyed. Now `degrade()` always
copies at entry. Regression test: `tests/test_codec.py::test_degradation_is_deterministic_for_a_seed`.

## Environment

| Item | Value |
|---|---|
| ffmpeg | 6.1.1-3ubuntu5 |
| Encoders present | `libopus`, `pcm_mulaw`, `pcm_alaw` |
| Hardware | i5-1235U, 12 cores, CPU only |
| Seed | 26104 (`DEFAULT_SEED`), overridable with `--seed` |

If `libopus` is absent from a local ffmpeg build, the Opus conditions raise rather than
degrading silently. Tests skip on missing ffmpeg/libopus rather than reporting a pass.

## CODEC-02 — registered conditions, measured

Measurements below are on a 4 s synthetic **engineering fixture** (harmonics at 200 /
1400 / 6200 Hz with pauses), not speech. They exist to prove the augmentation legs and
the channel metrics respond as expected. **They are not detection results.**

Channel values come from `strive/channel.py` over the first 2 s window.

| Condition | Degradation | Bandwidth (Hz) | SNR (dB) | Clipping | Channel quality | Encode (ms) |
|---|---|---:|---:|---:|---:|---:|
| `clean` | unmodified | 6219 | 60.0 | 0.0000 | 0.946 | 0 |
| `opus_6k` | opus@6k | 1438 | 51.2 | 0.0000 | 0.750 | 244 |
| `opus_12k` | opus@12k | 6219 | 54.8 | 0.0000 | 0.946 | 343 |
| `opus_16k` | opus@16k | 6219 | 48.8 | 0.0000 | 0.946 | 216 |
| `opus_24k` | opus@24k | 6219 | 53.4 | 0.0000 | 0.946 | 206 |
| `opus_32k` | opus@32k | 6219 | 54.6 | 0.0000 | 0.946 | 205 |
| `g711_ulaw` | G.711 μ-law | 1438 | 60.0 | 0.0000 | 0.750 | 169 |
| `g711_alaw` | G.711 A-law | 1438 | 60.0 | 0.0000 | 0.750 | 157 |
| `narrowband_8k` | 8 kHz round trip | 1438 | 60.0 | 0.0000 | 0.750 | 152 |
| `noise_20db` | 20 dB SNR | 6219 | 28.8 | 0.0000 | 0.946 | 2 |
| `noise_10db` | 10 dB SNR | 7125 | 19.3 | 0.0000 | 0.915 | 2 |
| `noise_5db` | 5 dB SNR | 7688 | 15.1 | 0.0000 | 0.852 | 3 |
| `loss_1pct` | 1% erasure | 6219 | 60.0 | 0.0000 | 0.946 | 0 |
| `loss_3pct` | 3% erasure | 6219 | 60.0 | 0.0000 | 0.946 | 0 |
| `loss_5pct` | 5% erasure | 6219 | 60.0 | 0.0000 | 0.946 | 0 |

Encode timings are wall-clock for a 4 s clip on CPU, single run. They bound how long a
matrix build takes; they are not inference latency.

### What the channel metrics do and do not catch

**Caught.** Every narrowband leg (G.711 μ-law, G.711 A-law, 8 kHz resample, and Opus at
6 kbps, which drops to narrowband internally) collapses bandwidth 6219 → 1438 Hz and
quality 0.946 → 0.750. Additive noise is tracked monotonically: 20/10/5 dB SNR reads
28.8/19.3/15.1 dB.

**Not caught — packet loss.** All three loss conditions read identically to clean:
quality 0.946, discontinuity unchanged. 20 ms zero-erasures do not move the per-window
aggregate energy, centroid or noise floor enough to register. This is a real limitation
of CH-05 as implemented, recorded rather than tuned around. Two consequences:

1. `packet_loss_rate` on `ChannelState` must be supplied by the transport. It is not
   inferred from the waveform, and it stays `null` when the transport does not report it.
2. If waveform-side loss detection is wanted later, it needs a dedicated erasure
   detector (runs of exact zeros / short-term energy dropouts), not a tweak to the
   existing continuity score. Not in scope for P0.

**Also note.** Bandwidth is content-dependent. This fixture's energy is dominated by its
200 Hz fundamental, so the 99% rolloff sits at 1438 Hz for narrowband rather than near
the 3.4 kHz channel cutoff. Bandwidth alone cannot distinguish "narrowband channel" from
"low-pitched or quiet speaker". It is a channel hint, not a codec classifier.

## CODEC-03 — paired manifest

`matrix` writes a CSV that extends the existing `scripts/build_index.py` manifest schema
rather than replacing it. Required columns are unchanged
(`path, label, language, speaker_id, generator, codec, source_id, split, license`), with
two additions:

| Column | Meaning |
|---|---|
| `condition` | Registered condition name, e.g. `opus_16k` |
| `condition_detail` | Human-readable description, e.g. `opus@16k` |

Guarantees, all enforced by `validate_rows()` before anything is written:

- The clean original and every derived variant **share `source_id`, `label`,
  `speaker_id` and `language`**. Only `path`, `codec`, `condition` differ.
- A `(source_id, condition)` pair cannot repeat.
- One `source_id` cannot carry two different labels, speakers or languages.

**Split on `source_id` or `speaker_id`, never on `path`.** Splitting on path would put
`clean/src0.wav` and `opus_16k/src0.wav` on opposite sides of the split and leak the
same recording into both. `scripts/build_index.py::assert_disjoint` already checks
`sha256`, `source_id` and `speaker_id` overlap; the augmented manifest is compatible
with it unchanged.

## CODEC-04 smoke set

The default `--conditions` is the ticket's minimum set:

```
clean, opus_16k, opus_32k, g711_ulaw, narrowband_8k, noise_10db
```

Use `--all` for the full 15-condition matrix, `--limit N` for a quick pass.

## Not yet done

- **CODEC-04 has not been run.** It needs a real licensed/consented corpus. `data/`
  contains only `manifest.example.csv`; no audio ships with this repository.
- No EER / ROC-AUC / score-distribution numbers exist for any codec. Nothing in this
  document is a detection metric, and none will be invented before the corpus exists.
- CODEC-05 (ΔEER tables) and CODEC-06 (embedding preservation) depend on CODEC-04.
