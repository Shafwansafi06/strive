"""CODEC-01/02/03: explicit OFFLINE evaluation preprocessing.

Not part of the live audio path and never invoked by the server. Produces codec /
bandwidth / noise / packet-loss variants of a clean corpus, plus a paired manifest
where every derived clip keeps its original `source_id`, `speaker_id` and `label`
so no split leakage can be introduced by augmentation.

Two modes:

    augment.py one   SOURCE OUTPUT --condition opus_16k
    augment.py matrix --manifest data/manifest.csv --out-dir data/degraded \
                      --out-manifest data/manifest_matrix.csv

Codec failure is an explicit error. Nothing is silently passed through unchanged.
"""
import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import soundfile as sf
from strive.audio import decode, RATE
from build_index import REQUIRED, read_manifest

DEFAULT_SEED = 26104


@dataclass(frozen=True)
class Condition:
    """One reproducible degradation. `codec=None` means no encode/decode leg."""
    name: str
    codec: str | None = None
    bitrate_kbps: int | None = None
    noise_snr_db: float | None = None
    packet_loss: float = 0.

    def describe(self) -> str:
        parts = []
        if self.codec:
            parts.append(f"{self.codec}" + (f"@{self.bitrate_kbps}k" if self.bitrate_kbps else ""))
        if self.noise_snr_db is not None:
            parts.append(f"noise {self.noise_snr_db:g} dB SNR")
        if self.packet_loss:
            parts.append(f"{self.packet_loss:.1%} packet loss")
        return ", ".join(parts) or "unmodified"


# CODEC-02: the Opus bitrate ladder is the minimum required set.
CONDITIONS: dict[str, Condition] = {c.name: c for c in [
    Condition("clean"),
    Condition("opus_6k", "opus", 6),
    Condition("opus_12k", "opus", 12),
    Condition("opus_16k", "opus", 16),
    Condition("opus_24k", "opus", 24),
    Condition("opus_32k", "opus", 32),
    Condition("g711_ulaw", "g711_ulaw"),
    Condition("g711_alaw", "g711_alaw"),
    Condition("narrowband_8k", "narrowband"),
    Condition("noise_20db", noise_snr_db=20),
    Condition("noise_10db", noise_snr_db=10),
    Condition("noise_5db", noise_snr_db=5),
    Condition("loss_1pct", packet_loss=.01),
    Condition("loss_3pct", packet_loss=.03),
    Condition("loss_5pct", packet_loss=.05),
]}

# CODEC-04's minimum smoke set: clean, two Opus rates, G.711, narrowband, one noise.
SMOKE_CONDITIONS = ["clean", "opus_16k", "opus_32k", "g711_ulaw", "narrowband_8k", "noise_10db"]

CODEC_LEGS = {
    "g711_ulaw": (["-ar", "8000", "-c:a", "pcm_mulaw", "-f", "mulaw"],
                  ["-f", "mulaw", "-ar", "8000", "-ac", "1"]),
    "g711_alaw": (["-ar", "8000", "-c:a", "pcm_alaw", "-f", "alaw"],
                  ["-f", "alaw", "-ar", "8000", "-ac", "1"]),
    "narrowband": (["-ar", "8000", "-f", "s16le"],
                   ["-f", "s16le", "-ar", "8000", "-ac", "1"]),
}


def ffmpeg(arguments: list[str], payload: bytes, what: str) -> bytes:
    result = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", *arguments],
                            input=payload, capture_output=True, timeout=60)
    if result.returncode or not result.stdout:
        detail = result.stderr.decode("utf-8", "replace").strip()[:400]
        raise RuntimeError(f"{what} failed (ffmpeg exit {result.returncode}): {detail}")
    return result.stdout


def apply_codec(x: np.ndarray, condition: Condition) -> np.ndarray:
    """Round-trip through a real encoder. Raises on any codec failure."""
    if condition.codec is None:
        return x
    if condition.codec == "opus":
        encode = ["-c:a", "libopus", "-b:a", f"{condition.bitrate_kbps}k", "-f", "ogg"]
        decode_leg = ["-f", "ogg"]
    elif condition.codec in CODEC_LEGS:
        encode, decode_leg = CODEC_LEGS[condition.codec]
    else:
        raise ValueError(f"Unknown codec: {condition.codec}")
    encoded = ffmpeg(["-f", "f32le", "-ar", str(RATE), "-ac", "1", "-i", "pipe:0", *encode, "pipe:1"],
                     x.astype("<f4").tobytes(), f"{condition.name} encode")
    decoded = ffmpeg([*decode_leg, "-i", "pipe:0", "-ar", str(RATE), "-ac", "1", "-f", "f32le", "pipe:1"],
                     encoded, f"{condition.name} decode")
    return np.frombuffer(decoded, dtype="<f4").copy()


def degrade(x: np.ndarray, condition: Condition, seed: int = DEFAULT_SEED) -> np.ndarray:
    """Codec leg, then additive noise, then packet loss. Deterministic for a seed.

    Always works on a copy: the packet-loss step writes in place, and callers
    reuse one decoded source array across every condition in the matrix.
    """
    x = apply_codec(np.array(x, dtype=np.float32, copy=True), condition)
    rng = np.random.default_rng(seed)
    if condition.noise_snr_db is not None:
        power = float(np.sqrt(np.mean(x * x)))
        if power > 0:
            x = x + rng.normal(0, power / (10 ** (condition.noise_snr_db / 20)), len(x)).astype(np.float32)
    if condition.packet_loss:
        # 20 ms erasures, the granularity a real jitter buffer drops at.
        for start in range(0, len(x), 320):
            if rng.random() < condition.packet_loss:
                x[start:start + 320] = 0
    return np.clip(x, -1, 1).astype(np.float32)


def output_path(out_dir: Path, condition: str, source_id: str) -> Path:
    """Deterministic, collision-free naming: <out_dir>/<condition>/<source_id>.wav."""
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in source_id)
    return out_dir / condition / f"{safe}.wav"


def validate_rows(rows: list[dict]) -> None:
    """CODEC-03: catch duplicate and conflicting metadata before anything is written."""
    seen: dict[tuple[str, str], dict] = {}
    identity: dict[str, tuple] = {}
    for row in rows:
        key = (row["source_id"], row["condition"])
        if key in seen:
            raise ValueError(f"Duplicate source_id/condition pair: {key}")
        seen[key] = row
        # A source_id must describe one recording, whatever the condition.
        fingerprint = (row["label"], row["speaker_id"], row["language"])
        if row["source_id"] in identity and identity[row["source_id"]] != fingerprint:
            raise ValueError(
                f"Conflicting metadata for source_id {row['source_id']}: "
                f"{identity[row['source_id']]} vs {fingerprint}")
        identity[row["source_id"]] = fingerprint


def build_matrix(manifest: str | Path, out_dir: Path, conditions: list[str],
                 seed: int = DEFAULT_SEED, limit: int | None = None) -> list[dict]:
    rows = read_manifest(manifest)
    if limit:
        rows = rows[:limit]
    produced = []
    for source in rows:
        audio = decode(Path(source["absolute_path"]).read_bytes())
        for name in conditions:
            condition = CONDITIONS[name]
            target = output_path(out_dir, name, source["source_id"])
            target.parent.mkdir(parents=True, exist_ok=True)
            sf.write(target, degrade(audio, condition, seed), RATE, subtype="PCM_16")
            produced.append({**{k: source[k] for k in REQUIRED},
                             "path": str(target),
                             "codec": name,
                             "condition": name,
                             "condition_detail": condition.describe()})
    validate_rows(produced)
    return produced


def write_manifest(rows: list[dict], path: Path) -> None:
    columns = sorted(REQUIRED) + ["condition", "condition_detail"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    one = sub.add_parser("one", help="degrade a single file")
    one.add_argument("source")
    one.add_argument("output")
    one.add_argument("--condition", choices=sorted(CONDITIONS), default="g711_ulaw")
    one.add_argument("--seed", type=int, default=DEFAULT_SEED)

    matrix = sub.add_parser("matrix", help="build the full condition matrix + paired manifest")
    matrix.add_argument("--manifest", required=True)
    matrix.add_argument("--out-dir", default="data/degraded")
    matrix.add_argument("--out-manifest", default="data/manifest_matrix.csv")
    matrix.add_argument("--conditions", nargs="+", default=SMOKE_CONDITIONS,
                        choices=sorted(CONDITIONS))
    matrix.add_argument("--all", action="store_true", help="use every registered condition")
    matrix.add_argument("--limit", type=int, help="first N source clips only")
    matrix.add_argument("--seed", type=int, default=DEFAULT_SEED)

    sub.add_parser("list", help="print the registered conditions")
    args = parser.parse_args()

    if args.command == "list":
        for name, condition in CONDITIONS.items():
            print(f"{name:16s} {condition.describe()}")
        return

    if args.command == "one":
        audio = decode(Path(args.source).read_bytes())
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        sf.write(output, degrade(audio, CONDITIONS[args.condition], args.seed), RATE, subtype="PCM_16")
        print(f"Wrote explicit offline evaluation artifact: {output}")
        print("Keep its source_id and speaker_id identical to the original to prevent split leakage.")
        return

    conditions = sorted(CONDITIONS) if args.all else args.conditions
    rows = build_matrix(args.manifest, Path(args.out_dir), conditions, args.seed, args.limit)
    write_manifest(rows, Path(args.out_manifest))
    print(f"Wrote {len(rows)} clips across {len(conditions)} conditions to {args.out_dir}")
    print(f"Paired manifest: {args.out_manifest}")
    print("Every derived clip shares its source_id with the clean original; "
          "split on source_id or speaker_id, never on path.")


if __name__ == "__main__":
    main()
