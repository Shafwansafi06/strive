import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from build_index import assert_disjoint
from evaluate import metrics


def test_leakage_check():
    ref = [{'sha256':'a','source_id':'one','speaker_id':'s1','generator':'g1'}]
    test = [{'sha256':'b','source_id':'two','speaker_id':'s2','generator':'g2'}]
    assert_disjoint(ref, test, 'g2')
    with pytest.raises(ValueError): assert_disjoint(ref, test, 'g1')
    with pytest.raises(ValueError): assert_disjoint(ref, [{**test[0], 'source_id':'one'}])


def test_metrics_handle_abstention_and_perfect_ranking():
    rows = [{'label':0,'score':.1},{'label':1,'score':.9},{'label':1,'score':None}]
    m = metrics(rows,'score')
    assert m['roc_auc'] == 1 and m['eer'] == 0 and m['abstained'] == 1
    assert metrics([{'label':0,'score':.1}], 'score')['eer'] is None
