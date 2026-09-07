"""Bounded audio decoding and sample-accurate overlapping windows."""
from dataclasses import dataclass
from io import BytesIO
from math import gcd
import subprocess
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

RATE = 16000
MAX_UPLOAD = 20 * 1024 * 1024


def normalize(samples, rate):
    x = np.asarray(samples, dtype=np.float32)
    if x.ndim == 2:
        x = x.mean(axis=1)
    if x.ndim != 1 or not len(x) or not np.isfinite(x).all():
        raise ValueError("Audio must contain finite mono or stereo samples")
    if not 8000 <= rate <= 192000:
        raise ValueError("Unsupported sample rate")
    if rate != RATE:
        g = gcd(rate, RATE)
        x = resample_poly(x, RATE // g, rate // g).astype(np.float32)
    return np.clip(x, -1, 1)


def decode(data: bytes, max_s=120):
    if not data or len(data) > MAX_UPLOAD:
        raise ValueError("Upload is empty or exceeds 20 MiB")
    try:
        with sf.SoundFile(BytesIO(data)) as f:
            if len(f) / f.samplerate > max_s or f.channels > 2:
                raise ValueError("Audio exceeds duration limit or has more than two channels")
            return normalize(f.read(dtype="float32", always_2d=True), f.samplerate)
    except (sf.LibsndfileError, RuntimeError):
        # No temp recording. Decode untrusted media only through pipes, never a shell.
        result = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "pipe",
             "-i", "pipe:0", "-t", str(max_s + 1), "-ac", "1", "-ar", str(RATE),
             "-f", "f32le", "pipe:1"], input=data, capture_output=True, timeout=20)
        if result.returncode:
            raise ValueError("Cannot decode this audio format")
        x = np.frombuffer(result.stdout, dtype="<f4").copy()
        if len(x) > max_s * RATE:
            raise ValueError("Audio exceeds duration limit")
        return normalize(x, RATE)


def activity(x):
    """Energy activity gate, not a trained speech/non-speech classifier."""
    frames = x[:len(x) // 320 * 320].reshape(-1, 320)
    if not len(frames):
        return 0.0
    rms = np.sqrt(np.mean(frames * frames, axis=1))
    return float(np.mean(rms > 0.008))


class SpeechGate:
    def __init__(self, research=False):
        self.vad = None
        if research:
            import webrtcvad
            self.vad = webrtcvad.Vad(2)

    def fraction(self, x):
        if self.vad is None:
            return activity(x)
        frames = x[:len(x) // 320 * 320].reshape(-1, 320)
        decisions = [self.vad.is_speech((np.clip(f, -1, 1) * 32767).astype("<i2").tobytes(), RATE) for f in frames]
        return float(np.mean(decisions)) if decisions else 0.


@dataclass
class Window:
    samples: np.ndarray
    start_s: float
    end_s: float
    fresh_samples: np.ndarray


class RingBuffer:
    def __init__(self):
        self.pending = np.empty(0, dtype=np.float32)
        self.start = 0
        self.first = True

    def push(self, samples):
        x = np.asarray(samples, dtype=np.float32)
        if x.ndim != 1 or not len(x) or not np.isfinite(x).all() or np.max(np.abs(x)) > 1.01:
            raise ValueError("Expected normalized finite PCM")
        self.pending = np.concatenate((self.pending, x))
        windows = []
        while len(self.pending) >= 2 * RATE:
            data = self.pending[:2 * RATE].copy()
            fresh = data if self.first else data[RATE:]
            windows.append(Window(data, self.start / RATE, self.start / RATE + 2, fresh))
            self.pending = self.pending[RATE:]
            self.start += RATE
            self.first = False
        return windows

    def clear(self):
        self.pending.fill(0)
        self.pending = np.empty(0, dtype=np.float32)
