"""Build and verify a GitHub-ready source ZIP using only standard-library tools.

Excludes root model weights, datasets and caches while retaining strive/models.
Verification imports and tests the extracted artifact, never the working tree.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {'README.md','STRIVE_Demo.html','THIRD_PARTY_NOTICES.md','pyproject.toml',
              'requirements.txt','requirements-demo.lock','requirements-research.txt',
              'Dockerfile','compose.yaml','.gitignore','.dockerignore'}
FOLDERS = {'strive','scripts','tests','web','docs','config','.github','evidence'}


def release_files(root: Path) -> list[Path]:
    """Select owned source and evidence; source modules named models are retained."""
    result = []
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        if not path.is_file() or path.is_symlink() or any(p in ('__pycache__','.pytest_cache','.git','.venv') for p in relative.parts):
            continue
        if path.suffix in ('.pyc','.zip','.wav','.flac','.mp3','.pt','.bin','.safetensors','.npz'):
            continue
        data_examples = {'data/manifest.example.csv', 'data/demo/README.md',
                         'data/demo/manifest.example.csv'}
        if relative.parts[0] in FOLDERS or relative.as_posix() in ROOT_FILES or relative.as_posix() in data_examples:
            result.append(path)
    return result


def build(root: Path, output: Path) -> dict:
    """Write SHA256SUMS for every bundled file, then build the archive."""
    files = release_files(root)
    paths = {p.relative_to(root).as_posix() for p in files}
    for required in ('strive/models/__init__.py','strive/models/research.py','scripts/run_ablation.py','scripts/download_data.py'):
        if required not in paths:
            raise ValueError('Required release source is missing: '+required)
    hashes = {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    checksum_file = root/'SHA256SUMS.json'
    checksum_file.write_text(json.dumps(hashes,indent=2,sort_keys=True)+'\n')
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in files+[checksum_file]:
            archive.write(path,'strive-mvp/'+path.relative_to(root).as_posix())
    return {'archive':str(output.resolve()),'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'files':len(files)+1}


def verify(output: Path) -> dict:
    """Validate exact membership/hashes, CLI imports and tests in a fresh folder."""
    with tempfile.TemporaryDirectory(prefix='strive-release-') as temporary:
        with zipfile.ZipFile(output) as archive:
            archive.extractall(temporary)
        root = Path(temporary)/'strive-mvp'
        hashes = json.loads((root/'SHA256SUMS.json').read_text())
        members = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
        assert members == set(hashes)|{'SHA256SUMS.json'}, 'Archive has missing or unhashed files'
        for relative,expected in hashes.items():
            assert hashlib.sha256((root/relative).read_bytes()).hexdigest() == expected, relative
        env = os.environ.copy(); env['PYTHONPATH'] = str(root)
        commands = [[sys.executable,'-c',
            'from pathlib import Path; import strive.models.research as r; assert Path(r.__file__).resolve().is_relative_to(Path.cwd()); print(r.__file__)']]
        commands += [[sys.executable,'scripts/'+name,'--help'] for name in
                     ('export_nii.py','evaluate.py','run_ablation.py','download_data.py','start.py')]
        commands += [[sys.executable,'-m','pytest','-q']]
        checks = []
        for command in commands:
            result = subprocess.run(command,cwd=root,env=env,capture_output=True,text=True,timeout=120)
            checks.append({'command':command[1:],'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
            if result.returncode:
                raise RuntimeError(f'Extracted release failed {command}:\n{result.stdout}\n{result.stderr}')
        return {'exact_membership_and_hashes':True,'extracted_checks':checks}


def main() -> None:
    """Create an archive and optional separate verification receipt."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',default='../deliverables/STRIVE_MVP.zip')
    p.add_argument('--verify',action='store_true')
    args = p.parse_args(); output = Path(args.output).resolve()
    result = build(ROOT,output)
    if args.verify:
        result.update(verify(output))
        output.with_suffix('.verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k != 'extracted_checks'},indent=2))


if __name__ == '__main__':
    main()
