"""Seeded engineering signals. BOTH families are synthetic, never human labels."""
import numpy as np
from .audio import RATE
from .features import DSPExtractor
from .retrieval import ReferenceIndex

SCENARIOS = {
    "steady": "Stable reference signal",
    "switch": "Reference → out-of-family signal at 18 s",
    "suspicious_start": "Out-of-family signal from the start",
    "silence": "Silence / insufficient evidence",
}

# Presentation aliases remain procedural engineering fixtures. The attack onset
# is known because the generator constructs it, not because STRIVE inferred it.
PRESENTATION_SCENARIOS = {
    "genuine": {"display_name": "Genuine Call", "engine_scenario": "steady",
        "duration_s": 30.0, "attack_onset_sec": None,
        "label": "DEMO / SYNTHETIC SCENARIO"},
    "spoof": {"display_name": "Deepfake / Spoof Call", "engine_scenario": "suspicious_start",
        "duration_s": 30.0, "attack_onset_sec": 0.0,
        "label": "DEMO / SYNTHETIC SCENARIO"},
    "mid_call": {"display_name": "Mid-Call Voice Replacement", "engine_scenario": "switch",
        "duration_s": 30.0, "attack_onset_sec": 15.0,
        "label": "DEMO / SYNTHETIC SCENARIO"},
}


def signal(family, seconds, seed=0, offset=0):
    rng = np.random.default_rng(seed)
    t = (np.arange(round(RATE * seconds)) + offset * RATE) / RATE
    if family == 0:
        f0 = 135 + 10 * np.sin(2 * np.pi * .8 * t) + seed % 23
        phase = 2 * np.pi * np.cumsum(f0) / RATE
        x = np.sin(phase) + .5 * np.sin(2 * phase) + .18 * np.sin(3 * phase)
        envelope = .28 + .08 * np.sin(2 * np.pi * 3 * t)
        x = .4 * envelope * x + rng.normal(0, .003, len(t))
    else:
        # Deliberately different spectrum; this is not a TTS/voice-clone generator.
        x = .13 * np.sin(2 * np.pi * (2300 + seed % 70) * t)
        x += .08 * np.sin(2 * np.pi * 3700 * t) + rng.normal(0, .07, len(t))
    return x.astype(np.float32)


def make_demo_index():
    extractor = DSPExtractor()
    vectors, labels, languages, ids = [], [], [], []
    for family in (0, 1):
        for seed in range(24):
            vectors.append(extractor.extract(signal(family, 2, seed)).cm)
            labels.append(family)
            languages.append("fixture")
            ids.append(f"engineering-family-{family}-seed-{seed}")
    return ReferenceIndex(vectors, labels, languages,
                          {"extractor_id": extractor.id, "demo_only": True,
                           "description": "48 procedural signals; family labels are NOT bona fide/spoof ground truth"}, ids)


def scenario_audio(name, seconds=40):
    if name in PRESENTATION_SCENARIOS:
        item = PRESENTATION_SCENARIOS[name]
        seconds = int(item["duration_s"])
        if name == "mid_call":
            onset = int(item["attack_onset_sec"])
            return np.r_[signal(0, onset, 103), signal(1, seconds - onset, 104, onset)]
        name = item["engine_scenario"]
    if name not in SCENARIOS:
        raise ValueError("Unknown demo scenario")
    if name == "silence":
        return np.zeros(seconds * RATE, dtype=np.float32)
    if name == "switch":
        return np.r_[signal(0, 18, 103), signal(1, seconds - 18, 104, 18)]
    return signal(1 if name == "suspicious_start" else 0, seconds, 105)
