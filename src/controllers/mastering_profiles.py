from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Destination(str, Enum):
    STREAMING = "streaming"
    CLUB = "club"
    FESTIVAL = "festival"


class Platform(str, Enum):
    SPOTIFY = "spotify"
    APPLE_MUSIC = "apple_music"
    YOUTUBE = "youtube"
    SOUNDCLOUD = "soundcloud"
    GENERIC = "generic"


class Atmosphere(str, Enum):
    THUNDER = "thunder"
    SUNROOF = "sunroof"
    AURORA = "aurora"
    CLEAR_SKY = "clear_sky"


class SoundCloudMode(str, Enum):
    STANDARD = "standard"
    LOUD = "loud"


@dataclass(frozen=True)
class DeliveryTarget:
    destination: Destination
    platform: Platform | None
    target_lufs: float
    min_lufs: float
    max_lufs: float
    true_peak_ceiling_dbtp: float
    min_plr_lu: float
    min_lra_retention: float
    max_crest_loss_db: float
    policy_source: str


@dataclass(frozen=True)
class AtmosphereProfile:
    atmosphere: Atmosphere
    label: str
    subtitle: str


@dataclass(frozen=True)
class MasteringRequest:
    delivery: DeliveryTarget
    atmosphere: AtmosphereProfile
    intensity_percent: float
    character_amount: float
    target_lufs: float


ATMOSPHERES = {
    Atmosphere.CLEAR_SKY: AtmosphereProfile(Atmosphere.CLEAR_SKY, "Clear Sky", "Transparent & Balanced"),
    Atmosphere.THUNDER: AtmosphereProfile(Atmosphere.THUNDER, "Thunder", "Punch & Low-End Impact"),
    Atmosphere.SUNROOF: AtmosphereProfile(Atmosphere.SUNROOF, "Sunroof", "Bright & Open"),
    Atmosphere.AURORA: AtmosphereProfile(Atmosphere.AURORA, "Aurora", "Warm & Cinematic"),
}


_STREAMING_TARGETS = {
    Platform.SPOTIFY: DeliveryTarget(
        Destination.STREAMING, Platform.SPOTIFY, -14.0, -14.5, -13.5, -1.2,
        9.0, 0.85, 1.5, "spotify_official_plus_krismig_safety_margin"
    ),
    Platform.APPLE_MUSIC: DeliveryTarget(
        Destination.STREAMING, Platform.APPLE_MUSIC, -16.0, -16.5, -14.0, -1.0,
        10.0, 0.85, 1.5, "krismig_house_target_apple_quality"
    ),
    Platform.YOUTUBE: DeliveryTarget(
        Destination.STREAMING, Platform.YOUTUBE, -14.0, -15.0, -13.0, -1.2,
        9.0, 0.85, 1.5, "krismig_house_target_youtube"
    ),
    Platform.SOUNDCLOUD: DeliveryTarget(
        Destination.STREAMING, Platform.SOUNDCLOUD, -14.0, -14.5, -13.5, -1.2,
        9.0, 0.85, 1.5, "soundcloud_official_plus_krismig_safety_margin"
    ),
    Platform.GENERIC: DeliveryTarget(
        Destination.STREAMING, Platform.GENERIC, -14.0, -15.0, -13.0, -1.2,
        9.0, 0.85, 1.5, "krismig_generic_streaming"
    ),
}


_SOUNDCLOUD_LOUD_TARGET = DeliveryTarget(
    Destination.STREAMING, Platform.SOUNDCLOUD, -11.0, -12.0, -10.0, -2.0,
    8.5, 0.75, 2.0, "krismig_soundcloud_loud_v1"
)

_NON_STREAMING_TARGETS = {
    Destination.CLUB: DeliveryTarget(
        Destination.CLUB, None, -10.5, -11.5, -10.0, -1.0,
        8.5, 0.75, 2.0, "krismig_club_v1"
    ),
    Destination.FESTIVAL: DeliveryTarget(
        Destination.FESTIVAL, None, -9.5, -10.5, -9.0, -1.0,
        7.5, 0.65, 3.0, "krismig_festival_v1"
    ),
}


def resolve_delivery_target(
    destination: Destination | str,
    platform: Platform | str | None = None,
    soundcloud_mode: SoundCloudMode | str = SoundCloudMode.STANDARD,
) -> DeliveryTarget:
    destination = Destination(destination)
    soundcloud_mode = SoundCloudMode(soundcloud_mode)
    if destination is Destination.STREAMING:
        if platform is None:
            raise ValueError("Streaming requires a platform.")
        platform = Platform(platform)
        if platform is Platform.SOUNDCLOUD:
            if soundcloud_mode is SoundCloudMode.LOUD:
                return _SOUNDCLOUD_LOUD_TARGET
            return _STREAMING_TARGETS[platform]
        if soundcloud_mode is not SoundCloudMode.STANDARD:
            raise ValueError("SoundCloud mode is only valid for SoundCloud.")
        return _STREAMING_TARGETS[platform]
    if platform is not None:
        raise ValueError("Platform is only valid for the streaming destination.")
    if soundcloud_mode is not SoundCloudMode.STANDARD:
        raise ValueError("SoundCloud mode is only valid for SoundCloud.")
    return _NON_STREAMING_TARGETS[destination]


def resolve_requested_lufs(delivery: DeliveryTarget, requested_lufs: float | None = None) -> float:
    if requested_lufs is None:
        return delivery.target_lufs
    value = float(requested_lufs)
    if not delivery.min_lufs <= value <= delivery.max_lufs:
        raise ValueError(
            f"Requested LUFS {value:.2f} is outside allowed range "            f"{delivery.min_lufs:.2f}..{delivery.max_lufs:.2f}."
        )
    return value


def intensity_to_character_amount(intensity_percent: float) -> float:
    value = float(intensity_percent)
    if not 0.0 <= value <= 100.0:
        raise ValueError("Intensity must be between 0 and 100 percent.")
    x = value / 100.0
    return (3.0 * x * x) - (2.0 * x * x * x)


def recommended_true_peak_ceiling(delivery: DeliveryTarget, requested_lufs: float | None = None) -> float:
    target_lufs = delivery.target_lufs if requested_lufs is None else float(requested_lufs)
    if (
        delivery.destination is Destination.STREAMING
        and delivery.platform in {Platform.SPOTIFY, Platform.SOUNDCLOUD}
        and target_lufs > -14.0
    ):
        return min(delivery.true_peak_ceiling_dbtp, -2.0)
    return delivery.true_peak_ceiling_dbtp


def build_mastering_request(
    *,
    destination: Destination | str,
    atmosphere: Atmosphere | str,
    intensity_percent: float,
    platform: Platform | str | None = None,
    requested_lufs: float | None = None,
    soundcloud_mode: SoundCloudMode | str = SoundCloudMode.STANDARD,
) -> MasteringRequest:
    delivery = resolve_delivery_target(destination, platform, soundcloud_mode=soundcloud_mode)
    atmosphere_profile = ATMOSPHERES[Atmosphere(atmosphere)]
    target_lufs = resolve_requested_lufs(delivery, requested_lufs)
    return MasteringRequest(
        delivery=delivery,
        atmosphere=atmosphere_profile,
        intensity_percent=float(intensity_percent),
        character_amount=intensity_to_character_amount(intensity_percent),
        target_lufs=target_lufs,
    )
