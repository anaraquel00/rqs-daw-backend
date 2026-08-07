from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pyloudnorm as pyln
import soundfile as sf


class MetricsError(RuntimeError):
    """Raised when an audio file cannot be measured reliably."""


@dataclass(frozen=True)
class AudioMetrics:
    path: str
    sha256: str
    sample_rate: int
    channels: int
    frames: int
    duration_seconds: float
    sample_peak_linear: float
    sample_peak_dbfs: float
    rms_linear: float
    rms_dbfs: float
    crest_factor_db: float
    integrated_lufs: float
    true_peak_dbtp: float
    loudness_range_lu: float
    loudness_threshold_lufs: float
    pyloudnorm_integrated_lufs: float
    loudness_delta_lu: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _dbfs(value: float) -> float:
    if value <= 0.0:
        return float("-inf")
    return 20.0 * math.log10(value)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _parse_number(value: Any) -> float:
    text = str(value).strip().lower()
    if text == "-inf":
        return float("-inf")
    if text in {"inf", "+inf"}:
        return float("inf")
    try:
        return float(text)
    except ValueError as exc:
        raise MetricsError(f"Invalid FFmpeg metric value: {value!r}") from exc


def _ffmpeg_loudnorm_metrics(
    path: Path,
    *,
    ffmpeg_binary: str = "ffmpeg",
) -> dict[str, float]:
    executable = shutil.which(ffmpeg_binary)
    if executable is None:
        raise MetricsError(f"FFmpeg executable not found: {ffmpeg_binary}")

    command = [
        executable,
        "-nostdin",
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
        timeout=300,
        check=False,
    )

    combined = f"{completed.stdout}\n{completed.stderr}"
    if completed.returncode != 0:
        raise MetricsError(
            "FFmpeg loudness analysis failed "
            f"(exit {completed.returncode}):\n{combined[-4000:]}"
        )

    matches = re.findall(
        r'\{\s*"input_i".*?\}',
        combined,
        flags=re.DOTALL,
    )
    if not matches:
        raise MetricsError(
            "FFmpeg loudnorm JSON was not found in analyzer output."
        )

    try:
        payload = json.loads(matches[-1])
    except json.JSONDecodeError as exc:
        raise MetricsError("Invalid FFmpeg loudnorm JSON.") from exc

    return {
        "integrated_lufs": _parse_number(payload["input_i"]),
        "true_peak_dbtp": _parse_number(payload["input_tp"]),
        "loudness_range_lu": _parse_number(payload["input_lra"]),
        "loudness_threshold_lufs": _parse_number(payload["input_thresh"]),
    }


def measure_audio_file(
    audio_path: str | Path,
    *,
    ffmpeg_binary: str = "ffmpeg",
) -> AudioMetrics:
    """Measure the final saved audio file using an independent analyzer path."""
    path = Path(audio_path).expanduser().resolve()

    if not path.exists():
        raise MetricsError(f"Audio file does not exist: {path}")
    if not path.is_file():
        raise MetricsError(f"Audio path is not a file: {path}")

    try:
        audio, sample_rate = sf.read(
            path,
            dtype="float64",
            always_2d=True,
        )
    except (RuntimeError, OSError, ValueError) as exc:
        raise MetricsError(f"Unable to read audio file: {path}") from exc

    if audio.size == 0 or audio.shape[0] == 0:
        raise MetricsError("Audio file contains no frames.")
    if sample_rate <= 0:
        raise MetricsError(f"Invalid sample rate: {sample_rate}")
    if audio.shape[1] <= 0:
        raise MetricsError("Audio file contains no channels.")
    if not np.isfinite(audio).all():
        raise MetricsError("Audio file contains NaN or Inf samples.")

    frames = int(audio.shape[0])
    channels = int(audio.shape[1])
    duration_seconds = frames / float(sample_rate)

    sample_peak_linear = float(np.max(np.abs(audio)))
    rms_linear = float(np.sqrt(np.mean(np.square(audio))))
    sample_peak_dbfs = _dbfs(sample_peak_linear)
    rms_dbfs = _dbfs(rms_linear)

    if rms_linear > 0.0 and sample_peak_linear > 0.0:
        crest_factor_db = sample_peak_dbfs - rms_dbfs
    else:
        crest_factor_db = float("nan")

    try:
        pyloudnorm_integrated_lufs = float(
            pyln.Meter(sample_rate).integrated_loudness(audio)
        )
    except Exception as exc:
        raise MetricsError("pyloudnorm integrated loudness measurement failed.") from exc

    ffmpeg_metrics = _ffmpeg_loudnorm_metrics(
        path,
        ffmpeg_binary=ffmpeg_binary,
    )

    integrated_lufs = ffmpeg_metrics["integrated_lufs"]
    loudness_delta_lu = integrated_lufs - pyloudnorm_integrated_lufs

    return AudioMetrics(
        path=str(path),
        sha256=_sha256(path),
        sample_rate=int(sample_rate),
        channels=channels,
        frames=frames,
        duration_seconds=duration_seconds,
        sample_peak_linear=sample_peak_linear,
        sample_peak_dbfs=sample_peak_dbfs,
        rms_linear=rms_linear,
        rms_dbfs=rms_dbfs,
        crest_factor_db=crest_factor_db,
        integrated_lufs=integrated_lufs,
        true_peak_dbtp=ffmpeg_metrics["true_peak_dbtp"],
        loudness_range_lu=ffmpeg_metrics["loudness_range_lu"],
        loudness_threshold_lufs=ffmpeg_metrics["loudness_threshold_lufs"],
        pyloudnorm_integrated_lufs=pyloudnorm_integrated_lufs,
        loudness_delta_lu=loudness_delta_lu,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure a saved master WAV independently."
    )
    parser.add_argument("audio_path")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()

    try:
        metrics = measure_audio_file(
            args.audio_path,
            ffmpeg_binary=args.ffmpeg,
        )
    except MetricsError as exc:
        print(
            json.dumps(
                {"ok": False, "error": str(exc)},
                ensure_ascii=False,
            )
        )
        return 2

    print(
        json.dumps(
            {"ok": True, "metrics": metrics.to_dict()},
            ensure_ascii=False,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
