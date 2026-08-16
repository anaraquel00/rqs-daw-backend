from __future__ import annotations

import argparse
import json
import sys

from .mastering_profiles import (
    ATMOSPHERES,
    Atmosphere,
    Destination,
    Platform,
    SoundCloudMode,
    resolve_delivery_target,
)
from .mastering_v2 import masterize_v2

RELEASE_ID = "mastering-v2-v1"


def _target_payload(target) -> dict:
    return {
        "target_lufs": target.target_lufs,
        "min_lufs": target.min_lufs,
        "max_lufs": target.max_lufs,
        "true_peak_ceiling_dbtp": target.true_peak_ceiling_dbtp,
        "min_plr_lu": target.min_plr_lu,
        "min_lra_retention": target.min_lra_retention,
        "max_crest_loss_db": target.max_crest_loss_db,
        "policy_source": target.policy_source,
    }


def build_capabilities() -> dict:
    streaming = {}
    for platform in Platform:
        modes = [SoundCloudMode.STANDARD]
        if platform is Platform.SOUNDCLOUD:
            modes.append(SoundCloudMode.LOUD)
        streaming[platform.value] = {
            mode.value: _target_payload(
                resolve_delivery_target(
                    Destination.STREAMING,
                    platform,
                    soundcloud_mode=mode,
                )
            )
            for mode in modes
        }

    return {
        "engine": "rqs-core-mastering-v2",
        "release": RELEASE_ID,
        "preview_seconds": 15,
        "intensity": {"min": 0, "max": 100, "step": 1, "default": 50},
        "atmospheres": [
            {
                "id": atmosphere.value,
                "label": ATMOSPHERES[atmosphere].label,
                "subtitle": ATMOSPHERES[atmosphere].subtitle,
            }
            for atmosphere in Atmosphere
        ],
        "destinations": {
            Destination.STREAMING.value: {
                "platform_required": True,
                "platforms": streaming,
            },
            Destination.CLUB.value: {
                "platform_required": False,
                "target": _target_payload(resolve_delivery_target(Destination.CLUB)),
            },
            Destination.FESTIVAL.value: {
                "platform_required": False,
                "target": _target_payload(resolve_delivery_target(Destination.FESTIVAL)),
            },
        },
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rqs-mastering-v2")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("capabilities")

    render = subparsers.add_parser("render")
    render.add_argument("--input", required=True)
    render.add_argument("--output", required=True)
    render.add_argument("--destination", required=True, choices=[item.value for item in Destination])
    render.add_argument("--platform", choices=[item.value for item in Platform])
    render.add_argument("--atmosphere", required=True, choices=[item.value for item in Atmosphere])
    render.add_argument("--intensity-percent", required=True, type=float)
    render.add_argument("--requested-lufs", type=float)
    render.add_argument(
        "--soundcloud-mode",
        default=SoundCloudMode.STANDARD.value,
        choices=[item.value for item in SoundCloudMode],
    )
    render.add_argument("--preview", action="store_true")
    render.add_argument("--preview-start-seconds", type=float)
    return parser


def run_render(args: argparse.Namespace) -> None:
    kwargs = {
        "destination": args.destination,
        "platform": args.platform,
        "atmosphere": args.atmosphere,
        "intensity_percent": args.intensity_percent,
        "requested_lufs": args.requested_lufs,
        "soundcloud_mode": args.soundcloud_mode,
        "is_preview": args.preview,
    }
    preview_start_seconds = getattr(args, "preview_start_seconds", None)
    if preview_start_seconds is not None:
        kwargs["preview_start_seconds"] = preview_start_seconds

    masterize_v2(args.input, args.output, **kwargs)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "capabilities":
            print(json.dumps(build_capabilities(), separators=(",", ":"), sort_keys=True))
            return 0

        run_render(args)
        print("V2_RENDER_SUCCESS")
        return 0
    except ValueError as exc:
        print(json.dumps({"error": "validation_error", "detail": str(exc)}), file=sys.stderr)
        return 2
    except Exception as exc:
        print(json.dumps({"error": "processing_error", "detail": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
