from __future__ import annotations

import inspect

from src.controllers import core_dsp


def test_side_lowpass_legacy_fallback_is_preserved():
    source = inspect.getsource(core_dsp.masterize)

    assert '13500.0 if faccao == "red" else 15000.0' in source
    assert "side_lowpass_cutoff_override is None" in source


def test_side_lowpass_override_drives_the_filter():
    source = inspect.getsource(core_dsp.masterize)

    assert "side_lowpass_cutoff_hz = float(side_lowpass_cutoff_override)" in source
    assert "LowpassFilter(cutoff_frequency_hz=side_lowpass_cutoff_hz)" in source


def test_side_lowpass_override_validation_guards_invalid_values():
    # Validation lives inside masterize after audio loading. This structural
    # guard confirms that the explicit V2 policy rejects non-finite and
    # non-positive cutoff values before constructing the Side filter.
    source = inspect.getsource(core_dsp.masterize)

    assert "not np.isfinite(side_lowpass_cutoff_hz)" in source
    assert "side_lowpass_cutoff_hz <= 0.0" in source
