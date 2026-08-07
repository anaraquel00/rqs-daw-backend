from __future__ import annotations

import pytest

from src.controllers.mastering_profiles import (
    ATMOSPHERES,
    Atmosphere,
    Destination,
    Platform,
    build_mastering_request,
    intensity_to_character_amount,
    recommended_true_peak_ceiling,
    resolve_delivery_target,
)


@pytest.mark.parametrize(
    ("platform", "target_lufs", "ceiling"),
    [
        (Platform.SPOTIFY, -14.0, -1.2),
        (Platform.APPLE_MUSIC, -16.0, -1.0),
        (Platform.YOUTUBE, -14.0, -1.2),
        (Platform.SOUNDCLOUD, -14.0, -1.2),
        (Platform.GENERIC, -14.0, -1.2),
    ],
)
def test_streaming_platform_defaults(platform, target_lufs, ceiling):
    target = resolve_delivery_target(Destination.STREAMING, platform)
    assert target.target_lufs == target_lufs
    assert target.true_peak_ceiling_dbtp == ceiling


def test_club_default_is_independent_delivery_target():
    target = resolve_delivery_target(Destination.CLUB)
    assert (target.target_lufs, target.min_lufs, target.max_lufs, target.true_peak_ceiling_dbtp) == (-10.5, -11.5, -10.0, -1.0)


def test_festival_default_is_independent_delivery_target():
    target = resolve_delivery_target(Destination.FESTIVAL)
    assert (target.target_lufs, target.min_lufs, target.max_lufs, target.true_peak_ceiling_dbtp) == (-9.5, -10.5, -9.0, -1.0)


def test_streaming_requires_platform():
    with pytest.raises(ValueError, match="requires a platform"):
        resolve_delivery_target(Destination.STREAMING)


@pytest.mark.parametrize("destination", [Destination.CLUB, Destination.FESTIVAL])
def test_non_streaming_rejects_platform(destination):
    with pytest.raises(ValueError, match="only valid"):
        resolve_delivery_target(destination, Platform.SPOTIFY)


@pytest.mark.parametrize(("intensity", "expected"), [(0.0, 0.0), (50.0, 0.5), (100.0, 1.0)])
def test_intensity_smoothstep_endpoints_and_midpoint(intensity, expected):
    assert intensity_to_character_amount(intensity) == pytest.approx(expected)


@pytest.mark.parametrize("intensity", [-1.0, 100.1])
def test_intensity_rejects_out_of_range_values(intensity):
    with pytest.raises(ValueError, match="between 0 and 100"):
        intensity_to_character_amount(intensity)


def test_intensity_does_not_change_loudness_or_true_peak_target():
    low = build_mastering_request(destination=Destination.CLUB, atmosphere=Atmosphere.CLEAR_SKY, intensity_percent=0)
    high = build_mastering_request(destination=Destination.CLUB, atmosphere=Atmosphere.CLEAR_SKY, intensity_percent=100)
    assert low.delivery == high.delivery
    assert low.character_amount == 0.0
    assert high.character_amount == 1.0


def test_atmosphere_does_not_change_delivery_target():
    targets = {
        build_mastering_request(
            destination=Destination.STREAMING,
            platform=Platform.SPOTIFY,
            atmosphere=atmosphere,
            intensity_percent=50,
        ).delivery
        for atmosphere in Atmosphere
    }
    assert len(targets) == 1


@pytest.mark.parametrize("atmosphere", list(Atmosphere))
def test_every_atmosphere_has_product_metadata(atmosphere):
    profile = ATMOSPHERES[atmosphere]
    assert profile.label
    assert profile.subtitle


def test_spotify_loud_custom_target_uses_minus_2_dbtp_safety():
    target = resolve_delivery_target(Destination.STREAMING, Platform.SPOTIFY)
    assert recommended_true_peak_ceiling(target, -11.0) == -2.0


def test_soundcloud_loud_custom_target_uses_minus_2_dbtp_safety():
    target = resolve_delivery_target(Destination.STREAMING, Platform.SOUNDCLOUD)
    assert recommended_true_peak_ceiling(target, -11.0) == -2.0


def test_spotify_standard_target_keeps_default_safety_ceiling():
    target = resolve_delivery_target(Destination.STREAMING, Platform.SPOTIFY)
    assert recommended_true_peak_ceiling(target, -14.0) == -1.2


def test_apple_house_target_does_not_inherit_spotify_soundcloud_rule():
    target = resolve_delivery_target(Destination.STREAMING, Platform.APPLE_MUSIC)
    assert recommended_true_peak_ceiling(target, -11.0) == -1.0


def test_house_guardrails_are_stricter_for_streaming_than_festival():
    streaming = resolve_delivery_target(Destination.STREAMING, Platform.GENERIC)
    festival = resolve_delivery_target(Destination.FESTIVAL)
    assert streaming.min_plr_lu > festival.min_plr_lu
    assert streaming.min_lra_retention > festival.min_lra_retention
    assert streaming.max_crest_loss_db < festival.max_crest_loss_db
