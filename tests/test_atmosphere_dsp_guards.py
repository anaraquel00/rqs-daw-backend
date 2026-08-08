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


def test_zero_intensity_final_render_uses_delivery_only_path(monkeypatch):
    core_calls = []
    loudness_calls = []

    def fake_masterize(*args, **kwargs):
        core_calls.append((args, kwargs))
        return "legacy"

    def fake_finalize_loudness(input_path, output_path, **kwargs):
        loudness_calls.append((input_path, output_path, kwargs))
        return "delivery-only"

    monkeypatch.setattr(mastering_v2.core_dsp, "masterize", fake_masterize)
    monkeypatch.setattr(mastering_v2, "finalize_loudness", fake_finalize_loudness)

    result = mastering_v2.masterize_v2(
        "input.wav",
        "output.wav",
        destination="club",
        atmosphere="thunder",
        intensity_percent=0,
        requested_lufs=-11.0,
    )

    assert result == "delivery-only"
    assert core_calls == []
    assert len(loudness_calls) == 1

    input_path, output_path, kwargs = loudness_calls[0]
    assert input_path == "input.wav"
    assert output_path == "output.wav"
    assert kwargs["target_lufs"] == -11.0
    assert kwargs["ceiling_dbtp"] == -1.0
    assert kwargs["release_ms"] == mastering_v2.DELIVERY_ONLY_RELEASE_MS


def test_v2_bypasses_legacy_fixed_high_cleanup(monkeypatch):
    calls = []

    def fake_masterize(*args, **kwargs):
        calls.append((args, kwargs))
        return "ok"

    monkeypatch.setattr(mastering_v2.core_dsp, "masterize", fake_masterize)

    for atmosphere in ("thunder", "clear_sky"):
        result = mastering_v2.masterize_v2(
            "input.wav",
            "output.wav",
            destination="club",
            atmosphere=atmosphere,
            intensity_percent=50,
            requested_lufs=-11.0,
        )
        assert result == "ok"

    assert len(calls) == 2

    for args, kwargs in calls:
        assert kwargs == {"high_cleanup_amount": 0.0}
        assert args[10] == 15000.0


def test_side_lowpass_is_controlled_by_v2_not_blue_red_faction(monkeypatch):
    calls = []

    def fake_masterize(*args, **kwargs):
        calls.append((args, kwargs))
        return "ok"

    monkeypatch.setattr(mastering_v2.core_dsp, "masterize", fake_masterize)

    for atmosphere in ("thunder", "clear_sky"):
        result = mastering_v2.masterize_v2(
            "input.wav",
            "output.wav",
            destination="club",
            atmosphere=atmosphere,
            intensity_percent=50,
            requested_lufs=-11.0,
        )
        assert result == "ok"

    assert len(calls) == 2

    for args, kwargs in calls:
        assert kwargs == {"high_cleanup_amount": 0.0}
        assert args[10] == 15000.0


def test_transient_character_is_controlled_by_v2_not_blue_red_faction(monkeypatch):
    calls = []

    def fake_masterize(*args, **kwargs):
        calls.append((args, kwargs))
        return "ok"

    monkeypatch.setattr(mastering_v2.core_dsp, "masterize", fake_masterize)

    result = mastering_v2.masterize_v2(
        "input.wav",
        "output.wav",
        destination="club",
        atmosphere="thunder",
        intensity_percent=50,
        requested_lufs=-11.0,
    )

    assert result == "ok"
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert kwargs == {"high_cleanup_amount": 0.0}
    assert args[8] == 0.5
    assert args[9] == 0.15

def test_side_saturation_is_controlled_by_v2_intensity(monkeypatch):
    calls = []

    def fake_masterize(*args, **kwargs):
        calls.append((args, kwargs))
        return "ok"

    monkeypatch.setattr(mastering_v2.core_dsp, "masterize", fake_masterize)

    result = mastering_v2.masterize_v2(
        "input.wav",
        "output.wav",
        destination="club",
        atmosphere="aurora",
        intensity_percent=50,
        requested_lufs=-11.0,
    )

    assert result == "ok"
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert kwargs == {"high_cleanup_amount": 0.0}
    assert args[7] == 0.5
    assert args[8] == 0.5
    assert args[9] == 0.15
