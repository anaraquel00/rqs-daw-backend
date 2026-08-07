from __future__ import annotations

import pytest
from src.controllers import mastering_v2
from src.controllers.mastering_profiles import SoundCloudMode


@pytest.mark.parametrize("target", [-11.5, -11.0, -10.5, -10.0])
def test_club_user_range(target):
    p = mastering_v2.build_render_plan_v2(
        destination="club", atmosphere="clear_sky",
        intensity_percent=50, requested_lufs=target)
    assert p.target_lufs == target
    assert p.true_peak_ceiling_dbtp == -1.0


@pytest.mark.parametrize("target", [-11.6, -9.9])
def test_club_rejects_outside_range(target):
    with pytest.raises(ValueError, match="outside allowed range"):
        mastering_v2.build_render_plan_v2(
            destination="club", atmosphere="clear_sky",
            intensity_percent=50, requested_lufs=target)


@pytest.mark.parametrize("target", [-10.5, -10.0, -9.5, -9.0])
def test_festival_user_range(target):
    p = mastering_v2.build_render_plan_v2(
        destination="festival", atmosphere="clear_sky",
        intensity_percent=50, requested_lufs=target)
    assert p.target_lufs == target
    assert p.true_peak_ceiling_dbtp == -1.0


def test_soundcloud_standard_stays_minus_14():
    p = mastering_v2.build_render_plan_v2(
        destination="streaming", platform="soundcloud",
        soundcloud_mode="standard", atmosphere="clear_sky",
        intensity_percent=50)
    assert (p.target_lufs, p.true_peak_ceiling_dbtp) == (-14.0, -1.2)


@pytest.mark.parametrize("target", [-12.0, -11.5, -11.0, -10.5, -10.0])
def test_soundcloud_loud_range(target):
    p = mastering_v2.build_render_plan_v2(
        destination="streaming", platform="soundcloud",
        soundcloud_mode="loud", atmosphere="clear_sky",
        intensity_percent=50, requested_lufs=target)
    assert p.target_lufs == target
    assert p.true_peak_ceiling_dbtp == -2.0
    assert p.request.delivery.policy_source == "krismig_soundcloud_loud_v1"


def test_soundcloud_loud_default():
    p = mastering_v2.build_render_plan_v2(
        destination="streaming", platform="soundcloud",
        soundcloud_mode="loud", atmosphere="clear_sky",
        intensity_percent=50)
    assert (p.target_lufs, p.true_peak_ceiling_dbtp) == (-11.0, -2.0)


def test_soundcloud_loud_rejected_for_spotify():
    with pytest.raises(ValueError, match="only valid for SoundCloud"):
        mastering_v2.build_render_plan_v2(
            destination="streaming", platform="spotify",
            soundcloud_mode=SoundCloudMode.LOUD,
            atmosphere="clear_sky", intensity_percent=50)


def _capture(monkeypatch):
    calls = []
    def fake(*args):
        calls.append(args)
        return "ok"
    monkeypatch.setattr(mastering_v2.core_dsp, "masterize", fake)
    return calls


def test_routes_custom_club(monkeypatch):
    calls = _capture(monkeypatch)
    mastering_v2.masterize_v2(
        "in", "out", destination="club",
        atmosphere="clear_sky", intensity_percent=50,
        requested_lufs=-11.0)
    assert calls[0][-2:] == (-11.0, -1.0)


def test_routes_soundcloud_loud(monkeypatch):
    calls = _capture(monkeypatch)
    mastering_v2.masterize_v2(
        "in", "out", destination="streaming", platform="soundcloud",
        soundcloud_mode="loud", atmosphere="clear_sky",
        intensity_percent=50, requested_lufs=-10.5)
    assert calls[0][-2:] == (-10.5, -2.0)
