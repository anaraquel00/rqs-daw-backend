from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from src.controllers import mastering_v2


def test_preview_source_segment_is_center_15_seconds_and_float(tmp_path):
    sample_rate = 1000
    total_frames = 20000
    source = tmp_path / "source.wav"

    left = np.linspace(-0.8, 0.8, total_frames, dtype=np.float32)
    right = np.linspace(0.7, -0.7, total_frames, dtype=np.float32)
    audio = np.column_stack((left, right))
    sf.write(source, audio, sample_rate, subtype="PCM_16")

    expected, _ = sf.read(
        source,
        start=2500,
        frames=15000,
        dtype="float32",
        always_2d=True,
    )

    segment = mastering_v2._create_preview_source_segment(source)
    try:
        actual, actual_sr = sf.read(
            segment,
            dtype="float32",
            always_2d=True,
        )
        info = sf.info(segment)

        assert actual_sr == sample_rate
        assert actual.shape == (15000, 2)
        assert np.array_equal(actual, expected)
        assert info.subtype == "FLOAT"
    finally:
        mastering_v2._cleanup_preview_source_segment(segment)

    assert not segment.exists()

def test_preview_source_segment_honors_explicit_start_and_keeps_exact_15_seconds(tmp_path):
    sample_rate = 1000
    total_frames = 30000
    source = tmp_path / "source_explicit.wav"

    left = np.linspace(-0.95, 0.95, total_frames, dtype=np.float32)
    right = np.linspace(0.85, -0.85, total_frames, dtype=np.float32)
    audio = np.column_stack((left, right))
    sf.write(source, audio, sample_rate, subtype="PCM_16")

    expected, _ = sf.read(
        source,
        start=7000,
        frames=15000,
        dtype="float32",
        always_2d=True,
    )

    segment = mastering_v2._create_preview_source_segment(source, 7.0)
    try:
        actual, actual_sr = sf.read(segment, dtype="float32", always_2d=True)
        assert actual_sr == sample_rate
        assert actual.shape == (15000, 2)
        assert np.array_equal(actual, expected)
    finally:
        mastering_v2._cleanup_preview_source_segment(segment)

    assert not segment.exists()

def test_zero_intensity_preview_uses_delivery_only_on_pretrimmed_source(monkeypatch):
    preview_source = Path("preview-segment.wav")
    core_calls = []
    loudness_calls = []
    cleanup_calls = []

    monkeypatch.setattr(
        mastering_v2,
        "_create_preview_source_segment",
        lambda input_path: preview_source,
    )
    monkeypatch.setattr(
        mastering_v2,
        "_cleanup_preview_source_segment",
        lambda path: cleanup_calls.append(path),
    )

    def fake_masterize(*args, **kwargs):
        core_calls.append((args, kwargs))
        return "core"

    def fake_finalize(input_path, output_path, **kwargs):
        loudness_calls.append((input_path, output_path, kwargs))
        return "delivery"

    monkeypatch.setattr(mastering_v2.core_dsp, "masterize", fake_masterize)
    monkeypatch.setattr(mastering_v2, "finalize_loudness", fake_finalize)

    result = mastering_v2.masterize_v2(
        "full-source.wav",
        "preview-output.wav",
        destination="streaming",
        platform="spotify",
        atmosphere="clear_sky",
        intensity_percent=0,
        is_preview=True,
    )

    assert result == "delivery"
    assert core_calls == []
    assert len(loudness_calls) == 1
    assert loudness_calls[0][0] == str(preview_source)
    assert cleanup_calls == [preview_source]


def test_nonzero_preview_preserves_core_preview_semantics_on_pretrimmed_source(monkeypatch):
    preview_source = Path("preview-segment.wav")
    captured = {}
    cleanup_calls = []

    monkeypatch.setattr(
        mastering_v2,
        "_create_preview_source_segment",
        lambda input_path: preview_source,
    )
    monkeypatch.setattr(
        mastering_v2,
        "_cleanup_preview_source_segment",
        lambda path: cleanup_calls.append(path),
    )

    def fake_masterize(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return "preview"

    monkeypatch.setattr(mastering_v2.core_dsp, "masterize", fake_masterize)

    result = mastering_v2.masterize_v2(
        "full-source.wav",
        "preview-output.wav",
        destination="streaming",
        platform="spotify",
        atmosphere="clear_sky",
        intensity_percent=50,
        is_preview=True,
    )

    assert result == "preview"
    assert captured["args"][0] == str(preview_source)
    assert captured["args"][4] is True
    assert captured["kwargs"] == {
        "high_cleanup_amount": 0.0,
        "high_compression_amount": 0.0,
        "side_highpass_cutoff_override": 100.0,
        "mid_compression_enabled": False,
        "side_compression_enabled": False,
        "legacy_faction_override": "blue",
    }
    assert cleanup_calls == [preview_source]


def test_final_render_does_not_create_preview_segment(monkeypatch):
    preview_calls = []

    monkeypatch.setattr(
        mastering_v2,
        "_create_preview_source_segment",
        lambda input_path: preview_calls.append(input_path),
    )
    monkeypatch.setattr(
        mastering_v2,
        "finalize_loudness",
        lambda *args, **kwargs: "delivery",
    )

    result = mastering_v2.masterize_v2(
        "full-source.wav",
        "output.wav",
        destination="streaming",
        platform="spotify",
        atmosphere="clear_sky",
        intensity_percent=0,
        is_preview=False,
    )

    assert result == "delivery"
    assert preview_calls == []
