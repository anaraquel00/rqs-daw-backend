from __future__ import annotations

import inspect

from src.controllers import core_dsp, mastering_v2


def test_side_highpass_legacy_fallback_is_preserved():
    source = inspect.getsource(core_dsp.masterize)

    assert "side_highpass_cutoff_override is None" in source
    assert "side_highpass_cutoff_hz = 150.0" in source


def test_side_highpass_override_drives_the_filter():
    source = inspect.getsource(core_dsp.masterize)

    assert "side_highpass_cutoff_hz = float(side_highpass_cutoff_override)" in source
    assert "HighpassFilter(cutoff_frequency_hz=side_highpass_cutoff_hz)" in source


def test_side_highpass_override_validation_guards_invalid_values():
    source = inspect.getsource(core_dsp.masterize)

    assert "not np.isfinite(side_highpass_cutoff_hz)" in source
    assert "side_highpass_cutoff_hz <= 0.0" in source


def test_v2_routes_side_highpass_100(monkeypatch):
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
    assert captured["kwargs"]["side_highpass_cutoff_override"] == 100.0


def test_side_highpass_override_remains_optional_before_v2_cleanup_controls():
    params = list(inspect.signature(core_dsp.masterize).parameters.values())
    names = [param.name for param in params]

    idx = names.index("side_highpass_cutoff_override")
    assert params[idx].default is None
    assert names[idx + 1:idx + 3] == [
        "mid_compression_enabled",
        "side_compression_enabled",
    ]
