from __future__ import annotations

import ast
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from conftest import read_audio_metrics, run_mastering, write_audio
from src.controllers.mastering_metrics import MetricsError, measure_audio_file


REPO_ROOT = Path(__file__).resolve().parents[1]
METRICS_MODULE = REPO_ROOT / "src" / "controllers" / "mastering_metrics.py"


def _sine(
    *,
    sample_rate: int = 48_000,
    duration_seconds: float = 5.0,
    amplitude: float = 0.1,
    frequency_hz: float = 1_000.0,
) -> np.ndarray:
    frame_count = int(sample_rate * duration_seconds)
    t = np.arange(frame_count, dtype=np.float64) / sample_rate
    mono = amplitude * np.sin(2.0 * np.pi * frequency_hz * t)
    return np.column_stack((mono, mono)).astype(np.float32)


def test_metrics_measure_known_sine(tmp_path: Path) -> None:
    sample_rate = 48_000
    audio = _sine(sample_rate=sample_rate)
    path = write_audio(tmp_path / "sine.wav", audio, sample_rate)

    metrics = measure_audio_file(path)

    assert metrics.sample_rate == sample_rate
    assert metrics.channels == 2
    assert metrics.frames == sample_rate * 5
    assert metrics.duration_seconds == pytest.approx(5.0, abs=1e-9)
    assert metrics.sample_peak_linear == pytest.approx(0.1, abs=2e-4)
    assert metrics.sample_peak_dbfs == pytest.approx(-20.0, abs=0.05)
    assert metrics.rms_dbfs == pytest.approx(-23.0103, abs=0.08)
    assert metrics.crest_factor_db == pytest.approx(3.0103, abs=0.1)
    assert math.isfinite(metrics.integrated_lufs)
    assert math.isfinite(metrics.true_peak_dbtp)
    assert math.isfinite(metrics.pyloudnorm_integrated_lufs)
    assert abs(metrics.loudness_delta_lu) <= 0.5
    assert len(metrics.sha256) == 64


def test_metrics_reject_missing_file(tmp_path: Path) -> None:
    with pytest.raises(MetricsError, match="does not exist"):
        measure_audio_file(tmp_path / "missing.wav")


def test_metrics_module_does_not_import_core_dsp() -> None:
    module = ast.parse(METRICS_MODULE.read_text(encoding="utf-8"))

    imported_names: list[str] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            imported_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.append(node.module)

    assert not any("core_dsp" in name for name in imported_names)


def test_metrics_cli_returns_json(tmp_path: Path) -> None:
    sample_rate = 48_000
    path = write_audio(tmp_path / "cli.wav", _sine(), sample_rate)

    completed = subprocess.run(
        [sys.executable, str(METRICS_MODULE), str(path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert payload["metrics"]["sample_rate"] == sample_rate
    assert payload["metrics"]["channels"] == 2
    assert math.isfinite(payload["metrics"]["integrated_lufs"])
    assert math.isfinite(payload["metrics"]["true_peak_dbtp"])


def test_metrics_measure_saved_master_output(tmp_path: Path) -> None:
    sample_rate = 44_100
    input_audio = _sine(
        sample_rate=sample_rate,
        duration_seconds=5.0,
        amplitude=0.15,
        frequency_hz=440.0,
    )
    input_path = write_audio(
        tmp_path / "master_input.wav",
        input_audio,
        sample_rate,
    )
    output_path = tmp_path / "master_output.wav"

    completed = run_mastering(input_path, output_path)

    assert completed.returncode == 0, completed.stderr
    assert output_path.exists()

    saved = read_audio_metrics(output_path)
    metrics = measure_audio_file(output_path)

    assert metrics.sample_rate == saved["sample_rate"]
    assert metrics.channels == saved["channels"]
    assert metrics.frames == saved["frames"]
    assert math.isfinite(metrics.integrated_lufs)
    assert math.isfinite(metrics.true_peak_dbtp)


def test_metrics_do_not_modify_measured_file(tmp_path: Path) -> None:
    sample_rate = 48_000
    path = write_audio(tmp_path / "immutable.wav", _sine(), sample_rate)

    before = path.read_bytes()
    first = measure_audio_file(path)
    second = measure_audio_file(path)
    after = path.read_bytes()

    assert before == after
    assert first.sha256 == second.sha256
    assert first.sha256 == hashlib.sha256(before).hexdigest()
