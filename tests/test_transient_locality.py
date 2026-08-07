from __future__ import annotations

import numpy as np
import pytest


def _impulse(sample_rate: int, amplitude: float = 0.5, position_seconds: float = 0.2) -> tuple[np.ndarray, int]:
    signal = np.zeros(sample_rate, dtype=np.float32)
    index = int(position_seconds * sample_rate)
    signal[index] = amplitude
    return signal, index


def _test_signal(sample_rate: int) -> np.ndarray:
    t = np.arange(sample_rate, dtype=np.float64) / sample_rate
    signal = (
        0.22 * np.sin(2.0 * np.pi * 110.0 * t)
        + 0.08 * np.sin(2.0 * np.pi * 2200.0 * t)
    ).astype(np.float32)
    signal[int(0.20 * sample_rate)] += 0.35
    signal[int(0.55 * sample_rate)] += 0.65
    return signal


def test_restore_transients_preserves_silence(core_dsp_module):
    silence = np.zeros(48_000, dtype=np.float32)

    processed = core_dsp_module.restore_transients(
        silence,
        crest_factor=7.5,
        sample_rate=48_000,
        faccao="blue",
    )

    assert processed.dtype == np.float32
    assert np.array_equal(processed, silence)


@pytest.mark.parametrize("sample_rate", [44_100, 48_000, 96_000])
def test_restore_transients_preserves_shape_dtype_and_finite_samples(
    core_dsp_module,
    sample_rate: int,
):
    signal = _test_signal(sample_rate)

    processed = core_dsp_module.restore_transients(
        signal,
        crest_factor=7.5,
        sample_rate=sample_rate,
        faccao="blue",
    )

    assert processed.shape == signal.shape
    assert processed.dtype == np.float32
    assert np.all(np.isfinite(processed))


@pytest.mark.parametrize(
    ("faccao", "crest_factor"),
    [
        ("red", 6.0),
        ("blue", 8.5),
        ("red", 8.5),
    ],
)
def test_restore_transients_preserves_existing_crest_bypass_rules(
    core_dsp_module,
    faccao: str,
    crest_factor: float,
):
    signal = _test_signal(48_000)

    processed = core_dsp_module.restore_transients(
        signal,
        crest_factor=crest_factor,
        sample_rate=48_000,
        faccao=faccao,
    )

    assert np.array_equal(processed, signal)


@pytest.mark.parametrize(
    ("faccao", "maximum_gain"),
    [
        ("blue", 1.15),
        ("red", 1.08),
    ],
)
def test_restore_transients_gain_is_bounded(
    core_dsp_module,
    faccao: str,
    maximum_gain: float,
):
    signal = _test_signal(48_000)

    processed = core_dsp_module.restore_transients(
        signal,
        crest_factor=7.5,
        sample_rate=48_000,
        faccao=faccao,
    )

    assert np.all(
        np.abs(processed)
        <= (np.abs(signal) * maximum_gain + 2e-7)
    )


def test_restore_transients_is_scale_invariant_for_same_local_shape(core_dsp_module):
    low, index = _impulse(48_000, amplitude=0.10)
    high, _ = _impulse(48_000, amplitude=0.50)

    low_processed = core_dsp_module.restore_transients(
        low,
        crest_factor=7.5,
        sample_rate=48_000,
        faccao="blue",
    )
    high_processed = core_dsp_module.restore_transients(
        high,
        crest_factor=7.5,
        sample_rate=48_000,
        faccao="blue",
    )

    low_gain = float(low_processed[index] / low[index])
    high_gain = float(high_processed[index] / high[index])

    assert abs(low_gain - high_gain) <= 1e-6


def test_restore_transients_future_peak_does_not_change_earlier_region(core_dsp_module):
    sample_rate = 48_000
    first, _ = _impulse(sample_rate, amplitude=0.25, position_seconds=0.20)
    later_index = int(0.80 * sample_rate)

    with_future_peak = first.copy()
    with_future_peak[later_index] = 1.0

    first_processed = core_dsp_module.restore_transients(
        first,
        crest_factor=7.5,
        sample_rate=sample_rate,
        faccao="blue",
    )
    future_processed = core_dsp_module.restore_transients(
        with_future_peak,
        crest_factor=7.5,
        sample_rate=sample_rate,
        faccao="blue",
    )

    assert np.array_equal(
        first_processed[:later_index],
        future_processed[:later_index],
    )


def test_restore_transients_handles_very_short_signal(core_dsp_module):
    signal = np.array([0.0, 0.5, 0.0], dtype=np.float32)

    processed = core_dsp_module.restore_transients(
        signal,
        crest_factor=7.5,
        sample_rate=48_000,
        faccao="blue",
    )

    assert processed.shape == signal.shape
    assert processed.dtype == np.float32
    assert np.all(np.isfinite(processed))
