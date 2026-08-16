from __future__ import annotations

import inspect
from pathlib import Path

from src.controllers import core_dsp, mastering_v2
from src.controllers.mastering_profiles import Atmosphere


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


def test_legacy_faction_inference_remains_only_as_compatibility_fallback():
    assert core_dsp.resolve_legacy_faction("clear_sky") == "blue"
    assert core_dsp.resolve_legacy_faction("aurora") == "blue"
    assert core_dsp.resolve_legacy_faction("thunder") == "red"
    assert core_dsp.resolve_legacy_faction("sunroof") == "red"


def test_explicit_legacy_faction_override_is_independent_of_profile():
    assert core_dsp.resolve_legacy_faction("thunder", "blue") == "blue"
    assert core_dsp.resolve_legacy_faction("clear_sky", "red") == "red"


def test_v2_plan_carries_explicit_blue_compatibility_faction_for_every_atmosphere():
    for atmosphere in Atmosphere:
        plan = mastering_v2.build_render_plan_v2(
            destination="streaming",
            platform="spotify",
            atmosphere=atmosphere,
            intensity_percent=50,
        )
        assert plan.legacy_dsp_style == "clear_sky"
        assert plan.legacy_dsp_intensity == "media"
        assert plan.legacy_dsp_faction == "blue"


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
        assert kwargs == {
            "high_cleanup_amount": 0.0,
            "high_compression_amount": 0.0,
            "side_highpass_cutoff_override": 100.0,
            "mid_compression_enabled": False,
            "side_compression_enabled": False,
            "legacy_faction_override": "blue",
        }
        assert args[10] == 15000.0



def test_v2_bypasses_legacy_high_band_compression(monkeypatch):
    calls = []

    def fake_masterize(*args, **kwargs):
        calls.append((args, kwargs))
        return "ok"

    monkeypatch.setattr(
        mastering_v2.core_dsp,
        "masterize",
        fake_masterize,
    )

    result = mastering_v2.masterize_v2(
        "input.wav",
        "output.wav",
        destination="club",
        atmosphere="clear_sky",
        intensity_percent=50,
        requested_lufs=-11.0,
    )

    assert result == "ok"
    assert len(calls) == 1

    _, kwargs = calls[0]

    assert kwargs == {
        "high_cleanup_amount": 0.0,
        "high_compression_amount": 0.0,
        "side_highpass_cutoff_override": 100.0,
        "mid_compression_enabled": False,
        "side_compression_enabled": False,
        "legacy_faction_override": "blue",
    }


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
        assert kwargs == {
            "high_cleanup_amount": 0.0,
            "high_compression_amount": 0.0,
            "side_highpass_cutoff_override": 100.0,
            "mid_compression_enabled": False,
            "side_compression_enabled": False,
            "legacy_faction_override": "blue",
        }
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
    assert kwargs == {
            "high_cleanup_amount": 0.0,
            "high_compression_amount": 0.0,
            "side_highpass_cutoff_override": 100.0,
            "mid_compression_enabled": False,
            "side_compression_enabled": False,
            "legacy_faction_override": "blue",
        }
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
    assert kwargs == {
            "high_cleanup_amount": 0.0,
            "high_compression_amount": 0.0,
            "side_highpass_cutoff_override": 100.0,
            "mid_compression_enabled": False,
            "side_compression_enabled": False,
            "legacy_faction_override": "blue",
        }
    assert args[7] == 0.5
    assert args[8] == 0.5
    assert args[9] == 0.15
