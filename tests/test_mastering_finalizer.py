from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from conftest import write_audio
from src.controllers.mastering_finalizer import (
    FinalizerError,
    finalize_true_peak,
)
from src.controllers.mastering_metrics import measure_audio_file


REPO_ROOT = Path(__file__).resolve().parents[1]
FINALIZER_MODULE = REPO_ROOT / "src" / "controllers" / "mastering_finalizer.py"


def _high_frequency_stereo(
    *,
    sample_rate: int = 44_100,
    duration_seconds: float = 3.0,
) -> np.ndarray:
    frame_count = int(sample_rate * duration_seconds)
    t = np.arange(frame_count, dtype=np.float64) / sample_rate
    signal = (
        0.95 * np.sin(2.0 * np.pi * 997.0 * t)
        + 0.65 * np.sin(2.0 * np.pi * 13_001.0 * t + 0.2)
        + 0.35 * np.sin(2.0 * np.pi * 17_003.0 * t + 0.7)
    )
    signal = signal / np.max(np.abs(signal)) * 0.99
    return np.column_stack((signal, signal)).astype(np.float32)


def test_finalizer_meets_true_peak_and_preserves_stream(tmp_path: Path) -> None:
    sample_rate = 44_100
    source = write_audio(
        tmp_path / "source.wav",
        _high_frequency_stereo(sample_rate=sample_rate),
        sample_rate,
    )
    target = tmp_path / "final.wav"
    source_info = sf.info(source)

    before = measure_audio_file(source)
    assert before.true_peak_dbtp > -1.0

    result = finalize_true_peak(
        source,
        target,
        ceiling_dbtp=-1.0,
        release_ms=120.0,
    )

    after = measure_audio_file(target)
    target_info = sf.info(target)

    assert result.measured_true_peak_dbtp <= -0.95
    assert after.true_peak_dbtp <= -0.95
    assert target_info.samplerate == source_info.samplerate
    assert target_info.channels == source_info.channels
    assert abs(target_info.frames - source_info.frames) <= 1
    assert target_info.subtype == "PCM_24"
    assert 1 <= result.passes <= 4


def test_finalizer_does_not_modify_source(tmp_path: Path) -> None:
    sample_rate = 48_000
    source = write_audio(
        tmp_path / "immutable.wav",
        _high_frequency_stereo(sample_rate=sample_rate),
        sample_rate,
    )
    target = tmp_path / "immutable_final.wav"
    before = source.read_bytes()

    finalize_true_peak(
        source,
        target,
        ceiling_dbtp=-1.0,
        release_ms=120.0,
    )

    assert source.read_bytes() == before


def test_finalizer_rejects_existing_output(tmp_path: Path) -> None:
    sample_rate = 44_100
    source = write_audio(
        tmp_path / "source.wav",
        _high_frequency_stereo(sample_rate=sample_rate),
        sample_rate,
    )
    target = tmp_path / "existing.wav"
    sentinel = b"DO-NOT-OVERWRITE"
    target.write_bytes(sentinel)

    with pytest.raises(FinalizerError, match="already exists"):
        finalize_true_peak(
            source,
            target,
            ceiling_dbtp=-1.0,
            release_ms=120.0,
        )

    assert target.read_bytes() == sentinel


def test_finalizer_rejects_invalid_ceiling(tmp_path: Path) -> None:
    sample_rate = 44_100
    source = write_audio(
        tmp_path / "source.wav",
        _high_frequency_stereo(sample_rate=sample_rate),
        sample_rate,
    )

    with pytest.raises(FinalizerError, match="ceiling"):
        finalize_true_peak(
            source,
            tmp_path / "bad.wav",
            ceiling_dbtp=0.5,
            release_ms=120.0,
        )


def test_finalizer_module_does_not_import_core_dsp() -> None:
    module = ast.parse(FINALIZER_MODULE.read_text(encoding="utf-8"))

    imported_names: list[str] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            imported_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.append(node.module)

    assert not any("core_dsp" in name for name in imported_names)


def test_finalizer_filter_disables_ffmpeg_auto_level() -> None:
    source = FINALIZER_MODULE.read_text(encoding="utf-8")

    assert "level=false" in source
    assert "latency=true" in source
    assert "aresample=" in source
