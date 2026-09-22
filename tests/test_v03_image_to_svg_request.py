from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_v03_image_to_svg as image_to_svg


class ImageToSvgRequestTests(unittest.TestCase):
    def test_defaults_and_upload_shape(self):
        request = image_to_svg.validate_image_to_svg_request({
            "source": {
                "kind": "upload",
                "image": {
                    "name": "art.png",
                    "mimeType": "image/png",
                    "dataBase64": "iVBORw0KGgo=",
                },
            }
        })
        self.assertEqual(request["source"]["kind"], "upload")
        self.assertEqual(request["mode"], "artwork")
        self.assertEqual(request["detail"], "medium")
        self.assertEqual(request["colors"], "auto")
        self.assertEqual(request["background"], "preserve")
        self.assertEqual(request["cropMode"], "preserve")
        self.assertIsNone(request["stylization"])
        self.assertEqual(request["advanced"]["backgroundTolerance"], 18)

    def test_rejects_invalid_combinations(self):
        cases = [
            ({"source": {"kind": "gallery", "id": "../secret"}}, "source"),
            ({"source": {"kind": "upload", "image": {}}, "mode": "photo-stylized"}, "name"),
            ({"source": {"kind": "gallery", "id": "x"}, "stylization": "creative"}, "stylization"),
            (
                {"source": {"kind": "gallery", "id": "x"}, "mode": "photo-direct",
                 "crop": {"x": 0, "y": 0, "width": 1, "height": 1}},
                "crop",
            ),
            ({"source": {"kind": "gallery", "id": "x"}, "cropMode": "manual"}, "crop"),
            ({"source": {"kind": "gallery", "id": "x"}, "advanced": {"posterize": 101}}, "posterize"),
            ({"source": {"kind": "gallery", "id": "x"}, "unexpected": True}, "Unsupported"),
        ]
        for payload, message in cases:
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(ValueError, message):
                    image_to_svg.validate_image_to_svg_request(payload)

    def test_mode_presets(self):
        self.assertEqual(image_to_svg.mode_preset("artwork")["posterize"], 20)
        self.assertEqual(image_to_svg.mode_preset("photo-direct")["denoise"], 35)
        self.assertEqual(image_to_svg.mode_preset("photo-stylized", "preserve")["posterize"], 70)
        self.assertEqual(image_to_svg.mode_preset("photo-stylized", "creative")["denoise"], 20)

    def test_crop_is_validated_against_decoded_dimensions(self):
        with self.assertRaisesRegex(ValueError, "inside"):
            image_to_svg.validate_crop({"x": 90, "y": 0, "width": 20, "height": 20}, 100, 100)

    def test_background_removal_preserves_enclosed_same_color_subject_pixels(self):
        pixels = [
            (255, 255, 255, 255), (255, 255, 255, 255), (255, 255, 255, 255),
            (255, 255, 255, 255), (255, 0, 0, 255), (255, 255, 255, 255),
            (255, 255, 255, 255), (255, 255, 255, 255), (255, 255, 255, 255),
        ]
        mask = image_to_svg.border_background_mask(pixels, 3, 3, tolerance=5)
        self.assertNotIn(4, mask)
        self.assertIn(0, mask)
        self.assertIn(8, mask)

    def test_local_preprocess_preserves_alpha(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            destination = root / "prepared.png"
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
                advanced=image_to_svg.ADVANCED_DEFAULTS,
            )

            self.assertEqual(result, destination.resolve())
            with Image.open(destination) as prepared:
                self.assertEqual(prepared.mode, "RGBA")
                self.assertEqual(prepared.size, (32, 24))
                self.assertEqual(prepared.getpixel((16, 12))[3], 0)


class ImageToSvgTestBridge:
    def _vector_dependency_ready(self):
        return True

    def _krea_image_edit_ready(self):
        return False


class ImageToSvgApiTests(unittest.TestCase):
    class Api(image_to_svg.ImageToSvgApiMixin):
        def __init__(self):
            self.bridge = ImageToSvgTestBridge()

        @staticmethod
        def _decode_json(body):
            import json
            return json.loads(body.decode("utf-8"))

        def _submit_vector_job(self, request, method):
            return {"jobId": "test-job", "jobKind": "vector", "status": "queued"}

        def dispatch(self, method, target, body=None):
            return super().dispatch(method, target, body)

    def test_capabilities_gate_creative(self):
        capabilities = image_to_svg.image_to_svg_capabilities(ImageToSvgTestBridge())
        self.assertEqual(capabilities["creative"]["provider"], "krea2-ostris-edit")
        self.assertFalse(capabilities["creative"]["ready"])
        self.assertEqual(capabilities["modes"], ["artwork", "photo-direct", "photo-stylized"])

    def test_rejects_creative_when_krea_is_unavailable(self):
        import json
        payload = {
            "source": {"kind": "gallery", "id": "gallery-1"},
            "mode": "photo-stylized",
            "stylization": "creative",
        }
        status, result = self.Api().dispatch("POST", "/api/vector/image-to-svg", json.dumps(payload).encode("utf-8"))
        self.assertEqual(status, 409)
        self.assertIn("Krea Image Edit", result["error"])

    def test_submits_local_mode(self):
        import json
        payload = {
            "source": {"kind": "gallery", "id": "gallery-1"},
            "mode": "photo-direct",
            "detail": "simple",
            "colors": 4,
            "cropMode": "auto",
        }
        status, result = self.Api().dispatch("POST", "/api/vector/image-to-svg", json.dumps(payload).encode("utf-8"))
        self.assertEqual(status, 202)
        self.assertEqual(result["jobKind"], "vector")
        self.assertEqual(result["status"], "queued")


if __name__ == "__main__":
    unittest.main()
