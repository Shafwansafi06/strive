"""BASE-02 / AUD-02: configurable window and hop.

Covers the three required geometries (2/1, 2/0.5, 4/0.5), monotonic timestamps,
bounded memory, exact overlap, and the resulting emission rate.
"""
import numpy as np
import pytest
from strive.audio import RATE, RingBuffer
from strive.config import Settings
from strive.demo import scenario_audio
from strive.engine import Call, boundary_coherence
from strive.features import DSPExtractor, Features, Segment

GEOMETRIES = [(2.0, 1.0), (2.0, 0.5), (4.0, 0.5), (4.0, 1.0), (2.0, 2.0)]


@pytest.mark.parametrize("window_s,hop_s", GEOMETRIES)
def test_ring_buffer_geometry(window_s, hop_s):
    seconds = 10
    x = np.linspace(-.5, .5, seconds * RATE, dtype=np.float32)
    ring = RingBuffer(window_s, hop_s)
    windows = []
    # Push in ragged frames so framing cannot accidentally align with the hop.
    for part in np.array_split(x, 173):
        windows.extend(ring.push(part))

    expected = int((seconds - window_s) / hop_s) + 1
    assert len(windows) == expected

    # Every window is exactly window_s long and timestamps are monotonic and exact.
    for i, w in enumerate(windows):
        assert len(w.samples) == round(window_s * RATE)
        assert w.start_s == pytest.approx(i * hop_s)
        assert w.end_s == pytest.approx(i * hop_s + window_s)
    assert [w.start_s for w in windows] == sorted(w.start_s for w in windows)

    # fresh_samples partitions the input: no audio counted twice, none skipped.
    assert sum(len(w.fresh_samples) for w in windows) == round(windows[-1].end_s * RATE)

    # Overlap is sample-exact between adjacent windows.
    overlap = round((window_s - hop_s) * RATE)
    for previous, current in zip(windows, windows[1:]):
        if overlap:
            np.testing.assert_array_equal(previous.samples[-overlap:], current.samples[:overlap])

    # Bounded memory: the buffer never retains a full window after draining.
    assert len(ring.pending) < round(window_s * RATE)


def test_half_second_hop_emits_two_windows_per_second():
    ring = RingBuffer(2.0, 0.5)
    ring.push(np.zeros(2 * RATE, dtype=np.float32))  # warm-up
    windows = ring.push(np.zeros(4 * RATE, dtype=np.float32))
    assert len(windows) == 8  # 4 s of audio at a 0.5 s hop


def test_hop_larger_than_window_rejected():
    with pytest.raises(ValueError):
        RingBuffer(2.0, 3.0)


@pytest.mark.parametrize("window_s,hop_s", GEOMETRIES)
def test_settings_accept_supported_geometries(window_s, hop_s):
    cfg = Settings(window_s=window_s, stride_s=hop_s)
    assert cfg.window_s == window_s and cfg.stride_s == hop_s


@pytest.mark.parametrize("window_s,hop_s", [
    (2.0, 0.0),        # zero hop
    (2.0, -1.0),       # negative hop
    (2.0, 3.0),        # hop exceeds window
    (2.0, 0.00003),    # not a whole number of samples
    (2.00003, 1.0),    # window not a whole number of samples
])
def test_settings_reject_invalid_geometry(window_s, hop_s):
    with pytest.raises(ValueError):
        Settings(window_s=window_s, stride_s=hop_s)


def test_sample_rate_still_locked():
    with pytest.raises(ValueError):
        Settings(sample_rate=8000)


def test_coherence_seam_follows_hop():
    """The seam sits at window_s - stride_s, not always at 1 s."""
    # 4 s window / 1 s hop puts the seam at 3 s.
    f = Features(np.ones(2), np.ones(2),
                 [Segment(0, 2.9, np.array([1., 0.])),
                  Segment(2.9, 3.0, np.array([0., 1.])),
                  Segment(3.0, 4.0, np.array([0., -1.]))], None, {})
    assert boundary_coherence(f, False, seam_s=3.0) == 1
    # At the default 1 s seam there is no adjacent pair bracketing it.
    assert boundary_coherence(f, False, seam_s=1.0) is None
    # No overlap means no seam to measure.
    assert boundary_coherence(f, False, seam_s=0.0) is None


def test_call_emits_at_configured_hop(index):
    """End-to-end: a 0.5 s hop roughly doubles the event rate over a 1 s hop."""
    audio = scenario_audio("steady", 20)

    def events_for(hop_s):
        call = Call(Settings(window_s=2.0, stride_s=hop_s), DSPExtractor(), index)
        out = []
        for i, start in enumerate(range(0, len(audio), RATE)):
            out.extend(call.feed(audio[start:start + RATE], i))
        call.close()
        return out

    slow, fast = events_for(1.0), events_for(0.5)
    assert len(slow) == 19   # (20 - 2) / 1 + 1
    assert len(fast) == 37   # (20 - 2) / 0.5 + 1
    for stream in (slow, fast):
        ages = [e["session_age_s"] for e in stream]
        assert ages == sorted(ages)
        assert all(e["schema_version"] == "1.1" for e in stream)
