from __future__ import annotations

import inspect

from src.controllers import core_dsp, mastering_v2


def test_legacy_defaults_keep_mid_and_side_compressors_enabled():
    params = inspect.signature(core_dsp.masterize).parameters

    assert params["mid_compression_enabled"].default is True
    assert params["side_compression_enabled"].default is True


def test_v2_compatibility_controls_are_optional_signature_tail():
    params = list(inspect.signature(core_dsp.masterize).parameters.values())

    assert params[-3].name == "mid_compression_enabled"
    assert params[-3].default is True
    assert params[-2].name == "side_compression_enabled"
    assert params[-2].default is True
    assert params[-1].name == "legacy_faction_override"
    assert params[-1].default is None


def test_v2_explicitly_disables_dead_mid_and_side_compressors(monkeypatch):
    captured = {}

    def fake(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return "ok"

    monkeypatch.setattr(mastering_v2.core_dsp, "masterize", fake)

    result = mastering_v2.masterize_v2(
        "in",
        "out",
        destination="streaming",
        platform="spotify",
        atmosphere="clear_sky",
        intensity_percent=50,
    )

    assert result == "ok"
    assert captured["kwargs"]["mid_compression_enabled"] is False
    assert captured["kwargs"]["side_compression_enabled"] is False


def test_mid_compressor_is_not_constructed_when_disabled():
    source = inspect.getsource(core_dsp.masterize)

    assert "if mid_compression_enabled else None" in source
    assert "if mid_compression_enabled:" in source
    assert "mid_mid_processed = mid_mid" in source


def test_side_compressor_is_not_added_when_disabled():
    source = inspect.getsource(core_dsp.masterize)

    assert "if side_compression_enabled:" in source
    assert "board_side.append(side_comp)" in source
