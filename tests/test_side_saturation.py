from __future__ import annotations

import math

import numpy as np
import pytest


def _sine(sample_rate: int, frequency: float, seconds: float, amplitude: float = 0.5) -> np.ndarray:
    sample_count = int(round(sample_rate * seconds))
    t = np.arange(sample_count, dtype=np.float64) / sample_rate
    return (amplitude * np.sin(2.0 * np.pi * frequency * t)).astype(np.float32)


def _band_energy(signal: np.ndarray, sample_rate: int, center_hz: float, width_hz: float = 50.0) -> float:
    signal = np.asarray(signal, dtype=np.float64)
    window = np.hanning(signal.size)
    spectrum = np.fft.rfft(signal * window)
    frequencies = np.fft.rfftfreq(signal.size, 1.0 / sample_rate)
    mask = np.abs(frequencies - center_hz) <= width_hz
    return float(np.sum(np.abs(spectrum[mask]) ** 2))


def _alias_dbc(signal: np.ndarray, sample_rate: int, fundamental_hz: float, alias_hz: float) -> float:
    fundamental_energy = _band_energy(signal, sample_rate, fundamental_hz)
    alias_energy = _band_energy(signal, sample_rate, alias_hz)
    return 10.0 * math.log10(
        (alias_energy + 1e-30) / (fundamental_energy + 1e-30)
    )


@pytest.mark.parametrize("sample_rate", [44_100, 48_000, 96_000])
def test_side_saturation_preserves_length_and_finite_samples(core_dsp_module, sample_rate: int):
    side = (
        _sine(sample_rate, 8_000.0, 1.0, 0.25)
        + _sine(sample_rate, 15_000.0, 1.0, 0.15)
    ).astype(np.float32)

    processed = core_dsp_module.saturate_side(side, sample_rate)

    assert processed.shape == side.shape
    assert processed.dtype == np.float32
    assert np.all(np.isfinite(processed))


def test_side_saturation_alias_is_below_minus_60_dbc_at_44100(core_dsp_module):
    sample_rate = 44_100
    frequency = 15_000.0
    side = _sine(sample_rate, frequency, 2.0, 0.5)

    processed = core_dsp_module.saturate_side(side, sample_rate)

    # Third harmonic: 45 kHz -> folds to 900 Hz at 44.1 kHz.
    alias_dbc = _alias_dbc(processed, sample_rate, frequency, 900.0)

    assert alias_dbc <= -60.0


def test_side_saturation_high_order_alias_is_below_minus_90_dbc_at_96000(core_dsp_module):
    sample_rate = 96_000
    frequency = 18_000.0
    side = _sine(sample_rate, frequency, 2.0, 0.5)

    processed = core_dsp_module.saturate_side(side, sample_rate)

    # Fifth harmonic: 90 kHz -> folds to 6 kHz at 96 kHz if not band-limited.
    alias_dbc = _alias_dbc(processed, sample_rate, frequency, 6_000.0)

    assert alias_dbc <= -90.0
