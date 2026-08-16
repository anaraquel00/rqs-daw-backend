from __future__ import annotations

import numpy as np
import pytest
from pedalboard import Compressor

from src.controllers.core_dsp import apply_high_compression


def _signal(sample_rate: int = 48_000) -> np.ndarray:
    n = sample_rate
    t = np.arange(n, dtype=np.float64) / sample_rate

    envelope = (
        0.45
        + 0.35 * np.sin(2.0 * np.pi * 2.0 * t) ** 2
    )

    return (
        envelope
        * (
            0.18 * np.sin(2.0 * np.pi * 6500.0 * t)
            + 0.12 * np.sin(2.0 * np.pi * 12000.0 * t)
        )
    ).astype(np.float32)


class _CountingProcessor:
    def __init__(self, scale: float):
        self.scale = scale
        self.calls = 0

    def __call__(self, audio, sample_rate):
        self.calls += 1
        return (
            np.asarray(audio, dtype=np.float32)
            * self.scale
        )


def _blue_like_compressor():
    return Compressor(
        threshold_db=-24.0,
        ratio=1.5,
        attack_ms=1.0,
        release_ms=30.0,
    )


def _dense_red_like_compressor():
    return Compressor(
        threshold_db=-24.0,
        ratio=2.25,
        attack_ms=1.0,
        release_ms=20.0,
    )


def test_high_compression_zero_is_exact_bypass_and_does_not_process():
    signal = _signal()
    processor = _CountingProcessor(0.5)

    result = apply_high_compression(
        signal,
        48_000,
        processor,
        amount=0.0,
    )

    assert processor.calls == 0
    assert result.dtype == np.float32
    assert np.array_equal(result, signal)


def test_high_compression_full_preserves_blue_like_legacy_exactly():
    signal = _signal()

    expected = _blue_like_compressor()(
        signal[np.newaxis, :],
        48_000,
    )[0]

    actual = apply_high_compression(
        signal,
        48_000,
        _blue_like_compressor(),
        amount=1.0,
    )

    assert np.array_equal(actual, expected)


def test_high_compression_full_preserves_dense_red_like_legacy_exactly():
    signal = _signal()

    expected = _dense_red_like_compressor()(
        signal[np.newaxis, :],
        48_000,
    )[0]

    actual = apply_high_compression(
        signal,
        48_000,
        _dense_red_like_compressor(),
        amount=1.0,
    )

    assert np.array_equal(actual, expected)


def test_high_compression_half_interpolates_dry_and_wet():
    signal = _signal()
    processor = _CountingProcessor(0.5)

    result = apply_high_compression(
        signal,
        48_000,
        processor,
        amount=0.5,
    )

    expected = (
        signal.astype(np.float64)
        + 0.5
        * (
            signal.astype(np.float64) * 0.5
            - signal.astype(np.float64)
        )
    ).astype(np.float32)

    assert processor.calls == 1
    assert np.array_equal(result, expected)


@pytest.mark.parametrize(
    "amount",
    [-0.01, 1.01, float("nan"), float("inf")],
)
def test_high_compression_rejects_invalid_amount(amount):
    with pytest.raises(
        ValueError,
        match="High compression amount",
    ):
        apply_high_compression(
            _signal(),
            48_000,
            _CountingProcessor(0.5),
            amount=amount,
        )
