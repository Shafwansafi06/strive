"""Research evaluation with seven conditional score ablations and full state sweeps.

Requires labelled local speech, a non-fixture reference index and frozen models.
No experiment is replaced by procedural data. Each gate/k sweep reruns all calls.
"""
import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
from importlib.metadata import version, PackageNotFoundError
import sys
from typing import Any
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from strive.ablation import CONFIGURATIONS, ablate_events, markdown_table, metrics, summarize
from strive.audio import RATE, decode
from strive.config import Settings
from strive.engine import Call
from strive.models.research import ResearchExtractor, sha256
from strive.retrieval import ReferenceIndex
from build_index import read_manifest, assert_disjoint


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("manifest"); p.add_argument("--models", default="models")
    p.add_argument("--index", default="data/reference.npz"); p.add_argument("--device", default="cpu")
    p.add_argument("--output", default="evidence/research-evaluation.json")
    p.add_argument("--profile", choices=["acoustic", "vox"], default="acoustic")
    p.add_argument("--holdout-generator"); p.add_argument("--ablation-table", action="store_true")
    p.add_argument("--track-config", choices=list(CONFIGURATIONS), default="strive")
    p.add_argument("--sweep-alpha"); p.add_argument("--sweep-k"); p.add_argument("--sweep-global-gate")
    p.add_argument("--sweep-weights"); p.add_argument("--sweep-manifest", help="Separate validation split for parameter sweeps")
    p.add_argument("--language-routing", choices=["model", "manifest"], default="model")
    p.add_argument("--skip-language-model", action="store_true", help="Explicit manifest-hint experiment; requires --language-routing manifest")
    p.add_argument("--alpha", type=float, default=.7); p.add_argument("--k", type=int, default=20)
    p.add_argument("--global-gate", type=float, default=.3)
    p.add_argument("--weights", choices=["equal", "proposed", "global_heavy", "session_heavy"], default="proposed")
    return p


def run_dataset(rows: list[dict], cfg: Settings, extractor: Any, index: ReferenceIndex,
                routing: str = "model") -> dict:
    """Rerun inference and per-call trust history with one exact configuration."""
    records, all_latency, feature_latency = [], [], []
    for n, row in enumerate(rows):
        print(f"Scoring {n + 1}/{len(rows)} ({row['source_id']})", file=sys.stderr, flush=True)
        call = Call(cfg, extractor, index, row["language"] if routing == "manifest" else "auto")
        audio = None
        try:
            audio = decode(Path(row["absolute_path"]).read_bytes(), max_s=cfg.max_call_s)
            onset = float(row["attack_onset_s"]) if row.get("attack_onset_s") not in (None, "") else None
            if onset is not None and not 0 <= onset < len(audio) / RATE:
                raise ValueError("attack_onset_s must lie within the audio")
            events = []
            for sequence, start in enumerate(range(0, len(audio), RATE)):
                events.extend(call.feed(audio[start:start + RATE], sequence))
            if any("MODEL_OR_INDEX_ERROR" in e["reasons"] or e["demo_only"] for e in events):
                raise RuntimeError("Research run contains surrogate features or model errors")
            scores = ablate_events(events, cfg.alpha, cfg.weight_preset, onset)
            record = {k: row[k] for k in ("source_id", "speaker_id", "language", "codec", "generator", "sha256")}
            record.update(label=int(row["label"]), attack_onset_s=onset, duration_s=len(audio)/RATE,
                timing={key: {k:v for k,v in score.items() if k not in ("score", "raw_mean")} for key,score in scores.items()},
                raw_scores={key: score["raw_mean"] for key,score in scores.items()},
                **{key: score["score"] for key,score in scores.items()})
            record.update({k: scores['strive'][k] if int(row['label']) == 1 else None
                           for k in ('first_warning_s','first_alert_s','detection_delay_s')})
            record["bootstrap"] = call.bootstrap
            record["language_route"] = call.language
            records.append(record)
            all_latency.extend(e["latency_ms"]["end_to_end"] for e in events)
            feature_latency.extend(e["stage_ms"]["artifact"] for e in events if e["stage_ms"].get("artifact", 0) > 0)
        finally:
            call.close()
            if audio is not None:
                audio.fill(0)
    def timing(values: list[float]) -> dict | None:
        return {"p50":float(np.percentile(values,50)), "p95":float(np.percentile(values,95)),
                "max":float(max(values)), "windows":len(values)} if values else None
    return {**summarize(records), "clips":records, "latency_ms":timing(all_latency),
            "feature_latency_ms":timing(feature_latency), "measurement":"Full pipeline including first-window cold inference; excludes disk decode"}


def sweep_values(args: argparse.Namespace) -> dict[str, list]:
    """Parse one-factor sweeps and validate values before loading any weights."""
    result = {}
    for field, option, cast in (("alpha", "sweep_alpha", float), ("global_k", "sweep_k", int),
                                ("global_gate", "sweep_global_gate", float), ("weight_preset", "sweep_weights", str)):
        value = getattr(args, option, None)
        if value:
            values = list(dict.fromkeys(cast(v.strip()) for v in value.split(",")))
            for v in values:
                replace(Settings(), **{field:v})
            result[field] = values
    return result


def evaluate(args: argparse.Namespace) -> dict:
    """Execute and persist actual experiments; never select a winner on the test set."""
    sweeps = sweep_values(args)
    if args.skip_language_model and args.language_routing != "manifest":
        raise ValueError("--skip-language-model requires explicit manifest routing")
    if sweeps and not args.sweep_manifest:
        raise ValueError("Parameter sweeps require --sweep-manifest with a separate validation split")
    index = ReferenceIndex.load(args.index)
    if index.metadata.get("demo_only", True):
        raise ValueError("Research evaluation refuses engineering-fixture indexes")
    rows = read_manifest(args.manifest)
    if any(r["split"] != "test" for r in rows):
        raise ValueError("Main evaluation manifest must use split=test")
    assert_disjoint(index.metadata["source_rows"], rows, args.holdout_generator)
    if args.holdout_generator:
        rows = [r for r in rows if r["label"] == "0" or r["generator"] == args.holdout_generator]
        if not any(r['label'] == '1' for r in rows):
            raise ValueError("No examples of requested held-out generator in test manifest")
    validation = read_manifest(args.sweep_manifest) if sweeps else []
    if validation:
        if any(r["split"] != "validation" for r in validation):
            raise ValueError("Sweep manifest must use split=validation")
        assert_disjoint(index.metadata['source_rows'], validation)
        assert_disjoint(validation, rows)
        if args.holdout_generator and any(r['generator'] == args.holdout_generator for r in validation):
            raise ValueError("Held-out generator is present in the validation sweep corpus")
    cfg = Settings(mode="research", model_dir=args.models, device=args.device, profile_backend=args.profile,
        alpha=args.alpha, global_k=args.k, global_gate=args.global_gate, weight_preset=args.weights,
        require_language_model=not args.skip_language_model, raise_model_errors=True)
    os.environ['HF_HUB_OFFLINE'] = '1'; os.environ['TRANSFORMERS_OFFLINE'] = '1'
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    extractor = ResearchExtractor(cfg)
    try:
        if extractor.id != index.metadata["extractor_id"]:
            raise ValueError("CM model hash differs from reference index; rebuild the index")
        report = {"created_utc":datetime.now(timezone.utc).isoformat(), "model_version":extractor.id,
            "pipeline_version":extractor.pipeline_version, "index_sha256":sha256(args.index),
            "manifest_sha256":sha256(args.manifest), "settings":{k:v for k,v in asdict(cfg).items() if k != 'api_token'},
            "hardware":{"platform":platform.platform(),"device":cfg.device},
            "language_routing":args.language_routing, "calibrated":False,
            "method":"Conditional score ablation: SPS always uses global trust gating; all primary configurations use identical EMA",
            "pretraining_overlap":"Reference/test disjointness is checked locally; absence from NII training is not established",
            "holdout_generator":args.holdout_generator, "selected_configuration":args.track_config,
            **run_dataset(rows,cfg,extractor,index,args.language_routing)}
        report['dependencies'] = {}
        for package in ('torch','torchaudio','transformers','speechbrain','numpy','scipy','faiss-cpu','scikit-learn','webrtcvad-wheels'):
            try:
                report['dependencies'][package] = version(package)
            except PackageNotFoundError:
                report['dependencies'][package] = None
        if cfg.device.startswith('cuda'):
            report['hardware']['gpu'] = extractor.torch.cuda.get_device_name(cfg.device)
        # Save the completed main run before starting potentially lengthy sweeps.
        output.write_text(json.dumps(report,indent=2,allow_nan=False))
        report['sweeps'] = {}
        for parameter, values in sweeps.items():
            report['sweeps'][parameter] = {}
            for value in values:
                case_cfg = replace(cfg, **{parameter:value})
                result = run_dataset(validation,case_cfg,extractor,index,args.language_routing)
                report['sweeps'][parameter][str(value)] = {"split":"validation", "value":value, **result}
                output.write_text(json.dumps(report,indent=2,allow_nan=False))
        if sweeps:
            report['sweep_manifest_sha256'] = sha256(args.sweep_manifest)
            report['sweep_design'] = 'One parameter at a time; fresh inference and SPS state; no test-set winner selection'
        output.write_text(json.dumps(report,indent=2,allow_nan=False))
        return report
    finally:
        extractor.close()


def main() -> None:
    args = parser().parse_args()
    try:
        report = evaluate(args)
    except (ValueError, FileNotFoundError) as exc:
        raise SystemExit(str(exc)) from exc
    if args.ablation_table:
        print(markdown_table(report['overall']))
    else:
        print(json.dumps(report['overall'],indent=2))


if __name__ == '__main__':
    main()
