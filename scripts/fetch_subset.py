"""Fetch a small balanced subset out of a remote ZIP corpus using HTTP range requests.

CODEC-04 says to run the smoke benchmark on a small licensed set first. On a slow
link, downloading a 7.6 GB archive to use a few hundred clips is hours of waiting
for megabytes of audio. ZIP stores a central directory, so a server that honours
`Range` lets us read that directory and pull only the members we want.

Edinburgh DataShare serves ASVspoof 2019 with `Accept-Ranges: bytes`. Zenodo does
not (it ignores Range and returns the whole file), so the URL matters.

The subset is chosen from the official CM protocol, so labels, speaker IDs and
attack generators keep their real provenance. A filtered protocol is written
alongside the audio so scripts/download_data.py can build manifests from it
unchanged:

    python scripts/fetch_subset.py --root data/asv2019-subset --per-class 150
    python scripts/download_data.py asv2019 --root data/asv2019-subset \\
           --protocol data/asv2019-subset/subset.cm.eval.trl.txt \\
           --output data/manifests/asv2019-subset
"""
import argparse
from collections import defaultdict
import io
import random
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Edinburgh DataShare bitstream for ASVspoof2019 LA.zip. Range-capable.
DEFAULT_URL = ("https://datashare.ed.ac.uk/server/api/core/bitstreams/"
               "a9f87c35-f055-4015-80e2-2fdff0d46269/content")
PROTOCOL_DIR = "LA/ASVspoof2019_LA_cm_protocols/"
SPLITS = {"train": ("ASVspoof2019.LA.cm.train.trn.txt", "LA/ASVspoof2019_LA_train/flac/"),
          "dev": ("ASVspoof2019.LA.cm.dev.trl.txt", "LA/ASVspoof2019_LA_dev/flac/"),
          "eval": ("ASVspoof2019.LA.cm.eval.trl.txt", "LA/ASVspoof2019_LA_eval/flac/")}


class HTTPRangeFile(io.RawIOBase):
    """Minimal seekable read-only file over HTTP Range requests."""

    def __init__(self, url: str, timeout: int = 60) -> None:
        self.url, self.timeout, self.pos = url, timeout, 0
        request = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.headers.get("Accept-Ranges", "").lower() != "bytes":
                raise ValueError(f"Server does not advertise byte ranges: {url}")
            self.size = int(response.headers["Content-Length"])
        self.bytes_fetched = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self.pos, io.SEEK_END: self.size}[whence]
        self.pos = max(0, min(self.size, base + offset))
        return self.pos

    def tell(self) -> int:
        return self.pos

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = self.size - self.pos
        size = min(size, self.size - self.pos)
        if size <= 0:
            return b""
        end = self.pos + size - 1
        request = urllib.request.Request(self.url, headers={"Range": f"bytes={self.pos}-{end}"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            if response.status != 206:
                raise ValueError(f"Expected 206 partial content, got {response.status}")
            data = response.read()
        self.pos += len(data)
        self.bytes_fetched += len(data)
        return data

    def readinto(self, buffer) -> int:
        data = self.read(len(buffer))
        buffer[:len(data)] = data
        return len(data)


def choose(protocol_text: str, per_class: int, seed: int) -> list[tuple[str, str, str, str]]:
    """Balanced pick from the official protocol: (speaker, trial, generator, label).

    Spoof clips are spread evenly across attack generators so a smoke benchmark is
    not dominated by whichever attack happens to appear first.
    """
    bonafide, by_generator = [], defaultdict(list)
    for line in protocol_text.splitlines():
        parts = line.split()
        if len(parts) != 5:
            continue
        speaker, trial, _, generator, label = parts
        (bonafide if label == "bonafide" else by_generator[generator]).append(
            (speaker, trial, generator, label))

    rng = random.Random(seed)
    rng.shuffle(bonafide)
    picked = bonafide[:per_class]

    generators = sorted(by_generator)
    if not generators:
        raise ValueError("Protocol contains no spoof trials")
    quota, spoof = per_class // len(generators) + 1, []
    for generator in generators:
        clips = by_generator[generator]
        rng.shuffle(clips)
        spoof.extend(clips[:quota])
    rng.shuffle(spoof)
    return picked + spoof[:per_class]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--root", required=True, help="destination directory")
    parser.add_argument("--split", choices=sorted(SPLITS), default="eval")
    parser.add_argument("--per-class", type=int, default=150,
                        help="clips per class; total is roughly twice this")
    parser.add_argument("--seed", type=int, default=26104)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    protocol_name, flac_prefix = SPLITS[args.split]

    print(f"Opening remote archive: {args.url}")
    stream = HTTPRangeFile(args.url)
    print(f"  archive size {stream.size / 1e9:.2f} GB")
    with zipfile.ZipFile(stream) as archive:
        names = set(archive.namelist())
        print(f"  central directory read, {len(names)} members "
              f"({stream.bytes_fetched / 1e6:.1f} MB fetched so far)")

        protocol_member = PROTOCOL_DIR + protocol_name
        if protocol_member not in names:
            raise SystemExit(f"Protocol not found in archive: {protocol_member}")
        protocol_text = archive.read(protocol_member).decode()
        selected = choose(protocol_text, args.per_class, args.seed)
        labels = {"bonafide": 0, "spoof": 0}
        for *_, label in selected:
            labels[label] += 1
        print(f"  selected {len(selected)} trials "
              f"({labels['bonafide']} bonafide, {labels['spoof']} spoof) "
              f"across {len({g for _, _, g, l in selected if l == 'spoof'})} generators")

        audio_dir = root / "LA" / f"ASVspoof2019_LA_{args.split}" / "flac"
        audio_dir.mkdir(parents=True, exist_ok=True)
        written, missing = 0, []
        for speaker, trial, generator, label in selected:
            member = f"{flac_prefix}{trial}.flac"
            if member not in names:
                missing.append(trial)
                continue
            target = audio_dir / f"{trial}.flac"
            if not target.exists():
                target.write_bytes(archive.read(member))
            written += 1
            if written % 25 == 0:
                print(f"    {written}/{len(selected)} clips "
                      f"({stream.bytes_fetched / 1e6:.1f} MB)", flush=True)

    if missing:
        raise SystemExit(f"{len(missing)} selected trials absent from archive, e.g. {missing[:3]}")

    # Filtered protocol so download_data.py can build manifests without the full corpus.
    subset_protocol = root / f"subset.cm.{args.split}.trl.txt"
    subset_protocol.write_text("".join(
        f"{speaker} {trial} - {generator} {label}\n" for speaker, trial, generator, label in selected))

    print(f"\nWrote {written} clips to {audio_dir}")
    print(f"Filtered protocol: {subset_protocol}")
    print(f"Total downloaded: {stream.bytes_fetched / 1e6:.1f} MB "
          f"instead of {stream.size / 1e9:.2f} GB")
    print("\nNext:")
    print(f"  python scripts/download_data.py asv2019 --root {root} \\")
    print(f"         --protocol {subset_protocol} --output data/manifests/{root.name}")


if __name__ == "__main__":
    main()
