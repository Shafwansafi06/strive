"""Build a reproducible language-partitioned index from explicitly labelled speech."""
import argparse
import csv
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strive.audio import RATE, decode
from strive.config import Settings
from strive.models.research import ResearchExtractor, sha256
from strive.retrieval import ReferenceIndex

REQUIRED = {"path", "label", "language", "speaker_id", "generator", "codec", "source_id", "split", "license"}


def read_manifest(path: str | Path) -> list[dict[str, str]]:
    path = Path(path)
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not REQUIRED.issubset(reader.fieldnames or []):
            raise ValueError("Manifest needs: " + ", ".join(sorted(REQUIRED)))
        rows = list(reader)
    if not rows:
        raise ValueError("Manifest is empty; supply labelled speech recordings")
    for row in rows:
        if row["label"] not in ("0", "1") or any(not row[k].strip() for k in REQUIRED):
            raise ValueError("Manifest rows need valid labels and complete provenance")
        row["absolute_path"] = str((path.parent / row["path"]).resolve())
        row["sha256"] = sha256(row["absolute_path"])
        row["language"] = row["language"].split("-")[0].lower()
    return rows


def assert_disjoint(reference: list[dict], evaluation: list[dict], holdout_generator: str | None = None) -> None:
    for key in ("sha256", "source_id", "speaker_id"):
        overlap = {r[key] for r in reference} & {r[key] for r in evaluation}
        if overlap:
            raise ValueError(f"Reference/evaluation leakage in {key}: {len(overlap)} overlaps")
    if holdout_generator and any(r["generator"] == holdout_generator for r in reference):
        raise ValueError("Held-out generator is present in the reference index")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("manifest")
    p.add_argument("--models", default="models")
    p.add_argument("--output", default="data/reference.npz")
    p.add_argument("--device", default="cpu")
    p.add_argument("--profile", choices=["acoustic", "vox"], default="acoustic")
    args = p.parse_args()
    rows = read_manifest(args.manifest)
    if any(r["split"] != "reference" for r in rows):
        raise SystemExit("Index manifest must contain only the reference split")
    cfg = Settings(mode="research", model_dir=args.models, device=args.device, profile_backend=args.profile)
    extractor = ResearchExtractor(cfg)
    vectors, labels, languages, ids = [], [], [], []
    try:
        for row in rows:
            x = decode(Path(row["absolute_path"]).read_bytes())
            for start in range(0, len(x) - 2 * RATE + 1, RATE):
                vector = extractor.extract(x[start:start + 2 * RATE]).cm
                vectors.append(vector); labels.append(int(row["label"])); languages.append(row["language"])
                ids.append(row["sha256"] + ":" + str(start))
        if set(labels) != {0, 1}:
            raise ValueError("Index requires both genuine and spoof recordings of at least 2 seconds")
        public_rows = [{k:v for k,v in row.items() if k not in ("absolute_path", "path")} for row in rows]
        index = ReferenceIndex(vectors, labels, languages, {"extractor_id": extractor.id, "demo_only": False,
            "manifest_sha256": sha256(args.manifest), "source_rows": public_rows}, ids)
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        index.save(args.output)
        print(json.dumps({"windows": len(vectors), "cm_dimension": len(vectors[0]), "languages": sorted(set(languages))}))
    finally:
        extractor.close()


if __name__ == "__main__":
    main()
