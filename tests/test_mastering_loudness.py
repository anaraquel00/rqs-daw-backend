from __future__ import annotations
import ast, hashlib, math
from pathlib import Path
import numpy as np
import pytest
import soundfile as sf
from src.controllers.mastering_loudness import LoudnessFinalizerError, finalize_loudness
from src.controllers.mastering_metrics import measure_audio_file

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE = REPO_ROOT / "src" / "controllers" / "mastering_loudness.py"

def write_audio(path,audio,sr):
    sf.write(path,audio,sr,format='WAV',subtype='FLOAT');return path

def sparse(sr=44100,dur=8):
    n=sr*dur;t=np.arange(n,dtype=np.float64)/sr
    mono=(0.03*np.sin(2*np.pi*440*t)).astype(np.float32);mono[::sr//4]=0.99
    return np.column_stack((mono,mono))

def dense(sr=48000,dur=5,amp=.8):
    n=sr*dur;t=np.arange(n,dtype=np.float64)/sr
    mono=(amp*np.sin(2*np.pi*1000*t)).astype(np.float32)
    return np.column_stack((mono,mono))

def test_hits_target_and_true_peak(tmp_path):
    src=write_audio(tmp_path/'source.wav',sparse(),44100);out=tmp_path/'master.wav'
    result=finalize_loudness(src,out,target_lufs=-10.5,ceiling_dbtp=-1.0,release_ms=120)
    m=measure_audio_file(out)
    assert abs(m.integrated_lufs-(-10.5))<=.2
    assert m.true_peak_dbtp<=-.95
    assert result.measured_lufs==pytest.approx(m.integrated_lufs,abs=.01)
    assert result.measured_true_peak_dbtp==pytest.approx(m.true_peak_dbtp,abs=.01)

def test_preserves_stream_and_pcm24(tmp_path):
    sr=48000;src=write_audio(tmp_path/'source.wav',dense(sr,5,.2),sr);out=tmp_path/'master.wav'
    before=sf.info(src); result=finalize_loudness(src,out,target_lufs=-14,ceiling_dbtp=-1,release_ms=120)
    after=sf.info(out)
    assert after.samplerate==before.samplerate
    assert after.channels==before.channels
    assert abs(after.frames-before.frames)<=1
    assert after.subtype=='PCM_24'
    assert result.sample_rate==sr and result.channels==2

def test_does_not_modify_source(tmp_path):
    src=write_audio(tmp_path/'source.wav',sparse(),44100);before=src.read_bytes();out=tmp_path/'master.wav'
    finalize_loudness(src,out,target_lufs=-10.5,ceiling_dbtp=-1,release_ms=120)
    assert src.read_bytes()==before
    assert hashlib.sha256(src.read_bytes()).hexdigest()==hashlib.sha256(before).hexdigest()

def test_rejects_existing_output(tmp_path):
    src=write_audio(tmp_path/'source.wav',dense(48000,5,.2),48000);out=tmp_path/'master.wav'; sentinel=b'KEEP';out.write_bytes(sentinel)
    with pytest.raises(LoudnessFinalizerError,match='already exists'):
        finalize_loudness(src,out,target_lufs=-14,ceiling_dbtp=-1,release_ms=120)
    assert out.read_bytes()==sentinel

def test_rejects_invalid_target(tmp_path):
    src=write_audio(tmp_path/'source.wav',dense(48000,5,.2),48000)
    with pytest.raises(LoudnessFinalizerError,match='Target LUFS'):
        finalize_loudness(src,tmp_path/'out.wav',target_lufs=-3,ceiling_dbtp=-1,release_ms=120)

def test_module_does_not_import_core_dsp():
    module=ast.parse(MODULE.read_text(encoding='utf-8'))
    names=[]
    for node in ast.walk(module):
        if isinstance(node,ast.Import): names.extend(a.name for a in node.names)
        elif isinstance(node,ast.ImportFrom) and node.module: names.append(node.module)
    assert not any('core_dsp' in n for n in names)

def test_can_correct_downward_without_hitting_ceiling(tmp_path):
    src=write_audio(tmp_path/'source.wav',dense(48000,5,.8),48000);out=tmp_path/'master.wav'
    result=finalize_loudness(src,out,target_lufs=-14,ceiling_dbtp=-1,release_ms=120)
    m=measure_audio_file(out)
    assert abs(m.integrated_lufs+14)<=.2
    assert m.true_peak_dbtp<=-.95
    assert result.total_gain_db<0
