"""Import consented/licensed presentation audio with explicit provenance."""
import argparse
import csv
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from strive.audio import decode


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--genuine", required=True)
    parser.add_argument("--spoof", required=True)
    parser.add_argument("--mid-call", required=True)
    parser.add_argument("--license", required=True)
    parser.add_argument("--provenance", required=True)
    parser.add_argument("--language", default="und")
    parser.add_argument("--attack-onset-sec", type=float, required=True)
    args = parser.parse_args()
    if args.attack_onset_sec < 0:
        raise SystemExit("--attack-onset-sec must be non-negative ground truth")
    target_dir = ROOT / "data" / "demo" / "audio"
    target_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    cases = [("genuine", "Genuine Call", args.genuine, "genuine", None),
             ("spoof", "Deepfake / Spoof Call", args.spoof, "spoof", 0.0),
             ("mid_call", "Mid-Call Voice Replacement", args.mid_call, "spoof", args.attack_onset_sec)]
    for identifier, display, source_name, label, onset in cases:
        source = Path(source_name).resolve()
        if not source.is_file():
            raise SystemExit(f"Missing audio: {source}")
        audio = decode(source.read_bytes())
        duration = len(audio) / 16000
        audio.fill(0)
        if onset is not None and onset >= duration:
            raise SystemExit(f"Attack onset must be inside {source.name}")
        target = target_dir / ("mid_call_attack" if identifier == "mid_call" else identifier)
        target = target.with_suffix(source.suffix.lower())
        shutil.copy2(source, target)
        rows.append({"id": identifier, "display_name": display,
            "path": target.relative_to(ROOT / "data" / "demo").as_posix(),
            "source_type": "consented_or_licensed_audio", "label": label,
            "language": args.language, "speaker_id": "operator-supplied",
            "generator": "operator-supplied" if label == "spoof" else "none",
            "codec": source.suffix.lower().lstrip("."), "duration": round(duration, 3),
            "attack_onset_sec": "" if onset is None else onset,
            "license": args.license, "provenance": args.provenance,
            "notes": "Labels and onset supplied by operator; review before use"})
    manifest = ROOT / "data" / "demo" / "manifest.csv"
    with manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    print(f"Imported {len(rows)} consented/licensed scenarios: {manifest}")


if __name__ == "__main__":
    main()
