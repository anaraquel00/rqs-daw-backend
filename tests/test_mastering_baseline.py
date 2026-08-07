from __future__ import annotations

import ast
import math
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from conftest import (
    CORE_DSP,
    ffmpeg_loudness_metrics,
    make_dense_stereo,
    read_audio_metrics,
    run_mastering,
    write_audio,
)


def _diagnostic_message(result) -> str:
    return (
        f"returncode={result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def test_smoke_stereo_44100_creates_readable_wav(
    tmp_path: Path,
    dense_stereo_44100: tuple[np.ndarray, int],
) -> None:
    audio, sample_rate = dense_stereo_44100
    input_path = write_audio(tmp_path / "input.wav", audio, sample_rate)
    output_path = tmp_path / "output.wav"

    result = run_mastering(input_path, output_path)

    assert result.returncode == 0, _diagnostic_message(result)
    assert output_path.exists()
    metrics = read_audio_metrics(output_path)
    assert metrics["finite"]
    assert metrics["sample_rate"] == sample_rate
    assert metrics["channels"] == 2
    assert metrics["frames"] > 0


def test_short_file_is_rejected_without_output(tmp_path: Path) -> None:
    sample_rate = 44_100
    audio = np.zeros((int(sample_rate * 0.1), 2), dtype=np.float32)
    input_path = write_audio(tmp_path / "short.wav", audio, sample_rate)
    output_path = tmp_path / "short_master.wav"

    result = run_mastering(input_path, output_path)

    assert result.returncode != 0
    assert not output_path.exists()


def test_silence_is_rejected_without_output(tmp_path: Path) -> None:
    sample_rate = 44_100
    audio = np.zeros((sample_rate * 3, 2), dtype=np.float32)
    input_path = write_audio(tmp_path / "silence.wav", audio, sample_rate)
    output_path = tmp_path / "silence_master.wav"

    result = run_mastering(input_path, output_path)

    assert result.returncode != 0
    assert not output_path.exists()
    assert "silent" in f"{result.stdout}\n{result.stderr}".lower()


def test_media_profile_respects_minus_1_dbtp_ceiling(
    tmp_path: Path,
    dense_stereo_44100: tuple[np.ndarray, int],
) -> None:
    audio, sample_rate = dense_stereo_44100
    input_path = write_audio(tmp_path / "tp_input.wav", audio, sample_rate)
    output_path = tmp_path / "tp_output.wav"

    result = run_mastering(input_path, output_path, intensity="media")

    assert result.returncode == 0, _diagnostic_message(result)
    sample_metrics = read_audio_metrics(output_path)
    loudness = ffmpeg_loudness_metrics(output_path)

    linear_minus_1_db = 10.0 ** (-1.0 / 20.0)
    assert sample_metrics["sample_peak"] <= linear_minus_1_db + 1e-6
    assert loudness["true_peak_dbtp"] <= -0.95


def test_media_profile_reaches_target_lufs_within_point_2_lu(
    tmp_path: Path,
) -> None:
    target_lufs = -10.5
    sample_rate = 44_100
    duration_seconds = 8
    frame_count = sample_rate * duration_seconds
    t = np.arange(frame_count, dtype=np.float64) / sample_rate

    # Stress one-shot loudness correction with sparse high peaks. A verified
    # True Peak limiter can reduce level here, so the engine must re-measure
    # and correct loudness iteratively in a later stage.
    mono = (0.03 * np.sin(2.0 * np.pi * 440.0 * t)).astype(np.float32)
    mono[:: sample_rate // 4] = 0.99
    audio = np.column_stack((mono, mono))

    input_path = write_audio(tmp_path / "lufs_input.wav", audio, sample_rate)
    output_path = tmp_path / "lufs_output.wav"

    result = run_mastering(input_path, output_path, intensity="media")

    assert result.returncode == 0, _diagnostic_message(result)
    measured = ffmpeg_loudness_metrics(output_path)
    assert math.isfinite(measured["integrated_lufs"])
    assert abs(measured["integrated_lufs"] - target_lufs) <= 0.2


def test_16khz_input_is_rejected_without_partial_output(tmp_path: Path) -> None:
    sample_rate = 16_000
    audio = make_dense_stereo(
        sample_rate=sample_rate,
        duration_seconds=3.0,
        amplitude=0.5,
    )
    input_path = write_audio(tmp_path / "sr16k.wav", audio, sample_rate)
    output_path = tmp_path / "sr16k_master.wav"

    result = run_mastering(input_path, output_path)

    assert result.returncode != 0
    assert not output_path.exists()


def test_four_channel_input_is_rejected_without_output(tmp_path: Path) -> None:
    sample_rate = 44_100
    stereo = make_dense_stereo(
        sample_rate=sample_rate,
        duration_seconds=3.0,
        amplitude=0.4,
    )
    four_channel = np.column_stack(
        (
            stereo[:, 0],
            stereo[:, 1],
            stereo[:, 0] * 0.5,
            stereo[:, 1] * 0.25,
        )
    ).astype(np.float32)

    input_path = write_audio(tmp_path / "four_channel.wav", four_channel, sample_rate)
    output_path = tmp_path / "four_channel_master.wav"

    result = run_mastering(input_path, output_path)

    assert result.returncode != 0
    assert not output_path.exists()


def test_masterize_library_function_does_not_call_sys_exit() -> None:
    source = CORE_DSP.read_text(encoding="utf-8")
    module = ast.parse(source)

    masterize_node = next(
        (
            node
            for node in module.body
            if isinstance(node, ast.FunctionDef) and node.name == "masterize"
        ),
        None,
    )
    assert masterize_node is not None

    sys_exit_calls = [
        node
        for node in ast.walk(masterize_node)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "sys"
        and node.func.attr == "exit"
    ]

    assert not sys_exit_calls
