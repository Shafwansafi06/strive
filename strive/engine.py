"""STRIVE: three tracks, trust-gated SPS, age weights and EMA."""
from concurrent.futures import ThreadPoolExecutor
import time
import uuid
from typing import Any
import numpy as np
from .audio import RATE, RingBuffer, SpeechGate
from .features import unit
from .features import Features
from .config import Settings
from .audio import Window
from .retrieval import SessionProfile
from .policy import decide


def scheduled_weights(age: float, preset: str = "proposed") -> list[float]:
    if preset == "equal":
        return [.33, .33, .34]
    if preset == "global_heavy":
        return [.6, .2, .2]
    if preset == "session_heavy" and age > 15:
        return [.2, .6, .2]
    return [.8, 0., .2] if age < 15 else [.5, .3, .2] if age <= 60 else [.3, .5, .2]


def aggregate(scores: list, age: float, previous: float | None, alpha: float = .7,
              preset: str = "proposed") -> tuple:
    weights = np.array(scheduled_weights(age, preset))
    weights[[s is None for s in scores]] = 0
    if weights.sum() == 0 or scores[0] is None:
        return None, [0., 0., 0.], None
    weights /= weights.sum()
    raw = float(np.dot(weights, [0 if s is None else s for s in scores]))
    # Start at zero exactly as specified; warm-up prevents early "safe" claims.
    smoothed = alpha * (0 if previous is None else previous) + (1 - alpha) * raw
    return smoothed, weights.tolist(), raw


def boundary_coherence(features: Features, first_window: bool) -> float | None:
    if first_window or not features.segments:
        return None
    # The overlap is [0,1); only [1,2) is new. Compare adjacent phoneme
    # segments bracketing the 1 s seam in the CURRENT window.
    segments = features.segments
    pairs = [(a, b) for a, b in zip(segments[:-1], segments[1:])
             if a.start_s < 1 <= b.end_s and b.start_s - a.end_s <= .12]
    if not pairs:
        return None
    a, b = min(pairs, key=lambda pair: abs((pair[0].end_s + pair[1].start_s) / 2 - 1))
    if abs((a.end_s + b.start_s) / 2 - 1) > .2:
        return None
    return float(np.clip(1 - np.dot(unit(a.vector), unit(b.vector)), 0, 1))


class Call:
    def __init__(self, settings: Settings, extractor: Any, index: Any, language: str = "auto",
                 context: dict | None = None, source: str = "stream") -> None:
        self.cfg, self.extractor, self.index = settings, extractor, index
        self.id = uuid.uuid4().hex
        self.language = "und" if language == "auto" else language
        self.language_source = "unavailable" if language == "auto" else "operator_hint"
        self.language_done = language != "auto"
        self.context = context or {}
        self.source = source
        self.buffer = RingBuffer()
        self.activity_gate = SpeechGate(settings.mode == "research")
        self.sps = SessionProfile(settings.max_session_entries, settings.session_k)
        self.bootstrap = "pending"
        self.bootstrap_features = []
        self.language_audio = []
        self.bootstrap_scores = []
        self.voiced_s = 0.
        self.risk = None
        self.sequence = 0
        self.received = 0
        self.created = self.touched = time.monotonic()
        self.closed = False
        self.latest = None
        self.hold_latched = False
        self.verification_epoch = -1
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="strive-track")

    def feed(self, samples: np.ndarray, sequence: int) -> list[dict]:
        if self.closed:
            raise ValueError("Call has ended")
        if sequence != self.sequence:
            # Reject duplicate/out-of-order frames rather than silently corrupting the stream.
            raise ValueError(f"Expected sequence {self.sequence}, got {sequence}")
        if not 0 < len(samples) <= 2 * RATE:
            raise ValueError("Each frame must contain at most two seconds of 16 kHz PCM")
        if self.received + len(samples) > self.cfg.max_call_s * RATE:
            raise ValueError("Maximum call duration reached")
        windows = self.buffer.push(samples)
        self.sequence += 1
        self.received += len(samples)
        self.touched = time.monotonic()
        return [self._score(w) for w in windows]

    def gap(self) -> None:
        self.buffer.clear()
        self.buffer = RingBuffer()
        self.buffer.start = self.received
        self.sps.clear()
        self.bootstrap_features.clear()
        self.language_audio.clear()
        self.bootstrap_scores.clear()
        self.bootstrap = "blocked_gap"
        self.voiced_s = 0
        self.risk = None
        self.latest = None
        self.hold_latched = True

    def _score(self, window: Window) -> dict:
        started = time.perf_counter()
        age = window.end_s
        current_activity = self.activity_gate.fraction(window.fresh_samples)
        self.voiced_s += len(window.fresh_samples) / RATE * current_activity
        active = current_activity >= .25
        reasons = []
        if self.bootstrap == "pending":
            self.language_audio.append(window.fresh_samples.copy())
        if not self.language_done and age >= self.cfg.bootstrap_s:
            self.language_done = True
            if hasattr(self.extractor, "identify_language"):
                try:
                    self.language, self.language_source = self.extractor.identify_language(
                        np.concatenate(self.language_audio)[:self.cfg.bootstrap_s * RATE])
                except Exception:
                    if self.cfg.raise_model_errors:
                        raise
                    self.language, self.language_source = "und", "model_error"
            self.language_audio.clear()

        global_score = session_score = coherence_score = similarity = None
        info = {"available": False, "route": self.language}
        features, feature_ms, track_ms = None, 0., 0.
        if active:
            tick = time.perf_counter()
            try:
                features = self.extractor.extract(window.samples)
                feature_ms = (time.perf_counter() - tick) * 1000
                tick = time.perf_counter()
                jobs = [self.pool.submit(self.index.query, features.cm, self.language, self.cfg.global_k,
                                        self.cfg.min_partition_entries, self.cfg.min_neighbor_similarity),
                        self.pool.submit(self.sps.similarity, features),
                        self.pool.submit(boundary_coherence, features, window.start_s == 0)]
                global_score, info = jobs[0].result()
                similarity = jobs[1].result()
                coherence_score = jobs[2].result()
                session_score = None if similarity is None else float(np.clip(1 - similarity, 0, 1))
                track_ms = (time.perf_counter() - tick) * 1000
            except Exception:
                if self.cfg.raise_model_errors:
                    raise
                # Failure is explicit uncertainty; do not mint a zero/safe result.
                reasons.append("MODEL_OR_INDEX_ERROR")
                global_score = session_score = coherence_score = None
        else:
            reasons.append("LOW_AUDIO_ACTIVITY")

        if self.bootstrap == "pending":
            self.bootstrap_scores.append(global_score)
            if features is not None:
                self.bootstrap_features.append(features)
            if age >= self.cfg.bootstrap_s:
                trusted = (self.voiced_s >= self.cfg.min_voiced_s and len(self.bootstrap_features) >= 3
                           and all(s is not None and s < self.cfg.global_gate for s in self.bootstrap_scores))
                self.bootstrap = "trusted" if trusted else "blocked"
                if trusted:
                    for f in self.bootstrap_features:
                        self.sps.add(f)
                else:
                    reasons.append("BOOTSTRAP_REJECTED")
                self.bootstrap_features.clear()
                self.language_audio.clear()
        elif (self.bootstrap == "trusted" and features is not None and global_score is not None
              and similarity is not None and global_score < self.cfg.global_gate
              and similarity > self.cfg.similarity_gate):
            self.sps.add(features)

        enough = self.voiced_s >= self.cfg.min_voiced_s and active and global_score is not None
        acoustic_risk, weights, raw = aggregate([global_score, session_score, coherence_score], age, self.risk,
                                               self.cfg.alpha, self.cfg.weight_preset)
        if active and acoustic_risk is not None:
            self.risk = acoustic_risk
        exposed_risk = self.risk if enough else None
        if not enough:
            reasons.append("LOW_EVIDENCE")
        if global_score is not None and global_score >= .5:
            reasons.append("GLOBAL_REFERENCE_ANOMALY")
        if session_score is not None and session_score >= .3:
            reasons.append("SESSION_INCONSISTENCY")
        if coherence_score is not None and coherence_score >= .5:
            reasons.append("BOUNDARY_DISCONTINUITY")
        if info.get("fallback"):
            reasons.append("GLOBAL_LANGUAGE_FALLBACK")
        if self.extractor.is_surrogate:
            reasons.append("SURROGATE_FEATURES_NOT_A_DEEPFAKE_VERDICT")
        policy = decide(exposed_risk, self.context, self.cfg.warning, self.cfg.alert)
        if policy["recommended_action"] in ("HOLD_AND_VERIFY", "VERIFY_CALLER"):
            self.hold_latched = True
            self.verification_epoch = -1
        event = {"schema_version": "1.0", "call_id": self.id, "timestamp": time.time(),
                 "session_age_s": age, "voiced_seconds": round(self.voiced_s, 3),
                 "s_risk": exposed_risk, "authenticity_risk": exposed_risk,
                 "track_scores": {"s_global": global_score, "s_session": session_score, "s_coherence": coherence_score},
                 "session_similarity": similarity, "weights": weights, "raw_fusion": raw,
                 "language": self.language, "language_source": self.language_source,
                 "bootstrap": self.bootstrap, "profile_entries": len(self.sps.entries),
                 "retrieval": info, "reasons": reasons, "mode": self.cfg.mode,
                 "source": self.source, "model_version": self.extractor.id,
                 "pipeline_version": getattr(self.extractor, "pipeline_version", self.extractor.id),
                 "calibrated": False, "demo_only": self.extractor.is_surrogate,
                 "evidence_eligible": enough,
                 "features": {} if features is None else features.metadata,
                 "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                 "stage_ms": {"features": round(feature_ms, 3), "tracks": round(track_ms, 3)}, **policy}
        if event["latency_ms"] > 1000:
            event["reasons"].append("COMPUTE_EXCEEDS_STRIDE")
        self.latest = event
        return event

    def close(self) -> None:
        self.closed = True
        self.buffer.clear()
        self.sps.clear()
        for x in self.language_audio:
            x.fill(0)
        self.language_audio.clear()
        self.bootstrap_features.clear()
        self.bootstrap_scores.clear()
        self.pool.shutdown(wait=True)
