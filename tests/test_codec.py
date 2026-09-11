"""CODEC-01/02/03 acceptance: condition matrix, determinism, paired manifest."""
import csv
import shutil
import subprocess
import sys
from pathlib import Path
import numpy as np
import pytest
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from augment import (CONDITIONS, SMOKE_CONDITIONS, Condition, apply_codec, build_matrix,
                     degrade, output_path, validate_rows, write_manifest)
from strive.audio import RATE

FFMPEG = shutil.which("ffmpeg") is not None
needs_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg not installed")


def speech_like(seconds=2.0):
    t = np.arange(round(seconds * RATE)) / RATE
    envelope = (np.sin(2 * np.pi * 2.5 * t) > -.3).astype(np.float32)
    return (envelope * (.30 * np.sin(2 * np.pi * 200 * t) + .15 * np.sin(2 * np.pi * 1400 * t)
                        + .06 * np.sin(2 * np.pi * 6200 * t))).astype(np.float32)


def has_encoder(name):
    if not FFMPEG:
        return False
    out = subprocess.run(["ffmpeg", "-hide_banner", "-codecs"], capture_output=True, timeout=30)
    return name in out.stdout.decode("utf-8", "replace")


# ------------------------------------------------------- CODEC-02 bitrate matrix

def test_required_opus_bitrate_ladder_is_registered():
    for kbps in (6, 12, 16, 24, 32):
        condition = CONDITIONS[f"opus_{kbps}k"]
        assert condition.codec == "opus" and condition.bitrate_kbps == kbps


def test_required_condition_families_are_registered():
    for name in ("clean", "g711_ulaw", "g711_alaw", "narrowband_8k"):
        assert name in CONDITIONS
    assert any(c.noise_snr_db is not None for c in CONDITIONS.values())
    assert any(c.packet_loss for c in CONDITIONS.values())


def test_smoke_set_matches_the_ticket():
    assert SMOKE_CONDITIONS == ["clean", "opus_16k", "opus_32k",
                                "g711_ulaw", "narrowband_8k", "noise_10db"]


@needs_ffmpeg
@pytest.mark.parametrize("name", ["opus_6k", "opus_16k", "opus_32k",
                                  "g711_ulaw", "g711_alaw", "narrowband_8k"])
def test_every_codec_round_trip_produces_audio(name):
    if name.startswith("opus") and not has_encoder("libopus"):
        pytest.skip("libopus not built into this ffmpeg")
    out = degrade(speech_like(), CONDITIONS[name])
    assert len(out) > 0 and np.isfinite(out).all()
    assert np.max(np.abs(out)) <= 1.0
    assert out.dtype == np.float32


def test_clean_condition_is_a_true_passthrough():
    x = speech_like()
    np.testing.assert_array_equal(degrade(x, CONDITIONS["clean"]), np.clip(x, -1, 1))


def test_codec_failure_raises_explicitly():
    with pytest.raises(ValueError, match="Unknown codec"):
        apply_codec(speech_like(), Condition("bogus", codec="not_a_codec"))


@needs_ffmpeg
def test_codec_failure_on_bad_payload_is_reported_not_swallowed():
    """A decode leg fed garbage must raise, never return silence as if it worked."""
    from augment import ffmpeg
    with pytest.raises(RuntimeError, match="failed"):
        ffmpeg(["-f", "ogg", "-i", "pipe:0", "-f", "f32le", "pipe:1"], b"not-an-ogg-file", "test decode")


def test_degradation_is_deterministic_for_a_seed():
    x = speech_like()
    for name in ("noise_10db", "loss_5pct"):
        a = degrade(x, CONDITIONS[name], seed=7)
        b = degrade(x, CONDITIONS[name], seed=7)
        c = degrade(x, CONDITIONS[name], seed=8)
        np.testing.assert_array_equal(a, b)
        assert not np.array_equal(a, c)


def test_noise_condition_actually_lowers_snr():
    from strive.channel import snr_db
    x = speech_like()
    assert snr_db(degrade(x, CONDITIONS["noise_5db"])) < snr_db(degrade(x, CONDITIONS["noise_20db"]))


def test_packet_loss_zeroes_roughly_the_requested_fraction():
    x = np.ones(100 * 320, dtype=np.float32) * .5
    out = degrade(x, CONDITIONS["loss_5pct"], seed=1)
    lost = float(np.mean(out == 0))
    assert .01 < lost < .15  # 20 ms granularity, so it is coarse but in the right band


# ------------------------------------------------- CODEC-02 deterministic naming

def test_output_names_are_deterministic_and_sanitized():
    a = output_path(Path("/out"), "opus_16k", "spk1/clip 3")
    assert a == output_path(Path("/out"), "opus_16k", "spk1/clip 3")
    assert a.parent.name == "opus_16k"
    assert "/" not in a.name and " " not in a.name
    assert a.suffix == ".wav"


# ---------------------------------------------------- CODEC-03 paired manifest

def base_row(source_id="s1", label="0", speaker="spk1", language="hi"):
    return {"source_id": source_id, "label": label, "speaker_id": speaker,
            "language": language, "condition": "clean", "path": "x.wav",
            "generator": "none", "codec": "clean", "split": "train", "license": "CC0"}


def test_validator_catches_duplicate_source_condition_pairs():
    with pytest.raises(ValueError, match="Duplicate"):
        validate_rows([base_row(), base_row()])


def test_validator_catches_conflicting_metadata_for_one_source_id():
    a = base_row()
    b = {**base_row(), "condition": "opus_16k", "label": "1"}
    with pytest.raises(ValueError, match="Conflicting"):
        validate_rows([a, b])


def test_validator_accepts_consistent_variants():
    rows = [base_row(), {**base_row(), "condition": "opus_16k"},
            {**base_row(), "condition": "g711_ulaw"}]
    validate_rows(rows)  # must not raise


@needs_ffmpeg
def test_matrix_shares_source_id_across_every_variant(tmp_path):
    if not has_encoder("libopus"):
        pytest.skip("libopus not built into this ffmpeg")
    # Two clean sources with full provenance.
    clean = tmp_path / "clean"
    clean.mkdir()
    rows = []
    for i, (label, speaker) in enumerate([("0", "spk_a"), ("1", "spk_b")]):
        wav = clean / f"src{i}.wav"
        sf.write(wav, speech_like(), RATE, subtype="PCM_16")
        rows.append({"path": wav.name, "label": label, "language": "hi", "speaker_id": speaker,
                     "generator": "none" if label == "0" else "gen_x", "codec": "clean",
                     "source_id": f"src{i}", "split": "test", "license": "CC0"})
    manifest = clean / "manifest.csv"
    with manifest.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    conditions = ["clean", "opus_16k", "g711_ulaw"]
    produced = build_matrix(manifest, tmp_path / "degraded", conditions)

    assert len(produced) == len(rows) * len(conditions)
    for source in ("src0", "src1"):
        variants = [r for r in produced if r["source_id"] == source]
        assert len(variants) == len(conditions)
        # CODEC-03: clean and every derived variant share source_id, label, speaker.
        assert len({r["label"] for r in variants}) == 1
        assert len({r["speaker_id"] for r in variants}) == 1
        assert {r["condition"] for r in variants} == set(conditions)
        for r in variants:
            assert Path(r["path"]).is_file()

    # No split leakage: a source_id never appears under two different speakers.
    by_source = {}
    for r in produced:
        by_source.setdefault(r["source_id"], set()).add(r["speaker_id"])
    assert all(len(v) == 1 for v in by_source.values())


@needs_ffmpeg
def test_written_manifest_is_readable_and_complete(tmp_path):
    rows = [base_row(), {**base_row(), "condition": "opus_16k"}]
    target = tmp_path / "m.csv"
    write_manifest(rows, target)
    with target.open(newline="") as f:
        back = list(csv.DictReader(f))
    assert len(back) == 2
    for column in ("source_id", "label", "speaker_id", "language", "condition", "path"):
        assert column in back[0]
