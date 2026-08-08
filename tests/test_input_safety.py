from __future__ import annotations

from pathlib import Path

import numpy as np

from conftest import make_dense_stereo, run_mastering, write_audio


def test_input_and_output_paths_must_be_different(tmp_path: Path) -> None:
    sample_rate = 44_100
    source = write_audio(
        tmp_path / "source.wav",
        make_dense_stereo(sample_rate=sample_rate, duration_seconds=1.0),
        sample_rate,
    )
    original_bytes = source.read_bytes()

    result = run_mastering(source, source)

    assert result.returncode != 0
    assert source.read_bytes() == original_bytes


def test_existing_output_is_not_overwritten(tmp_path: Path) -> None:
    sample_rate = 44_100
    input_path = write_audio(
        tmp_path / "input.wav",
        make_dense_stereo(sample_rate=sample_rate, duration_seconds=1.0),
        sample_rate,
    )
    output_path = tmp_path / "existing.wav"
    sentinel = b"DO-NOT-OVERWRITE"
    output_path.write_bytes(sentinel)

    result = run_mastering(input_path, output_path)

    assert result.returncode != 0
    assert output_path.read_bytes() == sentinel


def test_non_finite_input_is_rejected_without_output(tmp_path: Path) -> None:
    sample_rate = 44_100
    audio = make_dense_stereo(
        sample_rate=sample_rate,
        duration_seconds=1.0,
        amplitude=0.25,
    )
    audio[100, 0] = np.nan
    input_path = write_audio(tmp_path / "nan.wav", audio, sample_rate)
    output_path = tmp_path / "nan_master.wav"

    result = run_mastering(input_path, output_path)

    assert result.returncode != 0
    assert not output_path.exists()


def test_missing_output_directory_is_rejected(tmp_path: Path) -> None:
    sample_rate = 44_100
    input_path = write_audio(
        tmp_path / "input.wav",
        make_dense_stereo(sample_rate=sample_rate, duration_seconds=1.0),
        sample_rate,
    )
    output_path = tmp_path / "missing" / "output.wav"

    result = run_mastering(input_path, output_path)

    assert result.returncode != 0
    assert not output_path.exists()
