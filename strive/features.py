"""Feature contracts; the lightweight extractor is explicitly a DSP surrogate."""
from dataclasses import dataclass
from functools import lru_cache
import numpy as np
from scipy.fft import dct
from scipy.signal import stft, correlate, find_peaks
from .audio import RATE


def unit(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    norms = np.linalg.norm(x, axis=-1, keepdims=True)
    return x / np.maximum(norms, 1e-12)


@dataclass
class Segment:
    start_s: float
    end_s: float
    vector: np.ndarray
    token: int = -1


@dataclass
class Features:
    cm: np.ndarray
    profile: np.ndarray
    segments: list[Segment]
    cm_score: float | None
    metadata: dict


def acoustic_profile_legacy(x: np.ndarray) -> tuple[np.ndarray, dict]:
    """24 measured acoustic values; never advertised as Vox-Profile's output."""
    frames = x[:len(x) // 640 * 640].reshape(-1, 640)
    energy = np.sqrt(np.mean(frames ** 2, axis=1))
    pitch, harmonic = [], []
    for f, e in zip(frames, energy):
        if e < .008:
            continue
        f = f - f.mean()
        ac = correlate(f, f, method="fft")[len(f) - 1:]
        lag = 40 + np.argmax(ac[40:321])
        strength = ac[lag] / max(ac[0], 1e-9)
        if strength > .25:
            pitch.append(RATE / lag)
        harmonic.append(strength)
    spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2 + 1e-10
    bands = np.array([b.sum() for b in np.array_split(spectrum, 16)])
    bands /= bands.sum()
    vals = [np.mean(pitch) / 400 if pitch else 0,
            np.std(pitch) / 150 if pitch else 0,
            np.mean(energy), np.std(energy), np.mean(energy < .008),
            np.mean(harmonic) if harmonic else 0,
            np.mean(np.abs(np.diff(np.sign(x)))) / 2,
            np.mean(np.abs(x) >= .99)]
    return unit(np.r_[vals, np.sqrt(bands)]), {"pitch_hz": round(float(np.mean(pitch)), 1) if pitch else None,
        "rms": round(float(np.mean(energy)), 4), "activity_fraction": round(float(np.mean(energy >= .008)), 3)}


@lru_cache(maxsize=1)
def mel_filterbank() -> np.ndarray:
    """26 triangular mel filters for 512-point, 16 kHz power spectra."""
    mel_max = 2595 * np.log10(1 + (RATE / 2) / 700)
    hz = 700 * (10 ** (np.linspace(0, mel_max, 28) / 2595) - 1)
    frequencies = np.fft.rfftfreq(512, 1 / RATE)
    filters = np.zeros((26, len(frequencies)))
    for i in range(26):
        up = (frequencies - hz[i]) / (hz[i + 1] - hz[i])
        down = (hz[i + 2] - frequencies) / (hz[i + 2] - hz[i + 1])
        filters[i] = np.maximum(0, np.minimum(up, down))
    return filters


def acoustic_profile(x: np.ndarray, *, legacy: bool = False) -> tuple[np.ndarray, dict]:
    """62-value measured profile, or exact v1 behavior for the unchanged demo.

    Positions 0:24 preserve the legacy feature ordering/direction. Appending
    dimensions and renormalizing changes their magnitudes; old SPS vectors
    cannot be mixed with new ones. No learned model or librosa dependency.
    """
    x = np.asarray(x, dtype=np.float32)
    if x.ndim != 1 or len(x) < 640 or not np.isfinite(x).all():
        raise ValueError("Acoustic profile needs at least 640 finite mono samples")
    original, metadata = acoustic_profile_legacy(x)
    if legacy:
        return original, metadata
    _, _, z = stft(x, RATE, nperseg=400, noverlap=240, nfft=512, boundary=None)
    power = np.abs(z).T ** 2
    safe = power + 1e-12
    frequencies = np.fft.rfftfreq(512, 1 / RATE)
    totals = safe.sum(axis=1)
    centroid = (safe * frequencies).sum(axis=1) / totals
    rolloff = frequencies[np.argmax(np.cumsum(safe, axis=1) >= .85 * totals[:, None], axis=1)]
    flatness = np.exp(np.log(safe).mean(axis=1)) / safe.mean(axis=1)
    mfcc = dct(np.log(np.maximum(power @ mel_filterbank().T, 1e-12)), type=2, norm="ortho", axis=1)[:, :13]
    frames = x[:len(x) // 320 * 320].reshape(-1, 320)
    energy = np.sqrt(np.mean(frames * frames, axis=1))
    delta = np.diff(energy)
    peaks, _ = find_peaks(energy, distance=5, prominence=max(.005, float(energy.std()) * .5))
    period_changes, periods, amplitude_changes, amplitudes = [], [], [], []
    for frame in x[:len(x) // 640 * 640].reshape(-1, 640):
        f = frame - frame.mean()
        if np.sqrt(np.mean(f * f)) < .008:
            continue
        ac = correlate(f, f, method="fft")[len(f) - 1:]
        lag = 40 + int(np.argmax(ac[40:321]))
        if ac[lag] / max(ac[0], 1e-9) < .5:
            continue
        cycles, _ = find_peaks(f, distance=max(1, int(lag * .6)), prominence=float(np.std(f)) * .5)
        intervals = np.diff(cycles)
        valid = (intervals >= lag * .6) & (intervals <= lag * 1.5)
        for i in range(len(intervals) - 1):
            if valid[i] and valid[i + 1]:
                period_changes.append(abs(float(intervals[i + 1] - intervals[i])))
        periods.extend(intervals[valid].tolist())
        cycle_amplitudes = [float(np.ptp(f[a:b])) for a, b in zip(cycles[:-1], cycles[1:]) if b > a]
        amplitudes.extend(cycle_amplitudes)
        amplitude_changes.extend(np.abs(np.diff(cycle_amplitudes)).tolist())
    jitter = float(np.mean(period_changes) / max(np.mean(periods), 1e-12)) if period_changes else 0.
    shimmer = float(np.mean(amplitude_changes) / max(np.mean(amplitudes), 1e-12)) if amplitude_changes else 0.
    additions = np.r_[mfcc.mean(0) / 100, mfcc.std(0) / 50,
        centroid.mean() / 8000, centroid.std() / 8000,
        rolloff.mean() / 8000, rolloff.std() / 8000,
        flatness.mean(), flatness.std(),
        delta.mean() if len(delta) else 0, delta.std() if len(delta) else 0,
        len(peaks) / (len(x) / RATE) / 10, jitter, shimmer, np.mean(energy < .008)]
    vector = unit(np.r_[original, additions])
    return vector, {**metadata, "profile_kind": f"acoustic-{len(vector)}", "profile_dimension": len(vector),
                    "profile_schema": "acoustic-62-v2", "jitter_local": jitter, "shimmer_local": shimmer,
                    "cycle_features_available": bool(period_changes and amplitude_changes),
                    "energy_peaks_per_second": len(peaks) / (len(x) / RATE)}


class DSPExtractor:
    id = "dsp-surrogate-v1"
    is_surrogate = True

    def extract(self, x: np.ndarray) -> Features:
        _, times, z = stft(x, fs=RATE, nperseg=400, noverlap=240, nfft=512, boundary=None)
        p = np.abs(z).T ** 2 + 1e-12
        bands = np.stack([b.mean(axis=1) for b in np.array_split(p, 32, axis=1)], axis=1)
        b = np.sqrt(bands / np.maximum(bands.sum(axis=1, keepdims=True), 1e-12))
        cm = unit(np.r_[b.mean(axis=0), b.std(axis=0)])
        profile, stats = acoustic_profile(x, legacy=True)
        # Flux-based segments are an engineering substitute, not phoneme predictions.
        flux = np.linalg.norm(np.diff(b, axis=0), axis=1)
        peaks, _ = find_peaks(flux, distance=8, prominence=.08)
        edges = sorted(set([0, *list(peaks + 1), len(b)]))
        if len(edges) < 3:
            edges = list(range(0, len(b), 15)) + [len(b)]
        duration = len(x) / RATE
        segments = [Segment(float(max(0, times[a] - .0125)),
                            float(min(duration, times[e - 1] + .0125)), unit(b[a:e].mean(axis=0)))
                    for a, e in zip(edges[:-1], edges[1:]) if e > a]
        return Features(cm, profile, segments, None, {**stats, "extractor": self.id,
             "profile_kind": "acoustic-24", "segments_kind": "spectral-flux-surrogate"})
