from __future__ import annotations

import math
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

import soundfile as sf

try:
    from .mastering_finalizer import FinalizerError, finalize_true_peak
    from .mastering_metrics import measure_audio_file
except ImportError:
    from mastering_finalizer import FinalizerError, finalize_true_peak
    from mastering_metrics import measure_audio_file


MIN_TARGET_LUFS = -24.0
MAX_TARGET_LUFS = -5.0
DEFAULT_LUFS_TOLERANCE = 0.2
DEFAULT_MAX_PASSES = 6
DEFAULT_MAX_ABS_GAIN_DB = 36.0
DEFAULT_MAX_CORRECTION_STEP_DB = 6.0


class LoudnessFinalizerError(RuntimeError):
    """Raised when loudness and True Peak targets cannot both be verified."""


@dataclass(frozen=True)
class LoudnessFinalizerResult:
    output_path: str
    target_lufs: float
    measured_lufs: float
    measured_true_peak_dbtp: float
    requested_ceiling_dbtp: float
    total_gain_db: float
    input_lufs: float
    passes: int
    sample_rate: int
    channels: int
    frames: int


def _validate_settings(*, target_lufs: float, tolerance_lu: float, max_passes: int) -> None:
    if not math.isfinite(target_lufs):
        raise LoudnessFinalizerError("Target LUFS must be finite.")
    if not MIN_TARGET_LUFS <= target_lufs <= MAX_TARGET_LUFS:
        raise LoudnessFinalizerError(
            f"Target LUFS must be between {MIN_TARGET_LUFS} and {MAX_TARGET_LUFS}."
        )
    if not math.isfinite(tolerance_lu) or not 0.05 <= tolerance_lu <= 1.0:
        raise LoudnessFinalizerError("LUFS tolerance must be between 0.05 and 1.0 LU.")
    if not 1 <= max_passes <= 10:
        raise LoudnessFinalizerError("max_passes must be between 1 and 10.")


def _render_gain(
    input_path: Path,
    output_path: Path,
    *,
    gain_db: float,
    sample_rate: int,
    ffmpeg_binary: str,
) -> None:
    executable = shutil.which(ffmpeg_binary)
    if executable is None:
        raise LoudnessFinalizerError(f"FFmpeg executable not found: {ffmpeg_binary}")

    command = [
        executable,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(input_path),
        "-map_metadata",
        "-1",
        "-vn",
        "-af",
        f"volume={gain_db:.9f}dB:precision=double",
        "-ar",
        str(sample_rate),
        "-c:a",
        "pcm_f32le",
        str(output_path),
    ]

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )
    if completed.returncode != 0:
        combined = f"{completed.stdout}\n{completed.stderr}"
        raise LoudnessFinalizerError(
            f"FFmpeg gain render failed with exit {completed.returncode}:\n{combined[-4000:]}"
        )


def _safe_unlink(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def finalize_loudness(
    input_path: str | Path,
    output_path: str | Path,
    *,
    target_lufs: float,
    ceiling_dbtp: float,
    release_ms: float,
    ffmpeg_binary: str = "ffmpeg",
    tolerance_lu: float = DEFAULT_LUFS_TOLERANCE,
    max_passes: int = DEFAULT_MAX_PASSES,
    max_abs_gain_db: float = DEFAULT_MAX_ABS_GAIN_DB,
) -> LoudnessFinalizerResult:
    """Iteratively hit Integrated LUFS while preserving the verified dBTP ceiling."""
    _validate_settings(
        target_lufs=target_lufs,
        tolerance_lu=tolerance_lu,
        max_passes=max_passes,
    )

    source = Path(input_path).expanduser().resolve()
    target = Path(output_path).expanduser().resolve(strict=False)

    if not source.exists() or not source.is_file():
        raise LoudnessFinalizerError(f"Loudness input does not exist: {source}")
    if source == target:
        raise LoudnessFinalizerError("Loudness input and output must be different.")
    if target.exists():
        raise LoudnessFinalizerError(f"Loudness output already exists: {target}")
    if not target.parent.exists():
        raise LoudnessFinalizerError(f"Loudness output directory does not exist: {target.parent}")

    try:
        source_info = sf.info(str(source))
    except Exception as exc:
        raise LoudnessFinalizerError(f"Cannot inspect loudness input: {exc}") from exc

    sample_rate = int(source_info.samplerate)
    channels = int(source_info.channels)
    frames = int(source_info.frames)

    if channels not in {1, 2}:
        raise LoudnessFinalizerError(f"Unsupported loudness channel count: {channels}")
    if sample_rate <= 0 or frames <= 0:
        raise LoudnessFinalizerError("Loudness input has invalid stream metadata.")

    input_metrics = measure_audio_file(source, ffmpeg_binary=ffmpeg_binary)
    input_lufs = float(input_metrics.integrated_lufs)
    if not math.isfinite(input_lufs):
        raise LoudnessFinalizerError("Input Integrated LUFS is not finite.")

    total_gain_db = float(target_lufs - input_lufs)
    if abs(total_gain_db) > max_abs_gain_db:
        raise LoudnessFinalizerError(
            f"Required initial gain {total_gain_db:.2f} dB exceeds safety limit "
            f"of +/-{max_abs_gain_db:.2f} dB."
        )

    last_error_lu: float | None = None
    last_measured_lufs: float | None = None
    last_measured_tp: float | None = None

    for pass_number in range(1, max_passes + 1):
        token = uuid.uuid4().hex
        gain_path = target.parent / f".{target.name}.{token}.gain.wav"
        pass_output = target.parent / f".{target.name}.{token}.final.wav"

        try:
            _render_gain(
                source,
                gain_path,
                gain_db=total_gain_db,
                sample_rate=sample_rate,
                ffmpeg_binary=ffmpeg_binary,
            )

            try:
                finalize_true_peak(
                    gain_path,
                    pass_output,
                    ceiling_dbtp=ceiling_dbtp,
                    release_ms=release_ms,
                    ffmpeg_binary=ffmpeg_binary,
                )
            except FinalizerError as exc:
                raise LoudnessFinalizerError(str(exc)) from exc

            metrics = measure_audio_file(pass_output, ffmpeg_binary=ffmpeg_binary)
            measured_lufs = float(metrics.integrated_lufs)
            measured_tp = float(metrics.true_peak_dbtp)

            if not math.isfinite(measured_lufs):
                raise LoudnessFinalizerError("Final Integrated LUFS is not finite.")
            if not math.isfinite(measured_tp):
                raise LoudnessFinalizerError("Final True Peak is not finite.")

            error_lu = float(target_lufs - measured_lufs)
            last_error_lu = error_lu
            last_measured_lufs = measured_lufs
            last_measured_tp = measured_tp

            if abs(error_lu) <= tolerance_lu:
                os.replace(pass_output, target)
                pass_output = None
                return LoudnessFinalizerResult(
                    output_path=str(target),
                    target_lufs=float(target_lufs),
                    measured_lufs=measured_lufs,
                    measured_true_peak_dbtp=measured_tp,
                    requested_ceiling_dbtp=float(ceiling_dbtp),
                    total_gain_db=total_gain_db,
                    input_lufs=input_lufs,
                    passes=pass_number,
                    sample_rate=sample_rate,
                    channels=channels,
                    frames=frames,
                )

            correction_db = max(
                -DEFAULT_MAX_CORRECTION_STEP_DB,
                min(DEFAULT_MAX_CORRECTION_STEP_DB, error_lu),
            )
            total_gain_db += correction_db

            if abs(total_gain_db) > max_abs_gain_db:
                raise LoudnessFinalizerError(
                    f"Required gain {total_gain_db:.2f} dB exceeds safety limit "
                    f"of +/-{max_abs_gain_db:.2f} dB."
                )
        finally:
            _safe_unlink(gain_path)
            _safe_unlink(pass_output)

    raise LoudnessFinalizerError(
        f"Unable to reach {target_lufs:.2f} LUFS within +/-{tolerance_lu:.2f} LU "
        f"after {max_passes} passes; last LUFS={last_measured_lufs}, "
        f"last error={last_error_lu}, last True Peak={last_measured_tp}."
    )
