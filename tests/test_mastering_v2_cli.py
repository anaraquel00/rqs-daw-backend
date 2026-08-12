from __future__ import annotations

from argparse import Namespace

from src.controllers import mastering_v2_cli


def test_capabilities_expose_validated_v2_contract():
    payload = mastering_v2_cli.build_capabilities()

    assert payload["release"] == "mastering-v2-v1"
    assert payload["preview_seconds"] == 15
    assert payload["intensity"] == {"min": 0, "max": 100, "step": 1, "default": 50}
    assert {item["id"] for item in payload["atmospheres"]} == {
        "clear_sky", "thunder", "sunroof", "aurora"
    }
    assert set(payload["destinations"]) == {"streaming", "club", "festival"}
    assert set(payload["destinations"]["streaming"]["platforms"]) == {
        "spotify", "apple_music", "youtube", "soundcloud", "generic"
    }
    assert set(payload["destinations"]["streaming"]["platforms"]["soundcloud"]) == {
        "standard", "loud"
    }


def test_run_render_forwards_full_v2_request(monkeypatch):
    captured = {}

    def fake_masterize_v2(input_path, output_path, **kwargs):
        captured["input"] = input_path
        captured["output"] = output_path
        captured["kwargs"] = kwargs

    monkeypatch.setattr(mastering_v2_cli, "masterize_v2", fake_masterize_v2)

    args = Namespace(
        input="input.wav",
        output="output.wav",
        destination="streaming",
        platform="soundcloud",
        atmosphere="aurora",
        intensity_percent=73.0,
        requested_lufs=-11.0,
        soundcloud_mode="loud",
        preview=True,
    )
    mastering_v2_cli.run_render(args)

    assert captured == {
        "input": "input.wav",
        "output": "output.wav",
        "kwargs": {
            "destination": "streaming",
            "platform": "soundcloud",
            "atmosphere": "aurora",
            "intensity_percent": 73.0,
            "requested_lufs": -11.0,
            "soundcloud_mode": "loud",
            "is_preview": True,
        },
    }
