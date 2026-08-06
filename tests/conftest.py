from __future__ import annotations

import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf


REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_DSP = REPO_ROOT / "src" / "controllers" / "core_dsp.py"


def write_audio(
    path: Path,
    audio: np.ndarray,
    sample_rate: int,
    *,
    subtype: str = "FLOAT",
) -> Path:
    """Write samples-first audio for an isolated test case."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, audio, sample_rate, format="WAV", subtype=subtype)
    return path


def make_dense_stereo(
    sample_rate: int = 44_100,
    duration_seconds: float = 8.0,
    amplitude: float = 0.72,
) -> np.ndarray:
    """Generate a deterministic dense stereo signal with phase offsets."""
    sample_count = int(sample_rate * duration_seconds)
    t = np.arange(sample_count, dtype=np.float64) / sample_rate

    left = (
        np.sin(2.0 * np.pi * 97.0 * t)
        + 0.75 * np.sin(2.0 * np.pi * 997.0 * t + 0.17)
        + 0.45 * np.sin(2.0 * np.pi * 6_701.0 * t + 0.31)
        + 0.25 * np.sin(2.0 * np.pi * 12_301.0 * t + 0.63)
    )
    right = (
        np.sin(2.0 * np.pi * 103.0 * t + 0.09)
        + 0.75 * np.sin(2.0 * np.pi * 1_003.0 * t + 0.41)
        + 0.45 * np.sin(2.0 * np.pi * 6_809.0 * t + 0.77)
        + 0.25 * np.sin(2.0 * np.pi * 12_109.0 * t + 1.03)
    )

    stereo = np.column_stack((left, right))
    peak = float(np.max(np.abs(stereo)))
    return (stereo / peak * amplitude).astype(np.float32)


def run_mastering(
    input_path: Path,
    output_path: Path,
    *,
    profile: str = "clear_sky",
    intensity: str = "media",
    preview: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run the existing CLI as Node currently invokes it."""
    args = [
        sys.executable,
        str(CORE_DSP),
        str(input_path),
        str(output_path),
        profile,
        intensity,
    ]
    if preview:
        args.append("true")

    return subprocess.run(
        args,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
    )


def read_audio_metrics(path: Path) -> dict[str, Any]:
    audio, sample_rate = sf.read(path, dtype="float64", always_2d=True)
    return {
        "audio": audio,
        "sample_rate": sample_rate,
        "channels": audio.shape[1],
        "frames": audio.shape[0],
        "finite": bool(np.isfinite(audio).all()),
        "sample_peak": float(np.max(np.abs(audio))) if audio.size else 0.0,
        "rms": float(np.sqrt(np.mean(np.square(audio)))) if audio.size else 0.0,
    }


def ffmpeg_loudness_metrics(path: Path) -> dict[str, float]:
    """Measure the saved WAV independently with FFmpeg loudnorm."""
    command = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-i",
        str(path),
        "-af",
        "loudnorm=I=-23:LRA=7:TP=-1:print_format=json",
        "-f",
        "null",
        "-",
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
    )
    combined = f"{completed.stdout}\n{completed.stderr}"

    matches = re.findall(r"\{\s*\"input_i\".*?\}", combined, flags=re.DOTALL)
    if not matches:
        raise AssertionError(
            "FFmpeg did not return loudnorm JSON.\n"
            f"Exit code: {completed.returncode}\n{combined[-4000:]}"
        )

    parsed = json.loads(matches[-1])

    def to_float(value: Any) -> float:
        text = str(value).strip().lower()
        if text in {"-inf", "inf", "+inf"}:
            return float(text.replace("+", ""))
        return float(text)

    return {
        "integrated_lufs": to_float(parsed["input_i"]),
        "true_peak_dbtp": to_float(parsed["input_tp"]),
        "lra_lu": to_float(parsed["input_lra"]),
        "threshold_lufs": to_float(parsed["input_thresh"]),
    }


@pytest.fixture
def dense_stereo_44100() -> tuple[np.ndarray, int]:
    return make_dense_stereo(), 44_100
