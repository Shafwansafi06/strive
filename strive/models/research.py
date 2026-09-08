"""Frozen local NII CM, XLSR phonemes, acoustic/Vox traits and VoxLingua ID.

The module imports without PyTorch. Instantiation validates required local files
before importing optional ML packages. Runtime never downloads or invents weights.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import threading
from typing import Any
import numpy as np
from ..config import Settings
from ..features import Features, Segment, acoustic_profile, unit

SUPPORTED_LANGUAGES = {"hi", "ta", "te", "bn", "mr", "kn", "en", "mixed", "und"}
LANGUAGE_NAMES = {"hindi": "hi", "tamil": "ta", "telugu": "te", "bengali": "bn",
                  "bangla": "bn", "marathi": "mr", "kannada": "kn", "english": "en"}


def sha256(path: str | Path) -> str:
    """Hash a file incrementally without holding weights in RAM."""
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def language_result(label: str, probability: float) -> tuple[str, str]:
    """Map an actual posterior and VoxLingua label, never infer accent/country."""
    parts = [part.strip().lower() for part in label.split(":")]
    tag = next((p for p in parts if p in SUPPORTED_LANGUAGES), None)
    if tag is None:
        tag = next((LANGUAGE_NAMES[p] for p in parts if p in LANGUAGE_NAMES), "und")
    if not np.isfinite(probability) or probability < .5 or tag == "und":
        return "und", "model_low_confidence"
    return tag, "model"


def require_file(path: Path) -> Path:
    """Return a real local file or an actionable missing-asset exception."""
    if not path.is_file():
        raise FileNotFoundError(f"Required model file missing: {path.resolve()}. Run scripts/prepare_models.py and export/seal the model bundle.")
    return path


class ResearchExtractor:
    """Parallel inference on frozen, checksummed models; acoustic profile is 62-d."""
    is_surrogate: bool = False
    id: str
    pipeline_version: str

    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        # The NII CM is exported as a traced graph at a fixed input length. Derive
        # the expected window from config so a re-exported bundle can use 4 s.
        self.window_samples = round(cfg.window_s * cfg.sample_rate)
        self.root = Path(cfg.model_dir).resolve()
        root = self.root
        manifest_path = require_file(root / "manifest.json")
        require_file(root / "cm.pt")
        for name in ("config.json", "preprocessor_config.json", "vocab.json"):
            require_file(root / "phoneme" / name)
        if not any((root / "phoneme").glob("*.safetensors")) and not any((root / "phoneme").glob("pytorch_model*.bin")):
            raise FileNotFoundError(f"Phoneme weights missing in {root / 'phoneme'}")
        if cfg.require_language_model:
            for name in ("hyperparams.yaml", "embedding_model.ckpt", "classifier.ckpt", "label_encoder.txt"):
                require_file(root / "language" / name)
        if cfg.profile_backend == "vox":
            require_file(root / "vox" / "spec.json")
        manifest = json.loads(manifest_path.read_text())
        self.pipeline_version = "research-v2-" + hashlib.sha256(
            (sha256(manifest_path) + cfg.profile_backend + "acoustic-62-v2").encode()).hexdigest()[:16]
        pinned = manifest.get("sha256", {})
        if "cm.pt" not in pinned:
            raise ValueError("manifest.json must pin cm.pt")
        for relative, expected in pinned.items():
            path = (root / relative).resolve()
            if not path.is_relative_to(root):
                raise ValueError("Model path escapes model directory: " + relative)
            if sha256(require_file(path)) != expected:
                raise ValueError("Model checksum mismatch: " + relative)
        for folder in ("phoneme", "language"):
            for path in (root / folder).rglob("*"):
                if path.is_file() and ".cache" not in path.parts and path.relative_to(root).as_posix() not in pinned:
                    raise ValueError("Unpinned model dependency: " + path.relative_to(root).as_posix())
        self.id = "research-cm-" + pinned["cm.pt"][:12]
        self.cm_dimension = int(manifest["cm_dimension"])
        if self.cm_dimension not in (1024, 1920):
            raise ValueError("NII export must have 1024 (MMS) or 1920 (XLS-R-2B) dimensions")
        self.lock = threading.RLock()
        self.closed = False
        self.pool = None
        self.cm = self.phone = self.processor = self.lid = None
        self.profiles = []
        import torch
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
        self.torch = torch
        if cfg.device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested but no CUDA device is available")
        try:
            self.cm = torch.jit.load(str(root / "cm.pt"), map_location=cfg.device).eval()
            for parameter in self.cm.parameters():
                parameter.requires_grad_(False)
            # We process audio only. Disable text-to-phoneme conversion so the
            # tokenizer does not unnecessarily require a system espeak backend.
            self.processor = Wav2Vec2Processor.from_pretrained(root / "phoneme", local_files_only=True,
                                                              do_phonemize=False)
            self.phone = Wav2Vec2ForCTC.from_pretrained(root / "phoneme", local_files_only=True).to(cfg.device).eval()
            self.phone.requires_grad_(False)
            if cfg.profile_backend == "vox":
                spec_path = require_file(root / "vox" / "spec.json")
                if "vox/spec.json" not in pinned:
                    raise ValueError("manifest.json must pin vox/spec.json")
                specs = json.loads(spec_path.read_text())
                if not {"pitch", "volume", "clarity", "rhythm", "texture"}.issubset({s["trait"] for s in specs}):
                    raise ValueError("Vox specification must include all five vocal traits")
                if len({s["trait"] for s in specs}) != len(specs):
                    raise ValueError("Duplicate Vox trait names")
                for spec in specs:
                    relative = Path(spec["file"])
                    path = (root / relative if relative.parts[0] == "vox" else root / "vox" / relative).resolve()
                    if not path.is_relative_to(root / "vox"):
                        raise ValueError("Vox file must stay inside models/vox")
                    if path.relative_to(root).as_posix() not in pinned or int(spec["dimension"]) < 1:
                        raise ValueError("Unpinned Vox export or invalid dimension")
                    model = torch.jit.load(str(require_file(path)), map_location=cfg.device).eval()
                    for parameter in model.parameters():
                        parameter.requires_grad_(False)
                    self.profiles.append((spec, model))
            elif cfg.profile_backend != "acoustic":
                raise ValueError("profile_backend must be acoustic or vox")
            if (root / "language" / "hyperparams.yaml").is_file():
                from speechbrain.inference.classifiers import EncoderClassifier
                self.lid = EncoderClassifier.from_hparams(source=str(root / "language"),
                    savedir=str(root / "language"), overrides={"pretrained_path": str(root / "language")},
                    run_opts={"device": cfg.device})
                self.lid.eval()
                for parameter in self.lid.parameters():
                    parameter.requires_grad_(False)
            self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="strive-neural")
        except Exception:
            self.close()
            raise

    def _cm(self, tensor: Any) -> tuple[np.ndarray, float]:
        with self.torch.inference_mode():
            embedding, spoof = self.cm(tensor)
        vector = embedding.detach().float().cpu().numpy()
        score = float(spoof.detach().reshape(-1)[0].cpu())
        if vector.shape != (1, self.cm_dimension) or not np.isfinite(vector).all() or np.linalg.norm(vector) < 1e-12:
            raise ValueError("CM output shape or values violate the NII export contract")
        if not np.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("CM class-0 spoof probability must be finite and within [0,1]")
        return unit(vector[0]), score

    def _phones(self, raw: np.ndarray) -> list[Segment]:
        inputs = self.processor(raw, sampling_rate=16000, return_tensors="pt", padding=False)
        inputs = {k: v.to(self.cfg.device) for k, v in inputs.items()}
        with self.torch.inference_mode():
            result = self.phone(**inputs, output_hidden_states=True)
        ids = result.logits[0].argmax(-1).cpu().numpy()
        hidden = result.hidden_states[-1][0].float().cpu().numpy()
        if len(ids) != len(hidden) or not np.isfinite(hidden).all():
            raise ValueError("Invalid phoneme model output")
        bounds = np.r_[0, np.where(ids[1:] != ids[:-1])[0] + 1, len(ids)]
        stride, receptive = 1, 1
        for kernel, hop in zip(self.phone.config.conv_kernel, self.phone.config.conv_stride):
            receptive += (kernel - 1) * stride
            stride *= hop
        # CTC blanks separate same-token repetitions; no forced segment count.
        return [Segment(float(a * stride / 16000), float(min(len(raw) / 16000, ((b - 1) * stride + receptive) / 16000)),
                        unit(hidden[a:b].mean(0)), int(ids[a]))
                for a, b in zip(bounds[:-1], bounds[1:]) if ids[a] != self.phone.config.pad_token_id]

    def _profile(self, tensor: Any, raw: np.ndarray) -> tuple[np.ndarray, dict]:
        if self.cfg.profile_backend == "acoustic":
            return acoustic_profile(raw)
        vectors = []
        with self.torch.inference_mode():
            for spec, model in self.profiles:
                vector = model(tensor).reshape(-1).float().cpu().numpy()
                if len(vector) != spec["dimension"] or not np.isfinite(vector).all() or np.linalg.norm(vector) < 1e-12:
                    raise ValueError("Vox output disagrees with specification")
                vectors.append(unit(vector))
        return unit(np.concatenate(vectors)), {"profile_kind": "vox", "vox_traits": len(vectors)}

    def extract(self, waveform: np.ndarray) -> Features:
        """Return actual frozen-model features for exactly one 16 kHz 2-s window."""
        raw = np.asarray(waveform, dtype=np.float32)
        if raw.shape != (self.window_samples,) or not np.isfinite(raw).all() or np.max(np.abs(raw)) > 1.01:
            raise ValueError(f"Research input must be {self.window_samples} finite normalized mono float samples")
        with self.lock:
            if self.closed:
                raise RuntimeError("ResearchExtractor is closed")
            tensor = self.torch.from_numpy(np.ascontiguousarray(raw)).unsqueeze(0).to(self.cfg.device)
            jobs = [self.pool.submit(self._cm, tensor), self.pool.submit(self._phones, raw),
                    self.pool.submit(self._profile, tensor, raw)]
            try:
                vector, score = jobs[0].result()
                segments = jobs[1].result()
                profile, attributes = jobs[2].result()
            finally:
                # Drain all work before releasing the model lock, even after failure.
                for job in jobs:
                    try:
                        job.result()
                    except Exception:
                        continue
        return Features(vector, profile, segments, score,
            {**attributes, "extractor": self.id, "segments_kind": "xlsr-53-ctc", "cm_head_score": score,
             "profile_dimension": len(profile), "cm_dimension": len(vector)})

    def identify_language(self, audio: np.ndarray) -> tuple[str, str]:
        """Use the full posterior, respecting SpeechBrain's configured output domain."""
        raw = np.asarray(audio, dtype=np.float32)
        if raw.ndim != 1 or len(raw) == 0 or not np.isfinite(raw).all():
            raise ValueError("Language input must contain finite mono audio")
        with self.lock:
            if self.closed:
                raise RuntimeError("ResearchExtractor is closed")
            if self.lid is None:
                raise FileNotFoundError(f"Language model missing: {self.root / 'language' / 'hyperparams.yaml'}")
            with self.torch.inference_mode():
                posterior, _, _, labels = self.lid.classify_batch(
                    self.torch.from_numpy(raw).unsqueeze(0).to(self.cfg.device))
            values = posterior[0].detach().float().cpu().numpy()
        # Some SpeechBrain versions expose log probabilities; others expose
        # probabilities. Detect normalization; never mistake a log score for p.
        if np.all(values >= 0) and np.isclose(values.sum(), 1, atol=1e-3):
            confidence = float(values.max())
        else:
            exp = np.exp(values - values.max())
            confidence = float(exp.max() / exp.sum())
        return language_result(str(labels[0]), confidence)

    def close(self) -> None:
        """Idempotently drain work, release model references, and free cached CUDA RAM."""
        with self.lock:
            if self.closed:
                return
            self.closed = True
            if self.pool is not None:
                self.pool.shutdown(wait=True, cancel_futures=True)
                self.pool = None
            self.cm = self.phone = self.processor = self.lid = None
            self.profiles.clear()
            if hasattr(self, "torch") and self.torch.cuda.is_available():
                self.torch.cuda.empty_cache()
