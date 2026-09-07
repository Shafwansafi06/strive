"""Typed runtime and experiment settings; core requires only the standard library."""
from dataclasses import dataclass
import json
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    mode: str = "demo"
    sample_rate: int = 16000
    window_s: int = 2
    stride_s: int = 1
    bootstrap_s: int = 5
    min_voiced_s: float = 4.0
    global_k: int = 20
    session_k: int = 10
    global_gate: float = 0.30
    similarity_gate: float = 0.70
    alpha: float = 0.70
    warning: float = 0.50
    alert: float = 0.75
    max_session_entries: int = 120
    max_call_s: int = 600
    idle_timeout_s: int = 60
    max_sessions: int = 8
    min_partition_entries: int = 20
    min_neighbor_similarity: float = -1.0
    device: str = "cpu"
    model_dir: str = "models"
    index_path: str = "data/reference.npz"
    audit_path: str = "data/audit.sqlite3"
    profile_backend: str = "acoustic"
    require_language_model: bool = True
    weight_preset: str = "proposed"
    raise_model_errors: bool = False
    api_token: str = ""

    def __post_init__(self) -> None:
        if self.weight_preset not in ("equal", "proposed", "global_heavy", "session_heavy"):
            raise ValueError("Unknown weight preset")
        if self.mode not in ("demo", "research"):
            raise ValueError("mode must be demo or research")
        if (self.sample_rate, self.window_s, self.stride_s) != (16000, 2, 1):
            raise ValueError("This build implements the STRIVE 16 kHz / 2 s / 1 s contract")
        if not 0 <= self.alpha < 1 or not 0 < self.warning < self.alert <= 1:
            raise ValueError("Invalid EMA or alert thresholds")
        if not 0 < self.global_gate < 1 or not 0 < self.similarity_gate < 1:
            raise ValueError("Invalid bootstrap/update gate")
        if min(self.global_k, self.session_k, self.max_session_entries, self.max_sessions) < 1:
            raise ValueError("Counts must be positive")

    @classmethod
    def from_env(cls) -> "Settings":
        path = os.environ.get("STRIVE_CONFIG")
        values = json.loads(Path(path).read_text()) if path else {}
        for field in ("mode", "model_dir", "index_path", "audit_path", "device", "api_token"):
            if "STRIVE_" + field.upper() in os.environ:
                values[field] = os.environ["STRIVE_" + field.upper()]
        return cls(**values)
