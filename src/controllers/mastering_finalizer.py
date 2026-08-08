from __future__ import annotations

import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import soundfile as sf

try:
    from .mastering_metrics import measure_audio_file
except ImportError:
    from mastering_metrics import measure_audio_file


MIN_CEILING_DBTP = -9.0
MAX_CEILING_DBTP = 0.0
MIN_RELEASE_MS = 5.0
MAX_RELEASE_MS = 1000.0
DEFAULT_ATTACK_MS = 5.0
DEFAULT_OVERSAMPLE_FACTOR = 4
DEFAULT_TOLERANCE_DB = 0.05
DEFAULT_GUARD_DB = 0.05
DEFAULT_MAX_PASSES = 4


class FinalizerError(RuntimeError):
    """Raised when the final True Peak stage cannot meet its contract."""


@dataclass(frozen=True)
class FinalizerResult:
    output_path: str
    requested_ceiling_dbtp: float
    measured_true_peak_dbtp: float
    limiter_threshold_dbtp: float
    passes: int
    sample_rate: int
    channels: int
    frames: int


def db_to_linear(db_value: float) -> float:
    return 10.0 ** (db_value / 20.0)


def _validate_settings(
    *,
    ceiling_dbtp: float,
    release_ms: float,
    oversample_factor: int,
    max_passes: int,
    tolerance_db: float,
) -> None:
    if not math.isfinite(ceiling_dbtp):
        raise FinalizerError("True Peak ceiling must be finite.")
    if not MIN_CEILING_DBTP <= ceiling_dbtp <= MAX_CEILING_DBTP:
        raise FinalizerError(
            f"True Peak ceiling must be between {MIN_CEILING_DBTP} and "
            f"{MAX_CEILING_DBTP} dBTP."
        )
    if not math.isfinite(release_ms) or not MIN_RELEASE_MS <= release_ms <= MAX_RELEASE_MS:
        raise FinalizerError(
            f"Limiter release must be between {MIN_RELEASE_MS} and "
            f"{MAX_RELEASE_MS} ms."
        )
    if oversample_factor not in {2, 4}:
        raise FinalizerError("Oversample factor must be 2 or 4.")
    if not 1 <= max_passes <= 8:
        raise FinalizerError("max_passes must be between 1 and 8.")
    if not math.isfinite(tolerance_db) or not 0.0 <= tolerance_db <= 0.25:
        raise FinalizerError("True Peak tolerance must be between 0 and 0.25 dB.")


def _run_ffmpeg_limiter(
    input_path: Path,
    output_path: Path,
    *,
    sample_rate: int,
    threshold_dbtp: float,
    release_ms: float,
    attack_ms: float,
    oversample_factor: int,
    ffmpeg_binary: str,
) -> None:
    executable = shutil.which(ffmpeg_binary)
    if executable is None:
        raise FinalizerError(f"FFmpeg executable not found: {ffmpeg_binary}")

    oversampled_rate = sample_rate * oversample_factor
    limit_linear = db_to_linear(threshold_dbtp)

    filter_chain = (
        f"aresample={oversampled_rate},"
        f"alimiter="
        f"limit={limit_linear:.12f}:"
        f"attack={attack_ms:.3f}:"
        f"release={release_ms:.3f}:"
        f"level=false:"
        f"latency=true,"
        f"aresample={sample_rate}"
    )

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
        filter_chain,
        "-ar",
        str(sample_rate),
        "-c:a",
        "pcm_s24le",
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
        raise FinalizerError(
            f"FFmpeg True Peak finalizer failed with exit "
            f"{completed.returncode}:\n{combined[-4000:]}"
        )


def finalize_true_peak(
    input_path: str | Path,
    output_path: str | Path,
    *,
    ceiling_dbtp: float,
    release_ms: float,
    ffmpeg_binary: str = "ffmpeg",
    oversample_factor: int = DEFAULT_OVERSAMPLE_FACTOR,
    attack_ms: float = DEFAULT_ATTACK_MS,
    tolerance_db: float = DEFAULT_TOLERANCE_DB,
    guard_db: float = DEFAULT_GUARD_DB,
    max_passes: int = DEFAULT_MAX_PASSES,
) -> FinalizerResult:
    """Render PCM24 and verify True Peak on the final saved file."""
    _validate_settings(
        ceiling_dbtp=ceiling_dbtp,
        release_ms=release_ms,
        oversample_factor=oversample_factor,
        max_passes=max_passes,
        tolerance_db=tolerance_db,
    )

    source = Path(input_path).expanduser().resolve()
    target = Path(output_path).expanduser().resolve(strict=False)

    if not source.exists() or not source.is_file():
        raise FinalizerError(f"Finalizer input does not exist: {source}")
    if source == target:
        raise FinalizerError("Finalizer input and output must be different.")
    if target.exists():
        raise FinalizerError(f"Finalizer output already exists: {target}")
    if not target.parent.exists():
        raise FinalizerError(f"Finalizer output directory does not exist: {target.parent}")

    try:
        source_info = sf.info(str(source))
    except Exception as exc:
        raise FinalizerError(f"Cannot inspect finalizer input: {exc}") from exc

    sample_rate = int(source_info.samplerate)
    channels = int(source_info.channels)
    frames = int(source_info.frames)

    if channels not in {1, 2}:
        raise FinalizerError(f"Unsupported finalizer channel count: {channels}")
    if sample_rate <= 0 or frames <= 0:
        raise FinalizerError("Finalizer input has invalid stream metadata.")

    threshold_dbtp = float(ceiling_dbtp)

    for pass_number in range(1, max_passes + 1):
        if target.exists():
            target.unlink()

        _run_ffmpeg_limiter(
            source,
            target,
            sample_rate=sample_rate,
            threshold_dbtp=threshold_dbtp,
            release_ms=release_ms,
            attack_ms=attack_ms,
            oversample_factor=oversample_factor,
            ffmpeg_binary=ffmpeg_binary,
        )

        try:
            rendered_info = sf.info(str(target))
        except Exception as exc:
            target.unlink(missing_ok=True)
            raise FinalizerError(f"Cannot inspect rendered finalizer output: {exc}") from exc

        if int(rendered_info.samplerate) != sample_rate:
            target.unlink(missing_ok=True)
            raise FinalizerError(
                f"Finalizer changed sample rate: {rendered_info.samplerate} != {sample_rate}"
            )
        if int(rendered_info.channels) != channels:
            target.unlink(missing_ok=True)
            raise FinalizerError(
                f"Finalizer changed channel count: {rendered_info.channels} != {channels}"
            )
        if abs(int(rendered_info.frames) - frames) > 1:
            target.unlink(missing_ok=True)
            raise FinalizerError(
                f"Finalizer changed frame count: {rendered_info.frames} != {frames}"
            )
        if str(rendered_info.subtype).upper() != "PCM_24":
            target.unlink(missing_ok=True)
            raise FinalizerError(
                f"Finalizer output subtype is {rendered_info.subtype}, expected PCM_24."
            )

        metrics = measure_audio_file(
            target,
            ffmpeg_binary=ffmpeg_binary,
        )
        measured_tp = float(metrics.true_peak_dbtp)

        if math.isfinite(measured_tp) and measured_tp <= ceiling_dbtp + tolerance_db:
            return FinalizerResult(
                output_path=str(target),
                requested_ceiling_dbtp=float(ceiling_dbtp),
                measured_true_peak_dbtp=measured_tp,
                limiter_threshold_dbtp=threshold_dbtp,
                passes=pass_number,
                sample_rate=sample_rate,
                channels=channels,
                frames=int(rendered_info.frames),
            )

        if not math.isfinite(measured_tp):
            target.unlink(missing_ok=True)
            raise FinalizerError("Final True Peak measurement is not finite.")

        overshoot_db = measured_tp - ceiling_dbtp
        threshold_dbtp -= max(guard_db, overshoot_db + guard_db)

        if threshold_dbtp < MIN_CEILING_DBTP:
            target.unlink(missing_ok=True)
            raise FinalizerError(
                "Required limiter threshold fell below the supported safety range."
            )

    target.unlink(missing_ok=True)
    raise FinalizerError(
        f"Unable to meet True Peak ceiling {ceiling_dbtp:.2f} dBTP "
        f"within {max_passes} passes."
    )
