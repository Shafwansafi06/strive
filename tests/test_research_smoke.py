"""Opt-in real-model acceptance test using PyTorch, WebRTC VAD and real speech.

Set STRIVE_RESEARCH_MODELS, STRIVE_RESEARCH_INDEX and STRIVE_RESEARCH_AUDIO.
Audio must be genuine speech with enough trusted bootstrap activity (20+ seconds
recommended). No synthetic recording or fabricated embeddings are substituted.
"""
import json
import os
from pathlib import Path
import numpy as np
import pytest
from strive.audio import decode
from strive.config import Settings
from strive.engine import Call
from strive.models.research import ResearchExtractor
from strive.retrieval import ReferenceIndex

MODELS = Path(os.getenv('STRIVE_RESEARCH_MODELS','models'))


@pytest.mark.skipif(not (MODELS/'cm.pt').is_file(), reason='Local NII weights absent; real research acceptance was not run')
def test_real_research_pipeline_and_stride_budget() -> None:
    """Fail on missing dependencies/data, untrusted bootstrap or slow hardware."""
    audio_path = Path(os.getenv('STRIVE_RESEARCH_AUDIO','data/research-smoke.wav'))
    index_path = Path(os.getenv('STRIVE_RESEARCH_INDEX','data/reference.npz'))
    assert audio_path.is_file(), f'Supply genuine continuous speech through STRIVE_RESEARCH_AUDIO: {audio_path}'
    assert index_path.is_file(), f'Supply a real reference index: {index_path}'
    cfg = Settings(mode='research',model_dir=str(MODELS),device=os.getenv('STRIVE_DEVICE','cpu'),raise_model_errors=True)
    extractor = ResearchExtractor(cfg)
    call = None
    try:
        index = ReferenceIndex.load(index_path)
        assert index.metadata.get('demo_only') is False
        assert index.metadata['extractor_id'] == extractor.id
        audio = decode(audio_path.read_bytes())
        assert len(audio) >= 20*16000, 'Use at least 20 seconds of actual continuous speech'
        features = extractor.extract(audio[:32000])
        assert features.cm.shape in ((1024,),(1920,))
        assert features.profile.shape == (62,)
        assert features.segments, 'CTC returned no speech tokens'
        assert index.query(features.cm,'und')[0] is not None
        call = Call(cfg,extractor,index)
        events = []
        for sequence,start in enumerate(range(0,len(audio),16000)):
            events.extend(call.feed(audio[start:start+16000],sequence))
        assert any(e['s_risk'] is not None for e in events)
        assert any(all(v is not None for v in e['track_scores'].values()) for e in events), 'No eligible all-track window; inspect VAD, SPS bootstrap and reference domain'
        assert all(e['demo_only'] is False for e in events)
        assert call.language_source in ('model','model_low_confidence')
        budget = float(os.getenv('STRIVE_STRIDE_BUDGET_MS','1000'))
        latency = [e['latency_ms'] for e in events]
        assert max(latency) <= budget, f'Max {max(latency):.1f}ms exceeds {budget}ms on {cfg.device}; target hardware acceptance failed'
    finally:
        if call is not None:
            call.close()
        extractor.close()
        if 'audio' in locals():
            audio.fill(0)
