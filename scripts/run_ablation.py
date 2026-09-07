"""Run seven conditional score configurations and separate validation sweeps.

Uses evaluate.py, local frozen model bundles, FAISS and labelled speech. Optional
comparison bundles measure actual neural latency; no timings are extrapolated.
"""
import argparse
import json
from pathlib import Path
import sys
from time import perf_counter
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from evaluate import evaluate, parser as evaluation_parser
from strive.ablation import markdown_table
from strive.audio import decode
from strive.features import DSPExtractor
from build_index import read_manifest


def parser() -> argparse.ArgumentParser:
    """Build the one-command study interface."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', required=True)
    p.add_argument('--models', default='models'); p.add_argument('--index', default='data/reference.npz')
    p.add_argument('--output', default='evidence/ablation'); p.add_argument('--device', default='cpu')
    p.add_argument('--profile', choices=['acoustic','vox'], default='acoustic')
    p.add_argument('--sweep-manifest', help='Separate speaker-disjoint validation CSV; enables default sweeps')
    p.add_argument('--sweep-alpha', default='0.5,0.6,0.7,0.8,0.9')
    p.add_argument('--sweep-k', default='5,10,15,20,25')
    p.add_argument('--sweep-global-gate', default='0.1,0.2,0.3,0.4,0.5')
    p.add_argument('--sweep-weights', default='equal,proposed,global_heavy,session_heavy')
    p.add_argument('--holdout-generator')
    p.add_argument('--language-routing', choices=['model','manifest'], default='model')
    p.add_argument('--skip-language-model', action='store_true')
    p.add_argument('--compare', nargs=3, action='append', metavar=('NAME','MODELS','INDEX'), default=[],
                   help='Additional real bundle/index, e.g. xls-r-2b models-2b data/reference-2b.npz')
    return p


def render_report(report: dict) -> str:
    """Generate tables with explicit coverage, missing results and real controls."""
    sections = ['# STRIVE measured ablation study', '', report['method'],
        'Primary scores use identical EMA; raw scores are retained in JSON. These are fusion ablations: Track 1 still gates SPS admission.',
        'Compare the common cohort and coverage together. A method abstaining on difficult clips has not necessarily improved.', '',
        markdown_table(report['overall'], '## Available cohort'), '',
        markdown_table(report['common_cohort'], '## Common scored cohort')]
    for group in ('by_language','by_codec','by_generator'):
        for name, result in report[group].items():
            sections += ['', markdown_table(result['available_cohort'], f'## {group}: {name}'), '',
                         markdown_table(result['common_cohort'], '### Common cohort')]
    for parameter, cases in report.get('sweeps', {}).items():
        for value, result in cases.items():
            sections += ['', markdown_table(result['overall'], f'## Validation sweep: {parameter}={value}')]
    sections += ['', '## Latency on this machine', '',
        'Feature timings are wall time per two-second window, including transfer and first inference. All seven score masks share the same extracted features.', '',
        '| Configuration | Feature p50 (ms) | Feature p95 (ms) | Windows |', '|---|---:|---:|---:|']
    for name, value in report['latency_comparison'].items():
        if value is None:
            sections.append(f'| {name} | N/A | N/A | Not run |')
        else:
            sections.append(f"| {name} | {value['p50']:.2f} | {value['p95']:.2f} | {value['windows']} |")
    sections += ['', report.get('sweeps_status', ''), '',
        'No winner is assumed. These EERs describe the supplied split and checkpoint; reference separation does not establish absence from checkpoint training.',
        'TPR at 1% FPR is poorly resolved with fewer than 100 scored genuine clips. Alert-time averages include detected attacks; JSON also records misses and onset delays.']
    return '\n'.join(sections) + '\n'


def main() -> None:
    """Persist checkpoints and tables after each completed real model evaluation."""
    args = parser().parse_args()
    output = Path(args.output); output.mkdir(parents=True, exist_ok=True)
    base = evaluation_parser().parse_args([args.manifest])
    for key in ('models','index','device','profile','holdout_generator','language_routing','skip_language_model'):
        setattr(base, key, getattr(args, key))
    base.output = str(output / 'ablation_report.json')
    base.sweep_manifest = args.sweep_manifest
    if args.sweep_manifest:
        for key in ('sweep_alpha','sweep_k','sweep_global_gate','sweep_weights'):
            setattr(base, key, getattr(args,key))
    report = evaluate(base)
    report['sweeps_status'] = ('Sweeps measured on a separate validation split.' if args.sweep_manifest else
                             'Sweeps were not run: supply --sweep-manifest with separate validation data.')
    report['latency_comparison'] = {'DSP (feature-only surrogate)':None, 'MMS-300M':None, 'XLS-R-2B':None}
    model_manifest = json.loads((Path(args.models)/'manifest.json').read_text())
    model_name = 'MMS-300M' if model_manifest['cm_dimension'] == 1024 else 'XLS-R-2B'
    report['latency_comparison'][model_name] = report['feature_latency_ms']
    # Measure DSP on up to 100 actual corpus windows, not procedural signals.
    elapsed = []
    for row in read_manifest(args.manifest):
        audio = decode(Path(row['absolute_path']).read_bytes())
        try:
            for start in range(0,len(audio)-32000+1,16000):
                then = perf_counter(); DSPExtractor().extract(audio[start:start+32000])
                elapsed.append((perf_counter()-then)*1000)
                if len(elapsed) >= 100:
                    break
        finally:
            audio.fill(0)
        if len(elapsed) >= 100:
            break
    if elapsed:
        report['latency_comparison']['DSP (feature-only surrogate)'] = {
            'p50':float(np.percentile(elapsed,50)), 'p95':float(np.percentile(elapsed,95)), 'windows':len(elapsed)}
    report['comparisons'] = {}
    for name, models, index in args.compare:
        comparison = evaluation_parser().parse_args([args.manifest,'--models',models,'--index',index,'--device',args.device])
        comparison.language_routing = args.language_routing
        comparison.skip_language_model = args.skip_language_model
        comparison.profile = args.profile
        comparison.holdout_generator = args.holdout_generator
        comparison.output = str(output / f'comparison-{len(report["comparisons"])}.json')
        result = evaluate(comparison)
        report['comparisons'][name] = result
        report['latency_comparison'][name] = result['feature_latency_ms']
    Path(base.output).write_text(json.dumps(report,indent=2,allow_nan=False))
    (output/'ablation_table.md').write_text(render_report(report),encoding='utf-8')
    print(markdown_table(report['overall']))


if __name__ == '__main__':
    main()
