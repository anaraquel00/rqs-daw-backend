from __future__ import annotations

import numpy as np
import pytest

from src.controllers.core_dsp import saturate_side


def _side_signal(sample_rate: int = 48_000, duration_s: float = 0.25) -> np.ndarray:
    n = int(sample_rate * duration_s)
    t = np.arange(n, dtype=np.float64) / sample_rate
    signal = (
        0.12 * np.sin(2.0 * np.pi * 1200.0 * t)
        + 0.18 * np.sin(2.0 * np.pi * 7200.0 * t)
        + 0.10 * np.sin(2.0 * np.pi * 11000.0 * t)
    )
    return signal.astype(np.float32)


def test_side_saturation_amount_zero_is_exact_bypass():
    signal = _side_signal()
    result = saturate_side(signal, 48_000, amount=0.0)

    assert result.dtype == np.float32
    assert np.array_equal(result, signal)


def test_side_saturation_amount_one_matches_legacy_default():
    signal = _side_signal()

    legacy_default = saturate_side(signal, 48_000)
    explicit_full = saturate_side(signal, 48_000, amount=1.0)

    assert np.array_equal(explicit_full, legacy_default)


@pytest.mark.parametrize("amount", [-0.01, 1.01, float("nan"), float("inf")])
def test_side_saturation_rejects_invalid_amount(amount):
    with pytest.raises(ValueError, match="amount"):
        saturate_side(_side_signal(), 48_000, amount=amount)
