from __future__ import annotations

from dataclasses import dataclass
from . import core_dsp
from .mastering_profiles import (
    Atmosphere, Destination, MasteringRequest, Platform,
    build_mastering_request, recommended_true_peak_ceiling,
)

@dataclass(frozen=True)
class RenderPlanV2:
    request: MasteringRequest
    target_lufs: float
    true_peak_ceiling_dbtp: float
    legacy_dsp_style: str = "clear_sky"
    legacy_dsp_intensity: str = "media"

def build_render_plan_v2(*, destination, atmosphere, intensity_percent, platform=None):
    request = build_mastering_request(
        destination=destination,
        platform=platform,
        atmosphere=atmosphere,
        intensity_percent=intensity_percent,
    )
    return RenderPlanV2(
        request=request,
        target_lufs=request.delivery.target_lufs,
        true_peak_ceiling_dbtp=recommended_true_peak_ceiling(request.delivery),
    )

def masterize_v2(input_path, output_path, *, destination, atmosphere,
                 intensity_percent, platform=None, is_preview=False):
    plan = build_render_plan_v2(
        destination=destination,
        platform=platform,
        atmosphere=atmosphere,
        intensity_percent=intensity_percent,
    )
    return core_dsp.masterize(
        input_path, output_path,
        plan.legacy_dsp_style,
        plan.legacy_dsp_intensity,
        is_preview,
        plan.target_lufs,
        plan.true_peak_ceiling_dbtp,
    )
