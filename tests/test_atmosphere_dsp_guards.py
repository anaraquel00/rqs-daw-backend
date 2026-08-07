from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from src.controllers import core_dsp, mastering_v2


def _core_source() -> str:
    return inspect.getsource(core_dsp)


def test_delivery_override_remains_after_legacy_loudness_matrix():
    source = _core_source()
    assert source.index("int_level = intensidade.lower().strip()") < source.index(
        "if target_lufs_override is not None:"
    )
    assert source.index("if limiter_ceiling_override is not None:") < source.index(
        "# 6. MATRIZ MID/SIDE"
    )


def test_core_dsp_does_not_import_new_atmosphere_model_yet():
    source = _core_source()
    assert "mastering_atmospheres" not in source


def test_v2_zero_intensity_has_zero_character_amount():
    plan = mastering_v2.build_render_plan_v2(
        destination="club",
        atmosphere="thunder",
        intensity_percent=0,
        requested_lufs=-11.0,
    )
    assert plan.request.character_amount == 0.0
    assert plan.target_lufs == -11.0


def test_v2_hundred_intensity_has_full_character_amount():
    plan = mastering_v2.build_render_plan_v2(
        destination="club",
        atmosphere="thunder",
        intensity_percent=100,
        requested_lufs=-11.0,
    )
    assert plan.request.character_amount == 1.0
    assert plan.target_lufs == -11.0


@pytest.mark.xfail(
    strict=True,
    reason="Known migration debt: legacy core still groups Atmospheres into Blue/Red factions.",
)
def test_core_dsp_no_longer_maps_atmospheres_to_blue_red_factions():
    source = _core_source()
    assert 'faccao = "blue" if perfil in ["clear_sky", "clear sky", "aurora"] else "red"' not in source


@pytest.mark.xfail(
    strict=True,
    reason="Known migration debt: intensity 0 still calls the legacy Clear Sky/media creative path.",
)
def test_zero_intensity_does_not_invoke_legacy_creative_clear_sky_media(monkeypatch):
    calls = []

    def fake_masterize(*args):
        calls.append(args)
        return "ok"

    monkeypatch.setattr(mastering_v2.core_dsp, "masterize", fake_masterize)

    mastering_v2.masterize_v2(
        "input.wav",
        "output.wav",
        destination="club",
        atmosphere="thunder",
        intensity_percent=0,
        requested_lufs=-11.0,
    )

    assert calls
    assert calls[0][2:4] != ("clear_sky", "media")


@pytest.mark.xfail(
    strict=True,
    reason="Known migration debt: fixed high-band LPF/cuts are still part of the default creative path.",
)
def test_default_creative_path_has_no_fixed_15500_hz_high_cleanup():
    source = _core_source()
    assert "hf_cutoff = 15500.0" not in source
    assert "PeakFilter(cutoff_frequency_hz=6500.0, gain_db=-2.0" not in source


@pytest.mark.xfail(
    strict=True,
    reason="Known migration debt: Side low-pass cutoff is still selected from Blue/Red faction.",
)
def test_side_lowpass_is_not_selected_by_blue_red_faction():
    source = _core_source()
    assert '13500.0 if faccao == "red" else 15000.0' not in source


@pytest.mark.xfail(
    strict=True,
    reason="Known migration debt: transient character is still selected by Blue/Red faction.",
)
def test_transient_character_is_not_selected_by_blue_red_faction():
    source = _core_source()
    assert "restore_transients(mid, crest_factor_db, sample_rate, faccao)" not in source


@pytest.mark.xfail(
    strict=True,
    reason="Known migration debt: Side saturation is still unconditional and not controlled by V2 intensity.",
)
def test_side_saturation_is_not_unconditional_in_v2_creative_path():
    source = _core_source()
    assert "side = saturate_side(side, sample_rate)" not in source
