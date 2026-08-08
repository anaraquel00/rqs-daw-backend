from __future__ import annotations

import pytest

from src.controllers.mastering_atmospheres import (
    ATMOSPHERE_INTENTS_V1,
    Direction,
    get_atmosphere_intent,
    scale_atmosphere_intent,
)
from src.controllers.mastering_profiles import Atmosphere, build_mastering_request


def test_every_atmosphere_has_v1_intent():
    assert set(ATMOSPHERE_INTENTS_V1) == set(Atmosphere)


@pytest.mark.parametrize("atmosphere", list(Atmosphere))
def test_zero_intensity_means_zero_creative_amount(atmosphere):
    scaled = scale_atmosphere_intent(atmosphere, 0)
    assert scaled.character_amount == 0.0
    assert scaled.low_end == 0.0
    assert scaled.midrange == 0.0
    assert scaled.presence == 0.0
    assert scaled.air == 0.0
    assert scaled.stereo_width == 0.0
    assert scaled.transients == 0.0
    assert scaled.max_eq_move_db == 0.0
    assert scaled.max_stereo_move_db == 0.0
    assert scaled.max_transient_move_db == 0.0
    assert scaled.max_dynamic_move_db == 0.0


@pytest.mark.parametrize("atmosphere", list(Atmosphere))
def test_hundred_percent_means_full_character(atmosphere):
    scaled = scale_atmosphere_intent(atmosphere, 100)
    intent = get_atmosphere_intent(atmosphere)
    assert scaled.character_amount == 1.0
    assert scaled.low_end == float(intent.low_end)
    assert scaled.midrange == float(intent.midrange)
    assert scaled.presence == float(intent.presence)
    assert scaled.air == float(intent.air)
    assert scaled.stereo_width == float(intent.stereo_width)
    assert scaled.transients == float(intent.transients)
    assert scaled.max_eq_move_db == intent.max_eq_move_db


@pytest.mark.parametrize("atmosphere", list(Atmosphere))
def test_fifty_percent_is_half_character_via_existing_smoothstep(atmosphere):
    scaled = scale_atmosphere_intent(atmosphere, 50)
    assert scaled.character_amount == 0.5


def test_thunder_matches_first_reference_direction():
    intent = get_atmosphere_intent("thunder")
    assert intent.low_end is Direction.ENHANCE
    assert intent.midrange is Direction.REDUCE
    assert intent.stereo_width is Direction.REDUCE


def test_sunroof_matches_first_reference_direction():
    intent = get_atmosphere_intent("sunroof")
    assert intent.low_end is Direction.ENHANCE
    assert intent.presence is Direction.ENHANCE
    assert intent.air is Direction.ENHANCE


def test_aurora_matches_first_reference_direction():
    intent = get_atmosphere_intent("aurora")
    assert intent.low_end is Direction.PRESERVE
    assert intent.air is Direction.ENHANCE
    assert intent.stereo_width is Direction.PRESERVE


def test_clear_sky_matches_first_reference_direction():
    intent = get_atmosphere_intent("clear_sky")
    assert intent.midrange is Direction.REDUCE
    assert intent.presence is Direction.ENHANCE
    assert intent.stereo_width is Direction.PRESERVE


@pytest.mark.parametrize("atmosphere", list(Atmosphere))
def test_v1_is_marked_provisional_single_track_reference(atmosphere):
    intent = get_atmosphere_intent(atmosphere)
    assert intent.evidence_status == "provisional_single_track_soundcloud_100pct"


def test_atmosphere_intensity_still_does_not_change_delivery_target():
    low = build_mastering_request(
        destination="club",
        atmosphere="thunder",
        intensity_percent=0,
        requested_lufs=-11.0,
    )
    high = build_mastering_request(
        destination="club",
        atmosphere="thunder",
        intensity_percent=100,
        requested_lufs=-11.0,
    )
    assert low.target_lufs == high.target_lufs == -11.0
    assert low.delivery.true_peak_ceiling_dbtp == high.delivery.true_peak_ceiling_dbtp


@pytest.mark.parametrize("atmosphere", list(Atmosphere))
def test_safety_caps_are_conservative_and_positive(atmosphere):
    intent = get_atmosphere_intent(atmosphere)
    assert 0.0 < intent.max_eq_move_db <= 2.0
    assert 0.0 < intent.max_stereo_move_db <= 1.0
    assert 0.0 < intent.max_transient_move_db <= 1.0
    assert 0.0 < intent.max_dynamic_move_db <= 2.0
