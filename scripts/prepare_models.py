"""Explicit online preparation only. Runtime inference never downloads models."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strive.models.research import sha256


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--variant", choices=["mms-300m", "xls-r-2b"], default="mms-300m")
    p.add_argument("--output", default="models")
    p.add_argument("--download", action="store_true")
    p.add_argument("--include-language", action="store_true")
    p.add_argument("--seal", action="store_true")
    args = p.parse_args()
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)
    revisions_path = root / "revisions.json"
    revisions = json.loads(revisions_path.read_text()) if revisions_path.exists() else {}
    if args.download:
        from huggingface_hub import HfApi, snapshot_download
        models = [(f"nii-yamagishilab/{args.variant}-anti-deepfake", "nii-source"),
                  ("facebook/wav2vec2-xlsr-53-espeak-cv-ft", "phoneme")]
        if args.include_language:
            models.append(("speechbrain/lang-id-voxlingua107-ecapa", "language"))
        for repo, folder in models:
            revision = revisions.get(repo) or HfApi().model_info(repo).sha
            snapshot_download(repo, revision=revision, local_dir=root / folder)
            revisions[repo] = revision
        revisions_path.write_text(json.dumps(revisions, indent=2))
    if args.seal:
        metadata = json.loads((root / "cm-export.json").read_text())
        if not (root / "phoneme/config.json").exists():
            raise SystemExit("Missing phoneme model; download it before sealing")
        files = [root / "cm.pt"]
        for folder in ("phoneme", "language", "vox"):
            files.extend(p for p in (root / folder).rglob("*") if p.is_file() and ".cache" not in p.parts)
        metadata["sha256"] = {p.relative_to(root).as_posix(): sha256(p) for p in files}
        metadata["revisions"] = revisions
        vox = root / "vox/spec.json"
        if vox.exists():
            metadata["vox_profile"] = json.loads(vox.read_text())
        (root / "manifest.json").write_text(json.dumps(metadata, indent=2))
        print("Sealed local bundle; keep manifest.json with your evidence")


if __name__ == "__main__":
    main()
