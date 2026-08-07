from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf


def _sine(sample_rate: int, frequency: float, seconds: float, amplitude: float = 0.5) -> np.ndarray:
    sample_count = int(round(sample_rate * seconds))
    t = np.arange(sample_count, dtype=np.float64) / sample_rate
    return (amplitude * np.sin(2.0 * np.pi * frequency * t)).astype(np.float32)


def _rms(signal: np.ndarray) -> float:
    signal = np.asarray(signal, dtype=np.float64)
    return float(np.sqrt(np.mean(np.square(signal)))) if signal.size else 0.0


def _band_energy(signal: np.ndarray, sample_rate: int, center_hz: float, width_hz: float = 50.0) -> float:
    signal = np.asarray(signal, dtype=np.float64)
    window = np.hanning(signal.size)
    spectrum = np.fft.rfft(signal * window)
    frequencies = np.fft.rfftfreq(signal.size, 1.0 / sample_rate)
    mask = np.abs(frequencies - center_hz) <= width_hz
    return float(np.sum(np.abs(spectrum[mask]) ** 2))


def test_split_bands_reconstructs_signal(core_dsp_module):
    sample_rate = 48_000
    rng = np.random.default_rng(20260807)
    signal = rng.normal(0.0, 0.15, sample_rate * 2).astype(np.float32)

    low, mid, high = core_dsp_module.split_bands(signal, sample_rate)
    reconstructed = (
        low.astype(np.float64)
        + mid.astype(np.float64)
        + high.astype(np.float64)
    )

    relative_error = _rms(reconstructed - signal) / _rms(signal)
    relative_error_db = 20.0 * math.log10(max(relative_error, 1e-20))

    assert relative_error_db <= -120.0


def test_saturate_side_preserves_zero_side(core_dsp_module):
    sample_rate = 48_000
    side = np.zeros(sample_rate, dtype=np.float32)

    processed = core_dsp_module.saturate_side(side, sample_rate)

    assert np.max(np.abs(processed)) == 0.0


@pytest.mark.xfail(
    strict=True,
    reason="Known creative-DSP defect: native-rate tanh Side saturation aliases high-frequency harmonics.",
)
def test_saturate_side_high_frequency_alias_is_below_minus_60_dbc(core_dsp_module):
    sample_rate = 48_000
    frequency = 15_000.0
    side = _sine(sample_rate, frequency, 2.0, 0.5)

    processed = core_dsp_module.saturate_side(side, sample_rate)

    # tanh produces a third harmonic at 45 kHz. At 48 kHz processing this folds
    # to 3 kHz if the non-linearity is not adequately oversampled/band-limited.
    alias_frequency = 3_000.0
    fundamental_energy = _band_energy(processed, sample_rate, frequency)
    alias_energy = _band_energy(processed, sample_rate, alias_frequency)

    alias_dbc = 10.0 * math.log10(
        (alias_energy + 1e-30) / (fundamental_energy + 1e-30)
    )

    assert alias_dbc <= -60.0


@pytest.mark.xfail(
    strict=True,
    reason="Known creative-DSP defect: transient gain depends on the file-global maximum derivative.",
)
def test_restore_transients_is_local_and_not_changed_by_later_peak(core_dsp_module):
    sample_rate = 48_000
    first_index = int(0.20 * sample_rate)
    later_index = int(0.80 * sample_rate)

    first_only = np.zeros(sample_rate, dtype=np.float32)
    first_only[first_index] = 0.25

    with_larger_later_peak = first_only.copy()
    with_larger_later_peak[later_index] = 1.0

    first_result = core_dsp_module.restore_transients(
        first_only,
        crest_factor=7.5,
        sample_rate=sample_rate,
        faccao="blue",
    )
    second_result = core_dsp_module.restore_transients(
        with_larger_later_peak,
        crest_factor=7.5,
        sample_rate=sample_rate,
        faccao="blue",
    )

    gain_first_alone = float(first_result[first_index] / first_only[first_index])
    gain_first_with_later = float(
        second_result[first_index] / with_larger_later_peak[first_index]
    )

    assert abs(gain_first_alone - gain_first_with_later) <= 0.01


@pytest.mark.xfail(
    strict=True,
    reason="Known creative-DSP defect: mastering applies an unconditional full-mix NoiseGate.",
)
def test_masterize_does_not_require_full_mix_noise_gate(
    core_dsp_module,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    sample_rate = 48_000
    duration_seconds = 2.0
    signal = _sine(sample_rate, 440.0, duration_seconds, 0.20)
    stereo = np.column_stack((signal, signal))

    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    sf.write(input_path, stereo, sample_rate, format="WAV", subtype="FLOAT")

    def forbidden_noise_gate(*args, **kwargs):
        raise AssertionError(
            "Full-mix NoiseGate must not be instantiated by default mastering."
        )

    monkeypatch.setattr(core_dsp_module, "NoiseGate", forbidden_noise_gate)

    core_dsp_module.masterize(
        str(input_path),
        str(output_path),
        "clear_sky",
        "media",
        False,
    )

    assert output_path.exists()
