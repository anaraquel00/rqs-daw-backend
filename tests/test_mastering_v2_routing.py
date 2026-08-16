from __future__ import annotations

import inspect
import pytest
from src.controllers import core_dsp, mastering_v2
from src.controllers.mastering_profiles import Atmosphere, Destination, Platform

def test_spotify_plan():
    p = mastering_v2.build_render_plan_v2(
        destination="streaming", platform="spotify",
        atmosphere="thunder", intensity_percent=75)
    assert (p.target_lufs, p.true_peak_ceiling_dbtp) == (-14.0, -1.2)
    assert (p.legacy_dsp_style, p.legacy_dsp_intensity) == ("clear_sky", "media")
    assert p.legacy_dsp_faction == "blue"

def test_club_plan():
    p = mastering_v2.build_render_plan_v2(
        destination="club", atmosphere="aurora", intensity_percent=25)
    assert (p.target_lufs, p.true_peak_ceiling_dbtp) == (-10.5, -1.0)

def test_festival_plan():
    p = mastering_v2.build_render_plan_v2(
        destination="festival", atmosphere="sunroof", intensity_percent=50)
    assert (p.target_lufs, p.true_peak_ceiling_dbtp) == (-9.5, -1.0)

@pytest.mark.parametrize("value", [0.0, 50.0, 100.0])
def test_intensity_is_metadata_only_for_now(value):
    p = mastering_v2.build_render_plan_v2(
        destination="club", atmosphere="clear_sky", intensity_percent=value)
    assert p.request.intensity_percent == value
    assert p.legacy_dsp_intensity == "media"
    assert p.target_lufs == -10.5

@pytest.mark.parametrize("atmosphere", list(Atmosphere))
def test_atmosphere_is_metadata_only_for_now(atmosphere):
    p = mastering_v2.build_render_plan_v2(
        destination="streaming", platform="spotify",
        atmosphere=atmosphere, intensity_percent=50)
    assert p.request.atmosphere.atmosphere is atmosphere
    assert p.legacy_dsp_style == "clear_sky"
    assert p.target_lufs == -14.0

def _capture(monkeypatch):
    calls = []
    def fake(*args, **kwargs):
        assert kwargs == {
            "high_cleanup_amount": 0.0,
            "high_compression_amount": 0.0,
            "side_highpass_cutoff_override": 100.0,
            "mid_compression_enabled": False,
            "side_compression_enabled": False,
            "legacy_faction_override": "blue",
        }
        calls.append(args)
        return "ok"
    monkeypatch.setattr(mastering_v2.core_dsp, "masterize", fake)
    return calls

def test_routes_spotify(monkeypatch):
    c = _capture(monkeypatch)
    assert mastering_v2.masterize_v2(
        "in", "out", destination="streaming", platform="spotify",
        atmosphere="thunder", intensity_percent=90) == "ok"
    assert c[0][:-4] == ("in", "out", "clear_sky", "media", False, -14.0, -1.2)
    assert abs(c[0][-4] - 0.972) < 1e-12
    assert abs(c[0][-3] - 0.972) < 1e-12
    assert abs(c[0][-2] - 0.15) < 1e-12
    assert abs(c[0][-1] - 15000.0) < 1e-12

def test_routes_club(monkeypatch):
    c = _capture(monkeypatch)
    mastering_v2.masterize_v2(
        "in", "out", destination="club",
        atmosphere="aurora", intensity_percent=10)
    assert c[0][-6:-4] == (-10.5, -1.0)
    assert abs(c[0][-4] - 0.028) < 1e-12
    assert abs(c[0][-3] - 0.028) < 1e-12
    assert abs(c[0][-2] - 0.15) < 1e-12
    assert abs(c[0][-1] - 15000.0) < 1e-12

def test_routes_festival(monkeypatch):
    c = _capture(monkeypatch)
    mastering_v2.masterize_v2(
        "in", "out", destination="festival",
        atmosphere="sunroof", intensity_percent=50)
    assert c[0][-6:-4] == (-9.5, -1.0)
    assert abs(c[0][-4] - 0.5) < 1e-12
    assert abs(c[0][-3] - 0.5) < 1e-12
    assert abs(c[0][-2] - 0.15) < 1e-12
    assert abs(c[0][-1] - 15000.0) < 1e-12

def test_routes_preview(monkeypatch):
    preview_source = "preview-segment.wav"

    monkeypatch.setattr(
        mastering_v2,
        "_create_preview_source_segment",
        lambda input_path: preview_source,
    )
    monkeypatch.setattr(
        mastering_v2,
        "_cleanup_preview_source_segment",
        lambda path: None,
    )

    c = _capture(monkeypatch)
    mastering_v2.masterize_v2(
        "in", "out", destination="club",
        atmosphere="clear_sky", intensity_percent=50, is_preview=True)

    assert c[0][0] == preview_source
    assert c[0][4] is True

def test_legacy_signature_stays_compatible():
    p = list(inspect.signature(core_dsp.masterize).parameters.values())
    assert [x.name for x in p[:5]] == [
        "input_path", "output_path", "estilo", "intensidade", "is_preview"]
    assert p[4].default is False
    assert p[5].name == "target_lufs_override" and p[5].default is None
    assert p[6].name == "limiter_ceiling_override" and p[6].default is None
