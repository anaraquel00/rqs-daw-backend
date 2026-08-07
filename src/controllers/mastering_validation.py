from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import numpy as np
import soundfile as sf


MIN_SAMPLE_RATE_HZ = 32_000
MAX_SAMPLE_RATE_HZ = 192_000
MIN_DURATION_SECONDS = 0.5
SILENCE_PEAK_THRESHOLD = 1e-7
SUPPORTED_CHANNELS = frozenset({1, 2})


class AudioValidationError(ValueError):
    """Raised when an input or output violates the mastering contract."""


@dataclass(frozen=True)
class ValidatedInput:
    input_path: Path
    output_path: Path
    sample_rate: int
    channels: int
    frames: int


def _normalized_path(path: Path) -> str:
    return os.path.normcase(str(path.resolve(strict=False)))


def validate_mastering_request(input_path: str, output_path: str) -> ValidatedInput:
    input_file = Path(input_path).expanduser()
    output_file = Path(output_path).expanduser()

    if not input_file.exists() or not input_file.is_file():
        raise AudioValidationError(f"Input audio file does not exist: {input_file}")

    input_file = input_file.resolve(strict=True)
    output_file = output_file.resolve(strict=False)

    if _normalized_path(input_file) == _normalized_path(output_file):
        raise AudioValidationError("Input and output paths must be different.")

    if output_file.exists():
        raise AudioValidationError(f"Output path already exists: {output_file}")

    if not output_file.parent.exists() or not output_file.parent.is_dir():
        raise AudioValidationError(
            f"Output directory does not exist: {output_file.parent}"
        )

    try:
        info = sf.info(str(input_file))
    except Exception as exc:
        raise AudioValidationError(f"Cannot inspect input audio: {exc}") from exc

    sample_rate = int(info.samplerate)
    channels = int(info.channels)
    frames = int(info.frames)

    if channels not in SUPPORTED_CHANNELS:
        raise AudioValidationError(
            f"Unsupported channel count: {channels}. Only mono and stereo are supported."
        )

    if not MIN_SAMPLE_RATE_HZ <= sample_rate <= MAX_SAMPLE_RATE_HZ:
        raise AudioValidationError(
            f"Unsupported sample rate: {sample_rate} Hz. "
            f"Supported range is {MIN_SAMPLE_RATE_HZ}-{MAX_SAMPLE_RATE_HZ} Hz."
        )

    minimum_frames = max(1, int(np.ceil(MIN_DURATION_SECONDS * sample_rate)))
    if frames < minimum_frames:
        duration = frames / sample_rate if sample_rate else 0.0
        raise AudioValidationError(
            f"Input audio is too short: {duration:.3f} s. "
            f"Minimum duration is {MIN_DURATION_SECONDS:.3f} s."
        )

    return ValidatedInput(
        input_path=input_file,
        output_path=output_file,
        sample_rate=sample_rate,
        channels=channels,
        frames=frames,
    )


def validate_audio_samples(
    audio_data: np.ndarray,
    *,
    expected_channels: int,
) -> np.ndarray:
    audio = np.asarray(audio_data, dtype=np.float32)

    if audio.size == 0:
        raise AudioValidationError("Input audio contains no samples.")

    if audio.ndim not in (1, 2):
        raise AudioValidationError(f"Unsupported audio array shape: {audio.shape}")

    actual_channels = 1 if audio.ndim == 1 else int(audio.shape[1])
    if actual_channels != expected_channels:
        raise AudioValidationError(
            f"Decoded channel count changed from {expected_channels} to {actual_channels}."
        )

    if not np.isfinite(audio).all():
        raise AudioValidationError("Input audio contains NaN or infinite samples.")

    peak = float(np.max(np.abs(audio)))
    if peak <= SILENCE_PEAK_THRESHOLD:
        raise AudioValidationError("Input audio is silent or below the safety threshold.")

    return audio


def create_temporary_output_path(output_path: str) -> Path:
    output_file = Path(output_path)
    return output_file.with_name(
        f".{output_file.stem}.{uuid4().hex}.tmp{output_file.suffix}"
    )


def validate_written_output(
    path: Path,
    *,
    expected_sample_rate: int,
    expected_channels: int = 2,
) -> None:
    try:
        info = sf.info(str(path))
    except Exception as exc:
        raise AudioValidationError(f"Cannot reopen rendered output: {exc}") from exc

    if int(info.samplerate) != int(expected_sample_rate):
        raise AudioValidationError(
            f"Rendered sample rate mismatch: {info.samplerate} != {expected_sample_rate}."
        )

    if int(info.channels) != int(expected_channels):
        raise AudioValidationError(
            f"Rendered channel count mismatch: {info.channels} != {expected_channels}."
        )

    if int(info.frames) <= 0:
        raise AudioValidationError("Rendered output contains no frames.")

    for block in sf.blocks(
        str(path),
        blocksize=65_536,
        dtype="float32",
        always_2d=True,
    ):
        if not np.isfinite(block).all():
            raise AudioValidationError("Rendered output contains NaN or infinite samples.")


def publish_temporary_output(temporary_path: Path, output_path: str) -> None:
    output_file = Path(output_path)

    if output_file.exists():
        raise AudioValidationError(f"Output path appeared during render: {output_file}")

    try:
        os.link(temporary_path, output_file)
    except FileExistsError as exc:
        raise AudioValidationError(f"Output path already exists: {output_file}") from exc
    except OSError as exc:
        raise AudioValidationError(
            f"Cannot publish output atomically using a hard link: {exc}"
        ) from exc

    temporary_path.unlink()


def cleanup_temporary_output(path: Path | None) -> None:
    if path is None:
        return

    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
