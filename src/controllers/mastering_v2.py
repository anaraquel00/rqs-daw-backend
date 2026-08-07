from __future__ import annotations

from dataclasses import dataclass
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


DELIVERY_ONLY_RELEASE_MS = 120.0


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
                 soundcloud_mode=SoundCloudMode.STANDARD, is_preview=False):
    plan = build_render_plan_v2(
        destination=destination,
        platform=platform,
        atmosphere=atmosphere,
        intensity_percent=intensity_percent,
        requested_lufs=requested_lufs,
        soundcloud_mode=soundcloud_mode,
    )
    # V2 contract: 0% means no creative Atmosphere processing.
    # Keep preview on the legacy path for now; preview architecture is a
    # separate migration item and must not be changed silently here.
    if plan.request.character_amount == 0.0 and not is_preview:
        return finalize_loudness(
            input_path,
            output_path,
            target_lufs=plan.target_lufs,
            ceiling_dbtp=plan.true_peak_ceiling_dbtp,
            release_ms=DELIVERY_ONLY_RELEASE_MS,
        )

    return core_dsp.masterize(
        input_path, output_path,
        plan.legacy_dsp_style,
        plan.legacy_dsp_intensity,
        is_preview,
        plan.target_lufs,
        plan.true_peak_ceiling_dbtp,
        plan.request.character_amount,
    )
