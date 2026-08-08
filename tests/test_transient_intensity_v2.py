from __future__ import annotations

import numpy as np
import pytest

from src.controllers.core_dsp import restore_transients


def _signal(sample_rate: int = 48_000) -> np.ndarray:
    t = np.arange(sample_rate, dtype=np.float64) / sample_rate
    signal = (
        0.18 * np.sin(2.0 * np.pi * 120.0 * t)
        + 0.07 * np.sin(2.0 * np.pi * 2400.0 * t)
    ).astype(np.float32)
    signal[int(0.20 * sample_rate)] += 0.30
    signal[int(0.55 * sample_rate)] += 0.60
    return signal


def test_transient_amount_zero_is_exact_bypass():
    signal = _signal()
    result = restore_transients(
        signal,
        crest_factor=7.5,
        sample_rate=48_000,
        faccao="red",
        amount=0.0,
        max_boost_override=0.15,
    )
    assert np.array_equal(result, signal)


def test_transient_full_v2_override_matches_legacy_blue():
    signal = _signal()

    legacy = restore_transients(
        signal,
        crest_factor=7.5,
        sample_rate=48_000,
        faccao="blue",
    )
    v2_full = restore_transients(
        signal,
        crest_factor=7.5,
        sample_rate=48_000,
        faccao="red",
        amount=1.0,
        max_boost_override=0.15,
    )

    assert np.array_equal(v2_full, legacy)


def test_transient_half_is_linear_interpolation():
    signal = _signal()

    half = restore_transients(
        signal,
        crest_factor=7.5,
        sample_rate=48_000,
        faccao="blue",
        amount=0.5,
        max_boost_override=0.15,
    )
    full = restore_transients(
        signal,
        crest_factor=7.5,
        sample_rate=48_000,
        faccao="blue",
        amount=1.0,
        max_boost_override=0.15,
    )

    expected = (
        signal.astype(np.float64)
        + 0.5 * (full.astype(np.float64) - signal.astype(np.float64))
    ).astype(np.float32)

    assert np.allclose(half, expected, atol=2e-7, rtol=0.0)


def test_explicit_v2_override_is_independent_of_faction():
    signal = _signal()

    blue = restore_transients(
        signal,
        crest_factor=7.5,
        sample_rate=48_000,
        faccao="blue",
        amount=0.65,
        max_boost_override=0.15,
    )
    red = restore_transients(
        signal,
        crest_factor=7.5,
        sample_rate=48_000,
        faccao="red",
        amount=0.65,
        max_boost_override=0.15,
    )

    assert np.array_equal(blue, red)


@pytest.mark.parametrize("amount", [-0.01, 1.01, float("nan"), float("inf")])
def test_transient_rejects_invalid_amount(amount):
    with pytest.raises(ValueError, match="Transient amount"):
        restore_transients(
            _signal(),
            crest_factor=7.5,
            sample_rate=48_000,
            faccao="blue",
            amount=amount,
            max_boost_override=0.15,
        )


@pytest.mark.parametrize("boost", [-0.01, 0.26])
def test_transient_rejects_invalid_override(boost):
    with pytest.raises(ValueError, match="max boost override"):
        restore_transients(
            _signal(),
            crest_factor=7.5,
            sample_rate=48_000,
            faccao="blue",
            amount=1.0,
            max_boost_override=boost,
        )
