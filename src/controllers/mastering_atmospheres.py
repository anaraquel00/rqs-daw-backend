from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from .mastering_profiles import Atmosphere, intensity_to_character_amount


class Direction(IntEnum):
    REDUCE = -1
    PRESERVE = 0
    ENHANCE = 1


@dataclass(frozen=True)
class AtmosphereIntent:
    atmosphere: Atmosphere
    low_end: Direction
    midrange: Direction
    presence: Direction
    air: Direction
    stereo_width: Direction
    transients: Direction
    max_eq_move_db: float
    max_stereo_move_db: float
    max_transient_move_db: float
    max_dynamic_move_db: float
    evidence_status: str


@dataclass(frozen=True)
class ScaledAtmosphereIntent:
    atmosphere: Atmosphere
    character_amount: float
    low_end: float
    midrange: float
    presence: float
    air: float
    stereo_width: float
    transients: float
    max_eq_move_db: float
    max_stereo_move_db: float
    max_transient_move_db: float
    max_dynamic_move_db: float


# V1 is intentionally directional, not a fixed EQ/compressor preset.
# The first external reference is HUSARIA mastered by SoundCloud at 100%.
# Exact SoundCloud dB changes are NOT copied because they are source-dependent.
ATMOSPHERE_INTENTS_V1 = {
    Atmosphere.THUNDER: AtmosphereIntent(
        atmosphere=Atmosphere.THUNDER,
        low_end=Direction.ENHANCE,
        midrange=Direction.REDUCE,
        presence=Direction.PRESERVE,
        air=Direction.ENHANCE,
        stereo_width=Direction.REDUCE,
        transients=Direction.PRESERVE,
        max_eq_move_db=2.0,
        max_stereo_move_db=1.0,
        max_transient_move_db=1.0,
        max_dynamic_move_db=2.0,
        evidence_status="provisional_single_track_soundcloud_100pct",
    ),
    Atmosphere.SUNROOF: AtmosphereIntent(
        atmosphere=Atmosphere.SUNROOF,
        low_end=Direction.ENHANCE,
        midrange=Direction.REDUCE,
        presence=Direction.ENHANCE,
        air=Direction.ENHANCE,
        stereo_width=Direction.REDUCE,
        transients=Direction.PRESERVE,
        max_eq_move_db=2.0,
        max_stereo_move_db=1.0,
        max_transient_move_db=1.0,
        max_dynamic_move_db=2.0,
        evidence_status="provisional_single_track_soundcloud_100pct",
    ),
    Atmosphere.AURORA: AtmosphereIntent(
        atmosphere=Atmosphere.AURORA,
        low_end=Direction.PRESERVE,
        midrange=Direction.REDUCE,
        presence=Direction.ENHANCE,
        air=Direction.ENHANCE,
        stereo_width=Direction.PRESERVE,
        transients=Direction.ENHANCE,
        max_eq_move_db=2.0,
        max_stereo_move_db=1.0,
        max_transient_move_db=1.0,
        max_dynamic_move_db=2.0,
        evidence_status="provisional_single_track_soundcloud_100pct",
    ),
    Atmosphere.CLEAR_SKY: AtmosphereIntent(
        atmosphere=Atmosphere.CLEAR_SKY,
        low_end=Direction.PRESERVE,
        midrange=Direction.REDUCE,
        presence=Direction.ENHANCE,
        air=Direction.ENHANCE,
        stereo_width=Direction.PRESERVE,
        transients=Direction.ENHANCE,
        max_eq_move_db=2.0,
        max_stereo_move_db=1.0,
        max_transient_move_db=1.0,
        max_dynamic_move_db=2.0,
        evidence_status="provisional_single_track_soundcloud_100pct",
    ),
}


def get_atmosphere_intent(atmosphere: Atmosphere | str) -> AtmosphereIntent:
    return ATMOSPHERE_INTENTS_V1[Atmosphere(atmosphere)]


def scale_atmosphere_intent(
    atmosphere: Atmosphere | str,
    intensity_percent: float,
) -> ScaledAtmosphereIntent:
    intent = get_atmosphere_intent(atmosphere)
    amount = intensity_to_character_amount(intensity_percent)

    return ScaledAtmosphereIntent(
        atmosphere=intent.atmosphere,
        character_amount=amount,
        low_end=float(intent.low_end) * amount,
        midrange=float(intent.midrange) * amount,
        presence=float(intent.presence) * amount,
        air=float(intent.air) * amount,
        stereo_width=float(intent.stereo_width) * amount,
        transients=float(intent.transients) * amount,
        max_eq_move_db=intent.max_eq_move_db * amount,
        max_stereo_move_db=intent.max_stereo_move_db * amount,
        max_transient_move_db=intent.max_transient_move_db * amount,
        max_dynamic_move_db=intent.max_dynamic_move_db * amount,
    )
