"""CH-01..CH-06 acceptance: measured channel intelligence, no model dependency."""
import json
import numpy as np
import pytest
from scipy.signal import resample_poly
from strive.audio import RATE
from strive.channel import (ChannelAnalyzer, ChannelState, clipping_ratio,
                            estimated_bandwidth_hz, rms_dbfs, snr_db)


def speech_like(seconds=2.0, seed=0):
    """Harmonics with pauses. An engineering fixture, not a recording."""
    t = np.arange(round(seconds * RATE)) / RATE
    envelope = (np.sin(2 * np.pi * 2.5 * t) > -.3).astype(np.float32)
    tone = (.30 * np.sin(2 * np.pi * 200 * t) + .15 * np.sin(2 * np.pi * 1400 * t)
            + .06 * np.sin(2 * np.pi * 6200 * t))
    return (envelope * tone).astype(np.float32)


def narrowband(x):
    """Round-trip through 8 kHz, exactly what a G.711 leg does to bandwidth."""
    return resample_poly(resample_poly(x, 1, 2), 2, 1)[:len(x)].astype(np.float32)


def add_noise(x, snr_db_target, seed=1):
    rng = np.random.default_rng(seed)
    scale = np.sqrt(np.mean(x * x)) / (10 ** (snr_db_target / 20))
    return (x + rng.normal(0, scale, len(x))).astype(np.float32)


# ---------------------------------------------------------------- CH-01 schema

def test_channel_state_is_serializable_with_explicit_none():
    state = ChannelState(sample_rate=RATE, estimated_bandwidth_hz=None, snr_db=None,
                         clipping_ratio=0., rms_dbfs=None, discontinuity_score=0.)
    payload = state.to_dict()
    assert json.loads(json.dumps(payload)) == payload
    # Unavailable values are None, never a fake zero.
    for key in ("estimated_bandwidth_hz", "snr_db", "rms_dbfs", "packet_loss_rate",
                "jitter_ms", "codec", "quality"):
        assert payload[key] is None
    assert set(payload) == {"sample_rate", "estimated_bandwidth_hz", "snr_db", "clipping_ratio",
                            "rms_dbfs", "discontinuity_score", "packet_loss_rate", "jitter_ms",
                            "codec", "quality"}


def test_silence_reports_unavailable_not_zero():
    silence = np.zeros(2 * RATE, dtype=np.float32)
    state = ChannelAnalyzer().measure(silence, silence)
    assert state.rms_dbfs is None
    assert state.estimated_bandwidth_hz is None
    assert state.quality is None  # No usable audio means no reliability claim.


# -------------------------------------------------------------- CH-02 clipping

def test_clipping_detects_synthetic_hard_clipping():
    clean = speech_like()
    clipped = np.clip(clean * 10, -1, 1).astype(np.float32)
    assert clipping_ratio(clean) < .001      # near-zero for normal fixture
    # The fixture is silent during pauses, so only the voiced ~55% can clip.
    assert clipping_ratio(clipped) > .4      # obvious for hard clipping
    assert clipping_ratio(np.empty(0, dtype=np.float32)) == 0.


# ------------------------------------------------------------- CH-03 bandwidth

def test_bandwidth_separates_narrowband_from_wideband():
    wide = speech_like()
    narrow = narrowband(wide)
    assert estimated_bandwidth_hz(wide) > 5000
    assert estimated_bandwidth_hz(narrow) < 4000
    assert estimated_bandwidth_hz(narrow) < estimated_bandwidth_hz(wide)


def test_bandwidth_is_deterministic():
    x = speech_like()
    assert estimated_bandwidth_hz(x) == estimated_bandwidth_hz(x.copy())


def test_bandwidth_unavailable_below_silence_floor():
    assert estimated_bandwidth_hz(np.zeros(2 * RATE, dtype=np.float32)) is None
    assert estimated_bandwidth_hz(np.zeros(100, dtype=np.float32)) is None


# ------------------------------------------------------------------- CH-04 SNR

def test_noisy_fixture_scores_worse_than_clean():
    clean = speech_like()
    assert snr_db(add_noise(clean, 5)) < snr_db(add_noise(clean, 20)) < snr_db(clean)


def test_snr_is_monotonic_in_added_noise():
    clean = speech_like()
    values = [snr_db(add_noise(clean, target)) for target in (0, 5, 10, 20, 40)]
    assert values == sorted(values)


def test_snr_never_explodes_or_nans():
    for x in (np.zeros(2 * RATE, dtype=np.float32),
              np.ones(2 * RATE, dtype=np.float32),
              speech_like(),
              add_noise(speech_like(), 0)):
        value = snr_db(x)
        assert value is None or (np.isfinite(value) and 0 <= value <= 60)
    assert snr_db(np.zeros(100, dtype=np.float32)) is None


def test_rms_dbfs_is_negative_and_none_on_silence():
    assert rms_dbfs(speech_like()) < 0
    assert rms_dbfs(np.zeros(RATE, dtype=np.float32)) is None


# ----------------------------------------------------------- CH-05 continuity

def test_splice_scores_higher_than_continuous_audio():
    x = speech_like(4.0)
    rng = np.random.default_rng(7)

    continuous = ChannelAnalyzer()
    continuous.discontinuity(x[:2 * RATE])
    smooth = continuous.discontinuity(x[2 * RATE:])

    spliced = ChannelAnalyzer()
    spliced.discontinuity(x[:2 * RATE])
    cut = spliced.discontinuity((.02 * rng.normal(0, 1, 2 * RATE)).astype(np.float32))

    assert cut > smooth
    assert 0 <= smooth <= 1 and 0 <= cut <= 1


def test_first_window_has_no_predecessor():
    assert ChannelAnalyzer().discontinuity(speech_like()) == 0.


def test_discontinuity_is_bounded():
    analyzer = ChannelAnalyzer()
    rng = np.random.default_rng(3)
    for _ in range(6):
        value = analyzer.discontinuity(rng.normal(0, .3, RATE).astype(np.float32))
        assert 0. <= value <= 1.


# -------------------------------------------------------------- CH-06 quality

@pytest.mark.parametrize("degrade,label", [
    (lambda x: np.clip(x * 10, -1, 1).astype(np.float32), "clipping"),
    (narrowband, "narrowband"),
    (lambda x: add_noise(x, 0), "noise"),
])
def test_quality_decreases_for_degraded_fixtures(degrade, label):
    clean = speech_like()
    good = ChannelAnalyzer().measure(clean, clean)
    bad = ChannelAnalyzer().measure(degrade(clean), degrade(clean))
    assert bad.quality < good.quality, label
    assert 0. <= bad.quality <= 1.


def test_individual_features_remain_available_alongside_quality():
    x = speech_like()
    state = ChannelAnalyzer().measure(x, x)
    assert state.quality is not None
    for field in ("estimated_bandwidth_hz", "snr_db", "clipping_ratio", "rms_dbfs"):
        assert getattr(state, field) is not None


def test_quality_constants_are_configurable():
    x = narrowband(speech_like())
    strict = ChannelAnalyzer({"bandwidth": .9}).measure(x, x)
    lenient = ChannelAnalyzer({"bandwidth": .0}).measure(x, x)
    assert strict.quality < lenient.quality


def test_quality_is_reliability_not_spoof_probability():
    """A pristine channel must not read as 'safe'; it only means evidence is usable."""
    x = speech_like()
    state = ChannelAnalyzer().measure(x, x)
    assert state.quality > .8
    # ChannelState carries no risk/score field at all.
    assert not any("risk" in f or "spoof" in f for f in state.to_dict())


def test_transport_fields_pass_through():
    x = speech_like()
    state = ChannelAnalyzer().measure(x, x, codec="opus", packet_loss_rate=.02, jitter_ms=18.5)
    assert (state.codec, state.packet_loss_rate, state.jitter_ms) == ("opus", .02, 18.5)
