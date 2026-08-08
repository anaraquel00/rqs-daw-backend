from __future__ import annotations

import numpy as np
import pytest
from pedalboard import LowpassFilter, PeakFilter, Pedalboard

from src.controllers.core_dsp import apply_high_cleanup


def _signal(sample_rate: int = 48_000) -> np.ndarray:
    n = sample_rate
    t = np.arange(n, dtype=np.float64) / sample_rate

    return (
        0.15 * np.sin(2.0 * np.pi * 4500.0 * t)
        + 0.12 * np.sin(2.0 * np.pi * 6500.0 * t)
        + 0.08 * np.sin(2.0 * np.pi * 12000.0 * t)
        + 0.05 * np.sin(2.0 * np.pi * 17000.0 * t)
    ).astype(np.float32)


def test_high_cleanup_zero_is_exact_bypass():
    signal = _signal()

    result = apply_high_cleanup(
        signal,
        48_000,
        "blue",
        10.0,
        amount=0.0,
    )

    assert result.dtype == np.float32
    assert np.array_equal(result, signal)


def test_high_cleanup_full_is_not_dry():
    signal = _signal()

    result = apply_high_cleanup(
        signal,
        48_000,
        "blue",
        10.0,
        amount=1.0,
    )

    assert result.shape == signal.shape
    assert np.all(np.isfinite(result))
    assert not np.array_equal(result, signal)


def test_high_cleanup_half_interpolates_between_dry_and_full():
    signal = _signal()

    half = apply_high_cleanup(
        signal,
        48_000,
        "blue",
        10.0,
        amount=0.5,
    )

    full = apply_high_cleanup(
        signal,
        48_000,
        "blue",
        10.0,
        amount=1.0,
    )

    expected = (
        signal.astype(np.float64)
        + 0.5 * (
            full.astype(np.float64)
            - signal.astype(np.float64)
        )
    ).astype(np.float32)

    assert np.allclose(
        half,
        expected,
        atol=2e-7,
        rtol=0.0,
    )


def _legacy_blue_cleanup(signal):
    board = Pedalboard([
        LowpassFilter(cutoff_frequency_hz=15500.0),
        PeakFilter(cutoff_frequency_hz=6500.0, gain_db=-2.0, q=1.5),
        PeakFilter(cutoff_frequency_hz=4500.0, gain_db=-1.0, q=2.0),
    ])
    return board(signal[np.newaxis, :], 48_000)[0]


def _legacy_dense_red_cleanup(signal):
    board = Pedalboard([
        LowpassFilter(cutoff_frequency_hz=13800.0),
        PeakFilter(cutoff_frequency_hz=4500.0, gain_db=-1.5, q=2.0),
        PeakFilter(cutoff_frequency_hz=6500.0, gain_db=-2.5, q=1.5),
        PeakFilter(cutoff_frequency_hz=8000.0, gain_db=-1.5, q=1.0),
    ])
    return board(signal[np.newaxis, :], 48_000)[0]


def test_high_cleanup_full_preserves_legacy_blue_exactly():
    signal = _signal()

    expected = _legacy_blue_cleanup(signal)

    actual = apply_high_cleanup(
        signal,
        48_000,
        "blue",
        10.0,
        amount=1.0,
    )

    assert np.array_equal(actual, expected)


def test_high_cleanup_full_preserves_legacy_dense_red_exactly():
    signal = _signal()

    expected = _legacy_dense_red_cleanup(signal)

    actual = apply_high_cleanup(
        signal,
        48_000,
        "red",
        7.0,
        amount=1.0,
    )

    assert np.array_equal(actual, expected)


@pytest.mark.parametrize(
    "amount",
    [-0.01, 1.01, float("nan"), float("inf")],
)
def test_high_cleanup_rejects_invalid_amount(amount):
    with pytest.raises(ValueError, match="High cleanup amount"):
        apply_high_cleanup(
            _signal(),
            48_000,
            "blue",
            10.0,
            amount=amount,
        )
