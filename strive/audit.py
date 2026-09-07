import json
from pathlib import Path
import sqlite3
import threading
import time


class Audit:
    def __init__(self, path):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        self.db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, call_id TEXT, timestamp REAL, kind TEXT, payload TEXT)")
        self.db.commit()

    def write(self, call_id, kind, value):
        # Allow-list excludes PCM, embeddings, voiceprints, and acoustic attributes.
        keys = ("session_age_s", "s_risk", "context_risk", "decision_risk", "track_scores", "weights",
                "alert_level", "recommended_action", "reasons", "model_version", "pipeline_version", "mode", "demo_only",
                "latency_ms", "bootstrap", "status", "method")
        payload = {k: value[k] for k in keys if k in value}
        with self.lock:
            self.db.execute("INSERT INTO events(call_id,timestamp,kind,payload) VALUES(?,?,?,?)",
                            (call_id, time.time(), kind, json.dumps(payload, allow_nan=False)))
            self.db.commit()

    def read(self, call_id):
        with self.lock:
            rows = self.db.execute("SELECT timestamp,kind,payload FROM events WHERE call_id=? ORDER BY id DESC LIMIT 1000", (call_id,)).fetchall()
        return [{"timestamp": t, "kind": k, **json.loads(p)} for t, k, p in reversed(rows)]

    def purge(self, days=7):
        with self.lock:
            self.db.execute("DELETE FROM events WHERE timestamp < ?", (time.time() - days * 86400,))
            self.db.commit()

    def close(self):
        self.db.close()
