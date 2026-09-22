from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_v03_vector as vector


class VectorRequestValidationTests(unittest.TestCase):
    def test_defaults_are_product_owned_and_seed_omission_is_preserved(self):
        clean = vector.validate_text_to_svg_request({"prompt": "  crescent moon fox  "})
        self.assertEqual(clean["prompt"], "crescent moon fox")
        self.assertEqual(clean["style"], "icon")
        self.assertEqual(clean["detail"], "medium")
        self.assertEqual(clean["colors"], "auto")
        self.assertEqual(clean["background"], "transparent")
        self.assertNotIn("seed", clean)
        self.assertNotIn("backgroundColor", clean)

    def test_accepts_supported_fields_and_solid_background_default(self):
        clean = vector.validate_text_to_svg_request({
            "prompt": "a fox curled around a crescent moon",
            "style": "illustration",
            "detail": "detailed",
            "colors": 8,
            "background": "solid",
            "seed": 12345,
        })
        self.assertEqual(clean["colors"], 8)
        self.assertEqual(clean["backgroundColor"], "#ffffff")
        self.assertEqual(clean["seed"], 12345)

        custom = vector.validate_text_to_svg_request({
            "prompt": "mark",
            "background": "solid",
            "backgroundColor": "#A0b1C2",
        })
        self.assertEqual(custom["backgroundColor"], "#a0b1c2")

    def test_rejects_unknown_fields_and_invalid_prompt_enums_palette_seed_or_color(self):
        bad_requests = [
            ({"prompt": "x", "sampler": "euler"}, "Unsupported"),
            ({"prompt": "   "}, "prompt"),
            ({"prompt": "x" * 2001}, "2000"),
            ({"prompt": "x", "style": "logo-text"}, "style"),
            ({"prompt": "x", "detail": "ultra"}, "detail"),
            ({"prompt": "x", "colors": 3}, "colors"),
            ({"prompt": "x", "colors": "4"}, "colors"),
            ({"prompt": "x", "background": "checkerboard"}, "background"),
            ({"prompt": "x", "seed": True}, "seed"),
            ({"prompt": "x", "seed": -1}, "seed"),
            ({"prompt": "x", "seed": 2**63}, "seed"),
            ({"prompt": "x", "background": "solid", "backgroundColor": "white"}, "backgroundColor"),
            ({"prompt": "x", "background": "transparent", "backgroundColor": "#ffffff"}, "backgroundColor"),
        ]
        for request, message in bad_requests:
            with self.subTest(request=request):
                with self.assertRaisesRegex(ValueError, message):
                    vector.validate_text_to_svg_request(request)


class VectorPromptTests(unittest.TestCase):
    def test_icon_prompt_is_flat_text_free_and_symbol_focused(self):
        request = vector.validate_text_to_svg_request({
            "prompt": "red fox and crescent moon",
            "style": "icon",
            "colors": 4,
            "background": "transparent",
        })
        prompt = vector.build_vector_prompt(request).lower()
        for phrase in (
            "flat vector",
            "solid shapes",
            "crisp edges",
            "no gradients",
            "no text, no letters, no numbers, no watermark",
            "one dominant centered",
            "simple silhouette",
            "pure white",
            "maximum palette of 4 colors",
        ):
            self.assertIn(phrase, prompt)
        self.assertIn("red fox and crescent moon", prompt)

    def test_illustration_prompt_allows_fuller_composition_and_solid_color(self):
        request = vector.validate_text_to_svg_request({
            "prompt": "forest animals at a pond",
            "style": "illustration",
            "detail": "simple",
            "background": "solid",
            "backgroundColor": "#112233",
        })
        prompt = vector.build_vector_prompt(request).lower()
        self.assertIn("multiple objects", prompt)
        self.assertIn("full composition", prompt)
        self.assertIn("#112233", prompt)
        self.assertIn("flat full-canvas background", prompt)
        self.assertNotIn("one dominant centered", prompt)


class VectorBackgroundMaskTests(unittest.TestCase):
    def test_border_connected_mask_preserves_same_colored_enclosed_pixels(self):
        width = 7
        height = 7
        white = (255, 255, 255)
        red = (200, 20, 20)
        pixels = [white] * (width * height)
        for y in range(1, 6):
            for x in range(1, 6):
                pixels[y * width + x] = red
        pixels[3 * width + 3] = white

        mask = vector._border_connected_background_mask(pixels, width, height, tolerance=18)
        self.assertIn(0, mask)
        self.assertIn(6, mask)
        self.assertNotIn(3 * width + 3, mask)
        self.assertNotIn(2 * width + 2, mask)

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow is supplied by the managed StableAMD runtime.")
    def test_prepare_vector_raster_writes_alpha_only_for_border_connected_background(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            output = root / "prepared.png"
            image = Image.new("RGB", (8, 8), (255, 255, 255))
            for y in range(1, 7):
                for x in range(1, 7):
                    image.putpixel((x, y), (20, 120, 200))
            image.putpixel((4, 4), (255, 255, 255))
            image.save(source)

            vector.prepare_vector_raster(source, output, "transparent")
            prepared = Image.open(output).convert("RGBA")
            self.assertEqual(prepared.getpixel((0, 0))[3], 0)
            self.assertEqual(prepared.getpixel((4, 4))[3], 255)
            self.assertEqual(prepared.getpixel((2, 2))[3], 255)


if __name__ == "__main__":
    unittest.main()
