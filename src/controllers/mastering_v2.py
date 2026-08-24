from __future__ import annotations

import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import soundfile as sf

from . import core_dsp
from .mastering_loudness import finalize_loudness
from .mastering_profiles import (
    Atmosphere, Destination, MasteringRequest, Platform, SoundCloudMode,
    build_mastering_request, recommended_true_peak_ceiling,
)

@dataclass(frozen=True)
class RenderPlanV2:
    request: MasteringRequest
    target_lufs: float
    true_peak_ceiling_dbtp: float
    legacy_dsp_style: str = "clear_sky"
    legacy_dsp_intensity: str = "media"
    legacy_dsp_faction: str = "blue"


DELIVERY_ONLY_RELEASE_MS = 120.0
PREVIEW_DURATION_SECONDS = 15.0


def _create_preview_source_segment(input_path, start_seconds=None) -> Path:
    info = sf.info(str(input_path))
    sample_rate = int(info.samplerate)
    total_frames = int(info.frames)
    preview_frames = int(PREVIEW_DURATION_SECONDS * sample_rate)

    if start_seconds is not None:
        start_seconds = float(start_seconds)
        if not math.isfinite(start_seconds) or start_seconds < 0:
            raise ValueError("preview_start_seconds must be a finite value greater than or equal to 0")

    if total_frames > preview_frames:
        max_start_frame = total_frames - preview_frames
        if start_seconds is None:
            start_frame = int(total_frames / 2) - int(preview_frames / 2)
        else:
            requested_start_frame = int(round(start_seconds * sample_rate))
            start_frame = min(requested_start_frame, max_start_frame)
        frames = preview_frames
    else:
        start_frame = 0
        frames = total_frames

    audio_data, read_sample_rate = sf.read(
        str(input_path),
        start=start_frame,
        frames=frames,
        dtype="float32",
        always_2d=True,
    )

    fd, temporary_name = tempfile.mkstemp(
        prefix="rqs_v2_preview_",
        suffix=".wav",
    )
    os.close(fd)
    temporary_path = Path(temporary_name)

    try:
        sf.write(
            str(temporary_path),
            audio_data,
            int(read_sample_rate),
            format="WAV",
            subtype="FLOAT",
        )
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    return temporary_path


def _cleanup_preview_source_segment(path: Path | None) -> None:
    if path is not None:
        path.unlink(missing_ok=True)


def build_render_plan_v2(*, destination, atmosphere, intensity_percent, platform=None, requested_lufs=None, soundcloud_mode=SoundCloudMode.STANDARD):
    request = build_mastering_request(
        destination=destination,
        platform=platform,
        atmosphere=atmosphere,
        intensity_percent=intensity_percent,
        requested_lufs=requested_lufs,
        soundcloud_mode=soundcloud_mode,
    )
    return RenderPlanV2(
        request=request,
        target_lufs=request.target_lufs,
        true_peak_ceiling_dbtp=recommended_true_peak_ceiling(request.delivery, request.target_lufs),
    )

def masterize_v2(input_path, output_path, *, destination, atmosphere,
                 intensity_percent, platform=None, requested_lufs=None,
                 soundcloud_mode=SoundCloudMode.STANDARD, is_preview=False,
                 preview_start_seconds=None):
    plan = build_render_plan_v2(
        destination=destination,
        platform=platform,
        atmosphere=atmosphere,
        intensity_percent=intensity_percent,
        requested_lufs=requested_lufs,
        soundcloud_mode=soundcloud_mode,
    )
    preview_source = None
    effective_input_path = input_path

    try:
        if is_preview:
            if preview_start_seconds is None:
                preview_source = _create_preview_source_segment(input_path)
            else:
                preview_source = _create_preview_source_segment(input_path, preview_start_seconds)
            effective_input_path = str(preview_source)

        # V2 contract: 0% means no creative Atmosphere processing.
        # Preview uses the same delivery-only contract on the selected source
        # segment (centered only when no explicit start is requested).
        if plan.request.character_amount == 0.0:
            return finalize_loudness(
                effective_input_path,
                output_path,
                target_lufs=plan.target_lufs,
                ceiling_dbtp=plan.true_peak_ceiling_dbtp,
                release_ms=DELIVERY_ONLY_RELEASE_MS,
            )

        return core_dsp.masterize(
            effective_input_path, output_path,
            plan.legacy_dsp_style,
            plan.legacy_dsp_intensity,
            is_preview,
            plan.target_lufs,
            plan.true_peak_ceiling_dbtp,
            plan.request.character_amount,
            plan.request.character_amount,
            0.15,
            15000.0,
            high_cleanup_amount=0.0,
            high_compression_amount=0.0,
            side_highpass_cutoff_override=100.0,
            mid_compression_enabled=False,
            side_compression_enabled=False,
            legacy_faction_override=plan.legacy_dsp_faction,
        )
    finally:
        _cleanup_preview_source_segment(preview_source)
