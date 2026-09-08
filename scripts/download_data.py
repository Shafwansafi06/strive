"""Download and prepare ASVspoof2019-LA, ASVspoof2021-DF and Common Voice.

Uses standard-library HTTPS/checksums/archive readers and build_index validation.
Common Voice uses a user-authorized archive/URL, not an access-control bypass.
No audio is included in releases. Official splits and speaker identity are retained.
"""
import argparse
import csv
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile
import urllib.error
import urllib.request
import zipfile
from itertools import combinations
from typing import Any
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_index import REQUIRED, assert_disjoint, read_manifest

ASV2019 = 'https://zenodo.org/api/records/6906306'
ASV2021 = 'https://zenodo.org/api/records/4835108'
DF_KEYS = 'https://www.asvspoof.org/asvspoof2021/DF-keys-full.tar.gz'
LABELS = {'bonafide':'0', 'spoof':'1'}


def digest(path: Path, algorithm: str = 'sha256') -> str:
    """Compute an archive checksum using bounded memory."""
    h = hashlib.new(algorithm)
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def download(url: str, output: Path, checksum: str, token: str | None = None,
             attempts: int = 8) -> Path:
    """Fetch HTTPS to a temporary path and commit only after checksum verification.

    Resumes with HTTP Range between attempts. A slow or flaky link drops multi-GB
    transfers part way through, and `copyfileobj` returns normally on a truncated
    body, so a short read is checked explicitly against Content-Length rather than
    being left for the final checksum to catch after hours of transfer.

    The checksum remains the only thing that can commit the file: resumption only
    decides where to restart, never whether the result is trusted.
    """
    if not url.startswith('https://'):
        raise ValueError('Download URL must use HTTPS')
    algorithm, expected = checksum.split(':',1)
    if algorithm not in ('sha256','md5') or not expected:
        raise ValueError('Use a published sha256:... or md5:... checksum')
    output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists() and digest(output,algorithm) == expected:
        return output
    temporary = output.with_suffix(output.suffix+'.partial')
    base_headers = {'User-Agent':'STRIVE-research-data/0.2'}
    if token:
        base_headers['Authorization'] = 'Bearer '+token
    # Explicit authenticated URLs must not redirect credentials to another host.
    class SameHostRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req: urllib.request.Request, fp: Any, code: int, msg: str,
                             hdrs: Any, newurl: str) -> urllib.request.Request | None:
            from urllib.parse import urlsplit
            if not newurl.startswith('https://') or (token and urlsplit(newurl).netloc != urlsplit(url).netloc):
                raise ValueError('Refusing unsafe download redirect')
            return super().redirect_request(req,fp,code,msg,hdrs,newurl)
    opener = urllib.request.build_opener(SameHostRedirect())
    total = None
    for attempt in range(1,attempts+1):
        have = temporary.stat().st_size if temporary.exists() else 0
        if total is not None and have == total:
            break
        headers = dict(base_headers)
        if have:
            headers['Range'] = f'bytes={have}-'
        try:
            with opener.open(urllib.request.Request(url,headers=headers),timeout=120) as source:
                resuming = source.status == 206
                if have and not resuming:
                    # Server ignored Range (Zenodo does). Start over rather than
                    # appending a second copy of the file onto the partial one.
                    have = 0
                declared = source.headers.get('Content-Length')
                if declared is not None:
                    total = int(declared)+have
                with temporary.open('ab' if resuming and have else 'wb') as target:
                    shutil.copyfileobj(source,target,8*1024*1024)
        except (urllib.error.URLError,TimeoutError,ConnectionError,OSError) as error:
            if attempt == attempts:
                raise
            print(f'  {output.name}: {type(error).__name__} at '
                  f'{temporary.stat().st_size if temporary.exists() else 0}/{total} bytes, '
                  f'retrying ({attempt}/{attempts})',flush=True)
            continue
        got = temporary.stat().st_size
        if total is None or got >= total:
            break
        if attempt == attempts:
            raise ValueError(f'Truncated download for {output.name}: {got}/{total} bytes')
        print(f'  {output.name}: short read {got}/{total} bytes, '
              f'resuming ({attempt}/{attempts})',flush=True)
    if digest(temporary,algorithm) != expected:
        raise ValueError('Checksum mismatch for '+output.name)
    # The partial file is deliberately NOT removed on failure, so the next run
    # resumes from where this one stopped instead of restarting the transfer.
    temporary.replace(output)
    return output


def safe_target(root: Path, name: str) -> Path:
    """Reject traversal and platform-dependent archive paths."""
    if '\\' in name or ':' in name:
        raise ValueError('Unsafe archive member: '+name)
    target = (root/name).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError('Archive member escapes extraction directory')
    return target


def extract_tar(stream: tarfile.TarFile, root: Path) -> None:
    """Extract regular files/directories only; reject archive symlinks and devices."""
    for member in stream:
        target = safe_target(root,member.name)
        if member.isdir():
            target.mkdir(parents=True,exist_ok=True)
        elif member.isfile():
            target.parent.mkdir(parents=True,exist_ok=True)
            with stream.extractfile(member) as source, target.open('wb') as dest:
                shutil.copyfileobj(source,dest)
        else:
            raise ValueError('Unsupported archive member: '+member.name)


def extract_archive(path: Path, root: Path) -> None:
    """Unpack a ZIP or TAR without executing code or following archive links."""
    root.mkdir(parents=True,exist_ok=True)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                if (member.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('ZIP symlinks are not accepted')
                target = safe_target(root,member.filename)
                if member.is_dir():
                    target.mkdir(parents=True,exist_ok=True)
                else:
                    target.parent.mkdir(parents=True,exist_ok=True)
                    with archive.open(member) as source, target.open('wb') as dest:
                        shutil.copyfileobj(source,dest)
    else:
        with tarfile.open(path,'r|*') as archive:
            extract_tar(archive,root)


class PartReader(io.RawIOBase):
    """Read split gzip archives sequentially without duplicating 34 GB on disk."""
    def __init__(self, paths: list[Path]) -> None:
        self.paths = iter(paths); self.current = None
    def readable(self) -> bool:
        return True
    def readinto(self, buffer: bytearray) -> int:
        while True:
            if self.current is None:
                path = next(self.paths,None)
                if path is None:
                    return 0
                self.current = path.open('rb')
            count = self.current.readinto(buffer)
            if count:
                return count
            self.current.close(); self.current = None
    def close(self) -> None:
        if self.current:
            self.current.close()
        super().close()


def download_asv(dataset: str, root: Path) -> None:
    """Use official Zenodo file metadata and checksums, then safely extract."""
    api = ASV2019 if dataset == 'asv2019' else ASV2021
    with urllib.request.urlopen(api,timeout=60) as response:
        metadata = json.load(response)
    files = [f for f in metadata['files'] if f['key'] == 'LA.zip' or
             (dataset == 'asv2021' and f['key'].startswith('ASVspoof2021_DF_eval_part'))]
    if not files:
        raise ValueError('Expected official archives missing from record metadata')
    root.mkdir(parents=True,exist_ok=True)
    needed = sum(f['size'] for f in files)*3
    if shutil.disk_usage(root).free < needed:
        raise OSError(f'Allow at least {needed/1e9:.1f} GB free for downloads and extraction')
    (root/'zenodo-record.json').write_text(json.dumps(metadata,indent=2))
    paths = [download(f['links']['self'],root/'archives'/f['key'],f['checksum']) for f in sorted(files,key=lambda f:f['key'])]
    if dataset == 'asv2019':
        extract_archive(paths[0],root)
    else:
        # gzip supports concatenated members; ignore_zeros also accepts separately
        # tarred parts, while a single split tar stream requires no disk join.
        with PartReader(paths) as raw, io.BufferedReader(raw) as stream, gzip.GzipFile(fileobj=stream) as uncompressed:
            with tarfile.open(fileobj=uncompressed,mode='r|',ignore_zeros=True) as archive:
                extract_tar(archive,root)
        keys = download(DF_KEYS,root/'archives'/'DF-keys-full.tar.gz','md5:dabbc5628de4fcef53036c99ac7ab93a')
        extract_archive(keys,root)


def asv_rows(root: Path, dataset: str, protocol: Path | None = None) -> list[dict]:
    """Read official CM protocols; reject masked stage-1 or missing provenance."""
    audio = {}
    for path in root.rglob('*.flac'):
        if path.stem in audio:
            raise ValueError('Duplicate audio trial ID: '+path.stem)
        audio[path.stem] = path.resolve()
    protocols = [protocol] if protocol else (sorted(root.rglob('ASVspoof2019.LA.cm.*.txt')) if dataset == 'asv2019' else
        [p for p in root.rglob('trial_metadata.txt') if p.parent.name == 'CM' and 'DF' in p.parts])
    if not protocols:
        raise FileNotFoundError('CM protocols missing under '+str(root)+'. Supply --protocol for full official keys.')
    rows = []
    for source in protocols:
        for line in source.read_text().splitlines():
            if not line.strip():
                continue
            parts = line.split()
            if dataset == 'asv2019':
                if len(parts) != 5:
                    raise ValueError('Expected five ASVspoof2019 CM protocol fields')
                speaker, trial, _, generator, label = parts
                split = next((v for k,v in [('train','reference'),('dev','validation'),('eval','test')] if f'.{k}.' in source.name),None)
                codec, language = 'none', 'en'
                if split is None:
                    raise ValueError('2019 protocol filename must identify train/dev/eval')
            else:
                if len(parts) < 9:
                    raise ValueError('Use full ASVspoof2021 DF metadata (at least nine fields)')
                speaker,trial,codec,origin,generator,label,trim,subset = parts[:8]
                if subset != 'eval':
                    continue
                split, language = 'test', ('en' if origin == 'asvspoof' else 'und')
                if origin != 'asvspoof':
                    speaker = origin+':'+speaker
            if label not in LABELS or speaker in ('-','unknown','') or (label == 'spoof' and generator in ('-','unknown','')):
                raise ValueError('Incomplete speaker/label/generator provenance for '+trial)
            if trial not in audio:
                raise FileNotFoundError(f'Missing audio trial {trial}.flac under {root}')
            rows.append(dict(path=str(audio[trial]),label=LABELS[label],language=language,speaker_id=speaker,
                generator='bonafide' if label == 'bonafide' else generator,codec=codec,
                source_id=trial,split=split,license='ASVspoof-corpus-terms',
                dataset=dataset,attack_onset_s='0' if label == 'spoof' else ''))
    return rows


def speaker_split(speaker: str) -> str:
    """Assign all clips from a speaker deterministically to one split."""
    bucket = int(hashlib.sha256(('strive-split-v1:'+speaker).encode()).hexdigest()[:8],16)%100
    return 'reference' if bucket < 60 else ('validation' if bucket < 80 else 'test')


def common_voice_rows(root: Path, indian_only: bool, languages: set[str], accents: set[str]) -> list[dict]:
    """Use Common Voice metadata; accent labels are self-reports, not nationality."""
    tables = sorted(root.rglob('validated.tsv'))
    if not tables:
        raise FileNotFoundError('No validated.tsv found under '+str(root))
    rows = []
    for table in tables:
        with table.open(encoding='utf-8',newline='') as stream:
            for row in csv.DictReader(stream,delimiter='\t'):
                language = row.get('locale') or table.parent.name
                if languages and language not in languages:
                    continue
                accent = row.get('accents',row.get('accent','')).strip().lower()
                if indian_only and not any(a.strip() in accents for a in accent.split(',')):
                    continue
                speaker = row.get('client_id','').strip()
                if not speaker or not row.get('path'):
                    raise ValueError('Common Voice requires client_id and path')
                path = safe_target(table.parent/'clips',row['path'])
                if not path.is_file():
                    raise FileNotFoundError(str(path))
                rows.append(dict(path=str(path),label='0',language=language,speaker_id='cv:'+speaker,
                    generator='bonafide',codec='mp3',source_id='cv:'+language+':'+Path(row['path']).stem,
                    split=speaker_split(speaker),license='CC0-1.0',dataset='commonvoice',accents=accent))
    if not rows:
        raise ValueError('No matching Common Voice clips. Check locale/accent metadata filters.')
    return rows


def write_manifests(rows: list[dict], output: Path) -> dict:
    """Write available splits and verify file hashes plus speaker/source separation."""
    if not rows:
        raise ValueError('No dataset rows selected')
    output.mkdir(parents=True,exist_ok=True)
    fields = ['path','label','language','speaker_id','generator','codec','source_id','split','license']
    fields += sorted(set().union(*(r.keys() for r in rows))-set(fields))
    validated = {}
    for split in ('reference','validation','test'):
        selected = [r for r in rows if r['split'] == split]
        if not selected:
            continue
        target = output/(split+'.csv')
        with target.open('w',encoding='utf-8',newline='') as stream:
            writer = csv.DictWriter(stream,fieldnames=fields); writer.writeheader(); writer.writerows(selected)
        validated[split] = read_manifest(target)
    for left,right in combinations(validated,2):
        assert_disjoint(validated[left],validated[right])
    result = {'splits':{k:len(v) for k,v in validated.items()},'speaker_disjoint':True,
              'labels':sorted({r['label'] for r in rows}),
              'scope':'Corpus manifest, not proof of checkpoint-training exclusion. Common Voice is genuine-only.'}
    (output/'preparation.json').write_text(json.dumps(result,indent=2))
    return result


def main() -> None:
    """Download only when explicitly requested; local preparation also works offline."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('dataset',choices=['asv2019','asv2021','commonvoice'])
    p.add_argument('--root',required=True); p.add_argument('--output',default='data/manifests')
    p.add_argument('--download',action='store_true'); p.add_argument('--protocol',type=Path)
    p.add_argument('--archive',type=Path); p.add_argument('--url'); p.add_argument('--checksum')
    p.add_argument('--indian-only',action='store_true')
    p.add_argument('--languages',default='',help='Comma-separated Common Voice locales')
    p.add_argument('--accent-labels',default='indian',help='Exact self-reported accent labels for --indian-only; not nationality')
    args = p.parse_args(); root = Path(args.root).resolve()
    if args.indian_only and args.dataset != 'commonvoice':
        p.error('--indian-only requires Common Voice accent metadata')
    if args.dataset.startswith('asv'):
        if args.download:
            download_asv(args.dataset,root)
        if args.archive:
            extract_archive(args.archive,root)
        rows = asv_rows(root,args.dataset,args.protocol)
    else:
        archive = args.archive
        if args.download:
            if not args.url or not args.checksum:
                p.error('Common Voice: obtain an authorized download URL and published checksum; supply --url and --checksum')
            archive = download(args.url,root/'archives'/'commonvoice.tar.gz',args.checksum,os.getenv('COMMONVOICE_DOWNLOAD_TOKEN'))
        if archive:
            extract_archive(archive,root)
        rows = common_voice_rows(root,args.indian_only,set(filter(None,args.languages.split(','))),set(args.accent_labels.lower().split(',')))
    print(json.dumps(write_manifests(rows,Path(args.output)),indent=2))


if __name__ == '__main__':
    main()
