# Presentation audio

STRIVE ships no human recordings. The built-in buttons use deterministic
procedural signals and are labelled **DEMO / SYNTHETIC SCENARIO**. They exercise
the pipeline and workflow; they are not evidence of deepfake accuracy.

To add presentation recordings without changing code, obtain explicit consent or
a redistribution-compatible license, then run:

```bash
python scripts/import_demo_audio.py --genuine /path/genuine.wav \
  --spoof /path/spoof.wav --mid-call /path/mid_call_attack.wav \
  --license "your exact license/consent reference" \
  --provenance "who created/provided the recordings"
```

The script validates every file through the same decoder, copies it to the
ignored `data/demo/audio/` directory, and writes the ignored
`data/demo/manifest.csv`. It does not infer labels or onset times. Review the CSV
before presenting. Set `--attack-onset-sec` to the construction boundary of the
mid-call recording; never use a detector estimate as ground truth.

WAV and FLAC work through libsndfile. MP3/M4A and other formats require FFmpeg.
Do not use public-figure impersonations, private calls, or data without consent.
