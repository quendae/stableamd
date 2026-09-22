from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "backend"))

import stableamd_v03_image_to_svg as image_to_svg


def test_image_to_svg_request_defaults_and_upload_shape():
    request = image_to_svg.validate_image_to_svg_request(
        {
            "source": {
                "kind": "upload",
                "image": {
                    "name": "art.png",
                    "mimeType": "image/png",
                    "dataBase64": "iVBORw0KGgo=",
                },
            }
        }
    )

    assert request["source"]["kind"] == "upload"
    assert request["mode"] == "artwork"
    assert request["detail"] == "medium"
    assert request["colors"] == "auto"
    assert request["background"] == "preserve"
    assert request["cropMode"] == "preserve"
    assert request["stylization"] is None
    assert request["advanced"]["backgroundTolerance"] == 18


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"source": {"kind": "gallery", "id": "../secret"}}, "source"),
        ({"source": {"kind": "upload", "image": {}}, "mode": "photo-stylized"}, "upload"),
        ({"source": {"kind": "gallery", "id": "x"}, "stylization": "creative"}, "stylization"),
        ({"source": {"kind": "gallery", "id": "x"}, "mode": "photo-direct", "crop": {"x": 0, "y": 0, "width": 1, "height": 1}}, "crop"),
        ({"source": {"kind": "gallery", "id": "x"}, "cropMode": "manual"}, "crop"),
        ({"source": {"kind": "gallery", "id": "x"}, "advanced": {"posterize": 101}}, "posterize"),
        ({"source": {"kind": "gallery", "id": "x"}, "unexpected": True}, "Unsupported"),
    ],
)
def test_image_to_svg_request_rejects_invalid_combinations(payload, message):
    with pytest.raises(ValueError, match=message):
        image_to_svg.validate_image_to_svg_request(payload)


def test_mode_presets_are_normalized():
    assert image_to_svg.mode_preset("artwork")["posterize"] == 20
    assert image_to_svg.mode_preset("photo-direct")["denoise"] == 35
    assert image_to_svg.mode_preset("photo-stylized", "preserve")["posterize"] == 70
    assert image_to_svg.mode_preset("photo-stylized", "creative")["denoise"] == 20


def test_crop_is_validated_against_decoded_dimensions():
    with pytest.raises(ValueError, match="inside"):
        image_to_svg.validate_crop(
            {"x": 90, "y": 0, "width": 20, "height": 20},
            100,
            100,
        )


def test_background_removal_preserves_enclosed_same_color_subject_pixels():
    pixels = [
        (255, 255, 255, 255), (255, 255, 255, 255), (255, 255, 255, 255),
        (255, 255, 255, 255), (255, 0, 0, 255), (255, 255, 255, 255),
        (255, 255, 255, 255), (255, 255, 255, 255), (255, 255, 255, 255),
    ]
    mask = image_to_svg.border_background_mask(pixels, 3, 3, tolerance=5)
    assert 4 not in mask
    assert 0 in mask
    assert 8 in mask


def test_local_preprocess_produces_png_and_preserves_alpha(tmp_path):
    from PIL import Image

    source = tmp_path / "source.png"
    destination = tmp_path / "prepared.png"
    image = Image.new("RGBA", (32, 24), (255, 255, 255, 255))
    image.putpixel((16, 12), (255, 0, 0, 0))
    image.save(source)

    result = image_to_svg.preprocess_image_to_svg(
        source,
        destination,
        mode="artwork",
        stylization=None,
        detail="medium",
        colors=4,
        background="preserve",
        crop_mode="preserve",
        crop=None,
        advanced=image_to_svg.DEFAULT_ADVANCED,
    )

    assert result == destination.resolve()
    with Image.open(destination) as prepared:
        assert prepared.mode == "RGBA"
        assert prepared.size == (32, 24)
        assert prepared.getpixel((16, 12))[3] == 0
