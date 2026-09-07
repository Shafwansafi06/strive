"""Software regression tests; procedural inputs are never research evidence.

Checks NumPy/SciPy acoustics, persistent FAISS, missing assets, score replay and
safe dataset preparation without pretrained dependencies or downloaded speech.
"""
import csv
import io
import json
from pathlib import Path
import sys
import tarfile
import zipfile
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from download_data import asv_rows, common_voice_rows, extract_archive, speaker_split, write_manifests
from evaluate import parser, sweep_values
from strive.ablation import CONFIGURATIONS, ablate_events, markdown_table, summarize
from strive.config import Settings
from strive.engine import aggregate
from strive.features import DSPExtractor, Features, Segment, acoustic_profile, acoustic_profile_legacy, unit
from strive.models.research import ResearchExtractor, language_result, sha256
from strive.retrieval import SessionProfile


def test_profile_richer_and_legacy_direction_preserved() -> None:
    t = np.arange(32000)/16000
    x = (.2*np.sin(2*np.pi*160*t)*(1+.3*np.sin(2*np.pi*4*t))).astype(np.float32)
    old,_ = acoustic_profile_legacy(x)
    vector,meta = acoustic_profile(x)
    assert vector.shape == (62,) and meta['profile_kind'] == 'acoustic-62'
    np.testing.assert_allclose(np.linalg.norm(vector),1,atol=1e-6)
    np.testing.assert_allclose(unit(vector[:24]),old,atol=1e-6)
    np.testing.assert_array_equal(DSPExtractor().extract(x).profile,old)
    assert np.isfinite(acoustic_profile(np.zeros(32000,dtype=np.float32))[0]).all()
    with pytest.raises(ValueError):
        acoustic_profile(np.full(32000,np.nan))


def make_features(p: list[float], token: int = 1) -> Features:
    return Features(unit(np.array(p)),unit(np.array(p)),[Segment(0,1,unit(np.array(p)),token)],None,{})


def test_sps_queries_reuse_indexes_and_eviction_removes_old_points() -> None:
    sps = SessionProfile(capacity=2,k=1)
    a,b = make_features([1,0]),make_features([0,1])
    assert sps.similarity(a) is None
    sps.add(a); index = sps.profile_index
    sps.add(b)
    for _ in range(10):
        assert sps.similarity(a) == pytest.approx(1)
    assert sps.profile_index is index and sps.rebuild_count == 0
    sps.add(b)
    assert sps.rebuild_count == 1 and sps.profile_index.ntotal == 2
    assert sps.similarity(a) == pytest.approx(0)
    sps.clear(); assert sps.similarity(a) is None


def test_local_assets_and_language_mapping(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError,match='manifest.json'):
        ResearchExtractor(Settings(mode='research',model_dir=str(tmp_path)))
    (tmp_path/'manifest.json').write_text('{}')
    with pytest.raises(FileNotFoundError,match='cm.pt'):
        ResearchExtractor(Settings(mode='research',model_dir=str(tmp_path)))
    assert len(sha256(tmp_path/'manifest.json')) == 64
    assert ResearchExtractor.is_surrogate is False
    assert language_result('hi: Hindi',.8) == ('hi','model')
    assert language_result('Tamil',.8) == ('ta','model')
    assert language_result('English',.49) == ('und','model_low_confidence')
    assert language_result('fr: French',.99) == ('und','model_low_confidence')


def event(time: float, g: float | None, s: float | None, c: float | None, eligible: bool = True) -> dict:
    return {'session_age_s':time,'track_scores':dict(s_global=g,s_session=s,s_coherence=c),'evidence_eligible':eligible}


def test_ablation_full_matches_engine_and_all_use_ema() -> None:
    events = [event(t,.8,None if t<6 else .4,.7,t>=4) for t in range(2,25)]
    scores = ablate_events(events)
    previous = None; values = []
    for e in events:
        previous,_,_ = aggregate(list(e['track_scores'].values()),e['session_age_s'],previous)
        if e['evidence_eligible']:
            values.append(previous)
    assert scores['strive']['score'] == pytest.approx(np.mean(values))
    assert scores['global_only']['score'] < .8
    assert scores['global_only']['raw_mean'] == pytest.approx(.8)
    assert set(scores) == set(CONFIGURATIONS)
    assert ablate_events([event(2,.8,None,None)])['session_only']['score'] is None


def test_onset_delays_do_not_count_early_false_alarm_as_negative_delay() -> None:
    scores = ablate_events([event(t,1,1,1) for t in range(2,20)],attack_onset_s=10)
    assert scores['strive']['pre_onset_warning']
    assert scores['strive']['first_warning_s'] < 10
    assert scores['strive']['detection_delay_s'] == 0


def test_generator_metrics_get_real_controls_and_common_cohort() -> None:
    rows = []
    for label,gen,score in [(0,'bonafide',.1),(1,'A01',.9),(1,'A02',.8)]:
        rows.append(dict(label=label,generator=gen,language='en',codec='opus',**{k:score for k in CONFIGURATIONS}))
    rows[-1]['session_only'] = None
    report = summarize(rows)
    assert report['overall']['session_only']['abstained'] == 1
    assert report['common_cohort']['global_only']['total'] == 2
    assert report['by_generator']['A01']['available_cohort']['strive']['roc_auc'] == 1
    assert 'STRIVE (full)' in markdown_table(report['overall'])
    assert 'N/A' in markdown_table(summarize([])['overall'])


def test_sweep_parser_validates_each_value() -> None:
    args = parser().parse_args(['test.csv','--sweep-alpha','0.5,0.7','--sweep-k','5,20','--sweep-global-gate','0.1,0.3','--sweep-weights','equal,proposed'])
    assert sweep_values(args)['global_k'] == [5,20]
    args.sweep_alpha = '1.0'
    with pytest.raises(ValueError):
        sweep_values(args)


def test_asv_protocol_and_speaker_disjoint_manifest(tmp_path: Path) -> None:
    for split,speaker,trial in [('train','LA_1','LA_T_1'),('dev','LA_2','LA_D_1'),('eval','LA_3','LA_E_1')]:
        (tmp_path/(trial+'.flac')).write_bytes(trial.encode())
        (tmp_path/f'ASVspoof2019.LA.cm.{split}.trn.txt').write_text(f'{speaker} {trial} - A01 spoof\n')
    rows = asv_rows(tmp_path,'asv2019')
    result = write_manifests(rows,tmp_path/'manifests')
    assert result['splits'] == {'reference':1,'validation':1,'test':1}
    assert all(r['attack_onset_s'] == '0' for r in rows)
    rows[1]['speaker_id'] = rows[0]['speaker_id']
    with pytest.raises(ValueError,match='speaker_id'):
        write_manifests(rows,tmp_path/'leaky')


def test_full_df_protocol_and_cv_metadata(tmp_path: Path) -> None:
    (tmp_path/'DF_E_1.flac').write_bytes(b'unit-test-only')
    protocol = tmp_path/'full.txt'
    protocol.write_text('LA_0023 DF_E_1 nocodec asvspoof A14 spoof notrim eval traditional_vocoder - - - -\n')
    row = asv_rows(tmp_path,'asv2021',protocol)[0]
    assert (row['speaker_id'],row['generator'],row['split']) == ('LA_0023','A14','test')
    folder = tmp_path/'en'; (folder/'clips').mkdir(parents=True)
    (folder/'clips'/'a.mp3').write_bytes(b'a'); (folder/'clips'/'b.mp3').write_bytes(b'b')
    (folder/'validated.tsv').write_text('client_id\tpath\tlocale\taccents\na\ta.mp3\ten\tindian\nb\tb.mp3\ten\tcanadian\n')
    rows = common_voice_rows(tmp_path,True,{'en'},{'indian'})
    assert len(rows) == 1 and rows[0]['label'] == '0'
    assert speaker_split('a') == speaker_split('a')


def test_archive_traversal_and_links_are_rejected(tmp_path: Path) -> None:
    archive = tmp_path/'bad.zip'
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('../outside.txt','bad')
    with pytest.raises(ValueError):
        extract_archive(archive,tmp_path/'output')
    archive = tmp_path/'bad.tar'
    with tarfile.open(archive,'w') as t:
        link = tarfile.TarInfo('link'); link.type = tarfile.SYMTYPE; link.linkname = '/tmp'
        t.addfile(link)
    with pytest.raises(ValueError):
        extract_archive(archive,tmp_path/'output')


def test_release_preserves_source_models_and_excludes_weights(tmp_path: Path) -> None:
    from package_release import release_files
    for relative in ('strive/models/research.py','strive/models/__init__.py','models/cm.pt','models/manifest.json','data/private.wav'):
        path = tmp_path/relative; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(b'x')
    paths = {p.relative_to(tmp_path).as_posix() for p in release_files(tmp_path)}
    assert paths == {'strive/models/research.py','strive/models/__init__.py'}


def test_multipart_tar_reader_supports_split_and_independent_archives(tmp_path: Path) -> None:
    import gzip
    from download_data import PartReader, extract_tar
    archives = []
    for name in ('one','two'):
        data = io.BytesIO()
        with tarfile.open(fileobj=data,mode='w') as archive:
            info = tarfile.TarInfo(name); info.size = 3; archive.addfile(info,io.BytesIO(b'abc'))
        archives.append(gzip.compress(data.getvalue()))
    for mode,parts in [('split',[archives[0][:15],archives[0][15:]]),('independent',archives)]:
        paths = []
        for i,part in enumerate(parts):
            path = tmp_path/f'{mode}-{i}'; path.write_bytes(part); paths.append(path)
        target = tmp_path/mode; target.mkdir()
        with PartReader(paths) as raw, io.BufferedReader(raw) as buffer, gzip.GzipFile(fileobj=buffer) as data:
            with tarfile.open(fileobj=data,mode='r|',ignore_zeros=True) as archive:
                extract_tar(archive,target)
        assert (target/'one').read_bytes() == b'abc'
        if mode == 'independent':
            assert (target/'two').read_bytes() == b'abc'
