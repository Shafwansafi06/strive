"""Channel intelligence: measured transport quality, kept separate from spoof risk.

CH-01..CH-06. Every value here describes the CHANNEL, not the speaker. A degraded
channel means our evidence is less trustworthy; it is never itself evidence of a
clone. Nothing in this module loads a model, and every function is deterministic.

Values that cannot be measured are `None`, never a fake zero.
"""
from dataclasses import asdict, dataclass, replace
import numpy as np
from scipy.signal import stft
from .audio import RATE

CLIP_LEVEL = 0.99
SILENCE_RMS = 0.008

# CH-06 heuristic constants. Overridable per call so they stay tunable in config.
DEFAULT_QUALITY_WEIGHTS = {
    "clipping": 0.25, "clipping_full": 0.02,
    "discontinuity": 0.20,
    "snr": 0.30, "snr_good_db": 25.0, "snr_bad_db": 5.0,
    "bandwidth": 0.25, "bandwidth_good_hz": 7000.0, "bandwidth_bad_hz": 3400.0,
}


@dataclass(frozen=True)
class ChannelState:
    """CH-01. Serializable; unavailable measurements stay explicitly None."""
    sample_rate: int
    estimated_bandwidth_hz: float | None
    snr_db: float | None
    clipping_ratio: float
    rms_dbfs: float | None
    discontinuity_score: float
    packet_loss_rate: float | None = None
    jitter_ms: float | None = None
    codec: str | None = None
    quality: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def clipping_ratio(x: np.ndarray) -> float:
    """CH-02. Fraction of samples at or beyond full scale. No model dependency."""
    x = np.asarray(x, dtype=np.float32)
    return float(np.mean(np.abs(x) >= CLIP_LEVEL)) if len(x) else 0.


def rms_dbfs(x: np.ndarray) -> float | None:
    x = np.asarray(x, dtype=np.float32)
    rms = float(np.sqrt(np.mean(x * x))) if len(x) else 0.
    return None if rms < 1e-9 else float(20 * np.log10(rms))


def _power_spectrum(x: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    """Average power spectrum over the window, or None if too short."""
    if len(x) < 512:
        return None
    _, _, z = stft(x, RATE, nperseg=512, noverlap=256, nfft=512, boundary=None)
    power = (np.abs(z) ** 2).mean(axis=1)
    if not np.isfinite(power).all() or power.sum() <= 0:
        return None
    return np.fft.rfftfreq(512, 1 / RATE), power


def estimated_bandwidth_hz(x: np.ndarray, fraction: float = 0.99) -> float | None:
    """CH-03. Frequency below which `fraction` of the signal power sits.

    Method: cumulative power rolloff on the averaged STFT magnitude-squared
    spectrum (512-point, 50% overlap). This is an occupied-bandwidth estimate,
    not a codec cutoff measurement. Assumption: 8 kHz-sourced narrowband audio
    resampled to 16 kHz carries no meaningful power above ~4 kHz, so it lands
    well below a genuinely wideband recording. It is content-dependent: a very
    low-pitched or silent passage will read narrow regardless of the channel.
    """
    x = np.asarray(x, dtype=np.float32)
    if float(np.sqrt(np.mean(x * x))) < SILENCE_RMS:
        return None
    spectrum = _power_spectrum(x)
    if spectrum is None:
        return None
    frequencies, power = spectrum
    cumulative = np.cumsum(power)
    return float(frequencies[int(np.searchsorted(cumulative, fraction * cumulative[-1]))])


def snr_db(x: np.ndarray) -> float | None:
    """CH-04. Rough SNR proxy, NOT a laboratory SNR measurement.

    Method: minimum statistics on the STFT. For each frequency bin, the 10th
    percentile of its power across time frames estimates the stationary noise
    floor in that bin; the rest of the mean power is treated as signal. Unlike a
    frame-energy percentile, this also works on stationary input, where every
    frame has the same energy and a time-domain percentile ratio collapses to 0.

    It cannot separate additive noise from reverberation or codec artifacts, and
    it will read a genuinely noise-like source as low SNR. Reported as an
    estimate, clamped to [0, 60] dB. Not a laboratory measurement.
    """
    x = np.asarray(x, dtype=np.float32)
    if len(x) < 512 or float(np.sqrt(np.mean(x * x))) < 1e-9:
        return None
    _, _, z = stft(x, RATE, nperseg=512, noverlap=256, nfft=512, boundary=None)
    power = np.abs(z) ** 2
    if power.shape[1] < 5 or not np.isfinite(power).all():
        return None
    total = float(power.mean(axis=1).sum())
    # Digitally clean input has an exactly-zero floor; bound it rather than
    # reporting "unmeasurable", which the fusion would read as degraded.
    noise = max(float(np.percentile(power, 10, axis=1).sum()), total * 1e-6)
    signal = total - noise
    if total <= 0 or signal <= 0:
        return None
    return float(np.clip(10 * np.log10(signal / noise), 0., 60.))


class ChannelAnalyzer:
    """CH-05 + CH-06. Stateful across windows; one instance per call.

    Continuity needs the previous window, so this holds the minimum state to
    compare adjacent windows: last frame energy, last spectral centroid, last
    noise floor and the final sample of the previous fresh audio.
    """

    def __init__(self, quality_weights: dict | None = None) -> None:
        self.previous = None
        self.weights = dict(DEFAULT_QUALITY_WEIGHTS, **(quality_weights or {}))

    @staticmethod
    def _summary(x: np.ndarray) -> dict | None:
        spectrum = _power_spectrum(x)
        if spectrum is None:
            return None
        frequencies, power = spectrum
        rms = float(np.sqrt(np.mean(x * x)))
        frames = x[:len(x) // 320 * 320].reshape(-1, 320)
        energy = np.mean(frames * frames, axis=1) if len(frames) else np.zeros(1)
        return {"rms": rms,
                "centroid": float((power * frequencies).sum() / power.sum()),
                "floor": float(np.percentile(energy, 10)),
                "edge": float(x[-1]) if len(x) else 0.}

    def discontinuity(self, fresh: np.ndarray) -> float:
        """CH-05. Cheap continuity signal across adjacent windows, bounded [0,1].

        Combines a log energy jump, a spectral centroid jump, a noise-floor jump
        and the sample-level step at the join. A splice shifts at least one of
        them; normal speech moves all of them gently. The first window has no
        predecessor and scores 0.
        """
        current = self._summary(np.asarray(fresh, dtype=np.float32))
        previous, self.previous = self.previous, current
        if previous is None or current is None:
            return 0.

        def jump(now: float, before: float, scale: float) -> float:
            return float(np.clip(abs(np.log((now + scale) / (before + scale))) / np.log(10), 0, 1))

        energy_jump = jump(current["rms"], previous["rms"], 1e-3)
        floor_jump = jump(current["floor"], previous["floor"], 1e-8)
        centroid_jump = float(np.clip(abs(current["centroid"] - previous["centroid"]) / (RATE / 4), 0, 1))
        # A hard splice leaves a step far larger than the local sample-to-sample motion.
        step = abs(float(np.asarray(fresh, dtype=np.float32)[0]) - previous["edge"])
        step_jump = float(np.clip(step / max(4 * current["rms"], 1e-6), 0, 1))
        return float(np.clip(max(energy_jump, floor_jump, centroid_jump, step_jump), 0, 1))

    def quality(self, state: ChannelState) -> float | None:
        """CH-06. Conservative reliability scalar. NOT a spoof probability.

        1.0 means the channel does not undermine our evidence. Lower means the
        acoustic branches deserve less trust. Individual features stay available
        on the ChannelState; this only summarizes them.
        """
        w = self.weights
        penalties = [w["clipping"] * min(1., state.clipping_ratio / w["clipping_full"]),
                     w["discontinuity"] * state.discontinuity_score]
        if state.snr_db is not None:
            penalties.append(w["snr"] * float(np.clip((w["snr_good_db"] - state.snr_db) /
                                                      (w["snr_good_db"] - w["snr_bad_db"]), 0, 1)))
        if state.estimated_bandwidth_hz is not None:
            penalties.append(w["bandwidth"] * float(np.clip(
                (w["bandwidth_good_hz"] - state.estimated_bandwidth_hz) /
                (w["bandwidth_good_hz"] - w["bandwidth_bad_hz"]), 0, 1)))
        if state.rms_dbfs is None:
            return None
        return float(np.clip(1. - sum(penalties), 0., 1.))

    def measure(self, window: np.ndarray, fresh: np.ndarray, codec: str | None = None,
                packet_loss_rate: float | None = None, jitter_ms: float | None = None) -> ChannelState:
        """Full per-window channel state. `window` is the analysis window; `fresh`
        is only the newly arrived audio, which is what continuity compares."""
        window = np.asarray(window, dtype=np.float32)
        state = ChannelState(sample_rate=RATE,
                             estimated_bandwidth_hz=estimated_bandwidth_hz(window),
                             snr_db=snr_db(window),
                             clipping_ratio=clipping_ratio(window),
                             rms_dbfs=rms_dbfs(window),
                             discontinuity_score=self.discontinuity(fresh),
                             packet_loss_rate=packet_loss_rate,
                             jitter_ms=jitter_ms,
                             codec=codec)
        return replace(state, quality=self.quality(state))
