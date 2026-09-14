"""Capture deterministic presentation scenario events through the WebSocket API."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["STRIVE_CONFIG"] = str(ROOT / "config/presentation.json")
from fastapi.testclient import TestClient
from strive.api import create_app
from strive.demo import PRESENTATION_SCENARIOS


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="evidence/sih-final/scenario-events.json")
    args = parser.parse_args()
    report = {"created_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Deterministic procedural DSP scenarios; not a detection accuracy evaluation",
        "python": platform.python_version(), "platform": platform.platform(),
        "mode": "demo", "neural_inference": False, "scenarios": {}}
    with TestClient(create_app()) as client:
        for name, metadata in PRESENTATION_SCENARIOS.items():
            call = client.post("/v1/calls", json={"context": {"amount_inr": 1_000_000,
                "urgent": True, "new_beneficiary": True}}).json()
            events = []; complete = None
            with client.websocket_connect(call["ws_path"]) as ws:
                ws.send_json({"token": ""}); ws.receive_json()
                ws.send_json({"type": "playback", "scenario": name, "mode": "accelerated"})
                ws.receive_json()
                while complete is None:
                    message = ws.receive_json()
                    if message["type"] == "events": events.extend(message["events"])
                    elif message["type"] == "playback_complete": complete = message
            levels = [event["state"] for event in events]
            report["scenarios"][name] = {"metadata": metadata, "windows": len(events),
                "bootstrap": events[-1]["bootstrap"] if events else None,
                "final_authenticity_risk": events[-1]["authenticity_risk"] if events else None,
                "final_decision_risk": events[-1]["decision_risk"] if events else None,
                "first_review_s": next((e["session_age_s"] for e in events if e["state"] == "REVIEW"), None),
                "first_high_s": complete["first_high_sec"],
                "time_to_alert_s": complete["time_to_alert_sec"],
                "states_observed": list(dict.fromkeys(levels)), "events": events}
            client.delete("/v1/calls/" + call["call_id"])
    target = ROOT / args.output; target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    summary = {name: {k: value for k, value in result.items() if k != "events"}
               for name, result in report["scenarios"].items()}
    print(json.dumps(summary, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
