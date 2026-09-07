"""Exact normalized inner-product retrieval. Labels: genuine=0, spoof=1."""
from collections import deque
import json
from pathlib import Path
import numpy as np
import faiss
from .features import unit, Features


class ReferenceIndex:
    def __init__(self, embeddings: np.ndarray | list, labels: np.ndarray | list, languages: np.ndarray | list,
                 metadata: dict, ids: np.ndarray | list | None = None) -> None:
        x = np.asarray(embeddings, dtype=np.float32)
        y = np.asarray(labels)
        lang = np.asarray(languages, dtype=str)
        if x.ndim != 2 or len(x) == 0 or len(x) != len(y) or len(y) != len(lang):
            raise ValueError("Reference index shapes do not match")
        if not np.isfinite(x).all() or np.any(np.linalg.norm(x, axis=1) < 1e-9):
            raise ValueError("Reference embeddings must be finite nonzero vectors")
        if not np.isin(y, [0, 1]).all():
            raise ValueError("Reference labels must be 0 or 1")
        self.x, self.y, self.languages = unit(x), y.astype(int), lang
        self.metadata = metadata
        self.ids = np.asarray(ids if ids is not None else [str(i) for i in range(len(x))], dtype=str)
        self.partitions = {}
        for key in ["global", *sorted(set(lang) - {"global"})]:
            positions = np.arange(len(x)) if key == "global" else np.where(lang == key)[0]
            index = faiss.IndexFlatIP(x.shape[1])
            index.add(self.x[positions])
            self.partitions[key] = (index, positions)

    def query(self, vector: np.ndarray, language: str, k: int = 20, min_entries: int = 20,
              min_similarity: float = -1) -> tuple[float | None, dict]:
        part = self.partitions.get(language)
        route = language
        fallback = part is None or part[0].ntotal < min_entries or len(set(self.y[part[1]])) < 2
        if fallback:
            part, route = self.partitions["global"], "global"
        if part[0].ntotal < min_entries or len(set(self.y[part[1]])) < 2:
            return None, {"route": route, "available": False, "reason": "INDEX_TOO_SMALL_OR_SINGLE_CLASS"}
        q = np.asarray(vector, dtype=np.float32)
        if q.shape != (self.x.shape[1],) or not np.isfinite(q).all() or np.linalg.norm(q) < 1e-9:
            raise ValueError("CM/index embedding mismatch")
        sims, local = part[0].search(unit(q)[None], min(k, part[0].ntotal))
        positions = part[1][local[0]]
        available = float(sims[0].max()) >= min_similarity
        info = {"route": route, "fallback": bool(fallback), "available": available,
                "neighbors": len(positions), "fake_neighbors": int(self.y[positions].sum()),
                "mean_similarity": round(float(sims.mean()), 4)}
        return float(self.y[positions].mean()) if available else None, info

    def save(self, path: str | Path) -> None:
        np.savez_compressed(path, embeddings=self.x, labels=self.y, languages=self.languages,
                            ids=self.ids, metadata=json.dumps(self.metadata))

    @classmethod
    def load(cls, path: str | Path) -> "ReferenceIndex":
        with np.load(path, allow_pickle=False) as d:
            return cls(d["embeddings"], d["labels"], d["languages"], json.loads(str(d["metadata"])), d["ids"])


class SessionProfile:
    """Persistent indexes with incremental adds and rebuilds only on eviction."""
    def __init__(self, capacity: int = 120, k: int = 10) -> None:
        if capacity < 1 or k < 1:
            raise ValueError("capacity and k must be positive")
        self.entries = deque(maxlen=capacity)
        self.k = k
        self.profile_index = None
        self.phone_index = None
        self.token_indexes = {}
        self.rebuild_count = 0

    def _append_indexes(self, entry: tuple) -> None:
        profile, segments = entry
        if self.profile_index is None:
            self.profile_index = faiss.IndexFlatIP(len(profile))
        self.profile_index.add(profile[None])
        for token, vector in segments:
            if self.phone_index is None:
                self.phone_index = faiss.IndexFlatIP(len(vector))
            self.phone_index.add(vector[None])
            if token not in self.token_indexes:
                self.token_indexes[token] = faiss.IndexFlatIP(len(vector))
            self.token_indexes[token].add(vector[None])

    def _rebuild(self) -> None:
        self.profile_index = self.phone_index = None
        self.token_indexes.clear()
        for entry in self.entries:
            self._append_indexes(entry)
        self.rebuild_count += 1

    def add(self, features: "Features") -> None:
        p = np.asarray(features.profile, dtype=np.float32)
        segments = [(s.token, np.asarray(s.vector, dtype=np.float32)) for s in features.segments]
        if len({len(v) for _, v in segments}) > 1:
            raise ValueError("Mixed phoneme dimensions in one window")
        for vector in [p, *[v for _, v in segments]]:
            if vector.ndim != 1 or not np.isfinite(vector).all() or np.linalg.norm(vector) < 1e-12:
                raise ValueError("SPS needs finite nonzero vectors")
        if self.profile_index is not None and len(p) != self.profile_index.d:
            raise ValueError("Profile dimension changed within a call")
        if self.phone_index is not None and any(len(v) != self.phone_index.d for _, v in segments):
            raise ValueError("Phoneme dimension changed within a call")
        overflow = len(self.entries) == self.entries.maxlen
        self.entries.append((unit(p.copy()), [(token, unit(v.copy())) for token, v in segments]))
        if overflow:
            self._rebuild()
        else:
            self._append_indexes(self.entries[-1])

    def similarity(self, features: "Features") -> float | None:
        if self.profile_index is None or not self.entries:
            return None
        if len(features.profile) != self.profile_index.d:
            raise ValueError("Profile dimension changed within a call")
        sim, _ = self.profile_index.search(unit(features.profile)[None], min(self.k, self.profile_index.ntotal))
        values = [float(np.clip(sim.mean(), 0, 1))]
        for segment in features.segments:
            index = self.phone_index if segment.token < 0 else self.token_indexes.get(segment.token)
            if index is None or index.ntotal == 0:
                continue
            if len(segment.vector) != index.d:
                raise ValueError("Phoneme dimension changed within a call")
            scores, _ = index.search(unit(segment.vector)[None], min(self.k, index.ntotal))
            values.append(float(np.clip(scores.mean(), 0, 1)))
        return float(.5 * values[0] + .5 * np.mean(values[1:])) if len(values) > 1 else values[0]

    def clear(self) -> None:
        for profile, segments in self.entries:
            profile.fill(0)
            for _, vector in segments:
                vector.fill(0)
        self.entries.clear()
        if self.profile_index is not None:
            self.profile_index.reset()
        if self.phone_index is not None:
            self.phone_index.reset()
        for index in self.token_indexes.values():
            index.reset()
        self.profile_index = self.phone_index = None
        self.token_indexes.clear()
