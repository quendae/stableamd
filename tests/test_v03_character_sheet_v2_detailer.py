from __future__ import annotations

import tempfile
import sys
import unittest
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import stableamd_v03_character_sheet_v2 as sheetv2


class CharacterSheetV2GeometryTests(unittest.TestCase):
    def test_five_panel_regions_cover_base_without_overlap_or_gaps(self):
        regions = sheetv2.CharacterSheetV2BridgeMixin._panel_regions(1792, 1024)
        self.assertEqual([region.role for region in regions], ["face", "front", "three-quarter", "side", "back"])
        self.assertEqual(regions[0].box[0], 0)
        self.assertEqual(regions[-1].box[2], 1792)
        for left, right in zip(regions, regions[1:]):
            self.assertEqual(left.box[2], right.box[0])
        for region in regions:
            width = region.box[2] - region.box[0]
            self.assertGreater(width, 0)
            dx0, dy0, dx1, dy1 = region.detail_box
            self.assertGreater(dx0, 0)
            self.assertGreater(dy0, 0)
            self.assertLess(dx1, width)
            self.assertLess(dy1, 1024)

    def test_back_is_never_detailed_and_face_box_expands_aligns_and_clamps(self):
        bridge = sheetv2.CharacterSheetV2BridgeMixin
        self.assertTrue(bridge._should_detail_panel("face"))
        self.assertTrue(bridge._should_detail_panel("front"))
        self.assertTrue(bridge._should_detail_panel("three-quarter"))
        self.assertTrue(bridge._should_detail_panel("side"))
        self.assertFalse(bridge._should_detail_panel("back"))
        box = bridge._face_detail_box([95, 80, 145, 140], (358, 1024))
        self.assertIsNotNone(box)
        x0, y0, x1, y1 = box
        self.assertGreaterEqual(x0, 0)
        self.assertGreaterEqual(y0, 0)
        self.assertLessEqual(x1, 358)
        self.assertLessEqual(y1, 1024)
        self.assertEqual((x1 - x0) % 16, 0)
        self.assertEqual((y1 - y0) % 16, 0)
        self.assertGreater(x1 - x0, 50)
        self.assertGreater(y1 - y0, 60)
        self.assertIsNone(bridge._face_detail_box([10, 10, 10, 20], (358, 1024)))
        self.assertIsNone(bridge._face_detail_box([10, 10, 20], (358, 1024)))


class CharacterSheetV2DetailerFallbackTests(unittest.TestCase):
    @staticmethod
    def _panel(role="front"):
        return sheetv2.CharacterSheetV2Panel(
            role=role,
            index=1,
            path=Path(f"{role}.png"),
            box=(0, 0, 358, 1024),
            detail_box=(5, 15, 353, 1009),
        )

    def test_no_face_keeps_original_panel_without_generation(self):
        calls = []

        class Bridge(sheetv2.CharacterSheetV2BridgeMixin):
            def _prepare_v2_detail_context(self, panel, source):
                calls.append("detect")
                return None
            def _generate_krea_identity_edit(self, *args, **kwargs):
                calls.append("generate")
                raise AssertionError("must not generate")

        result = Bridge()._refine_v2_panel({}, {}, self._panel(), {})
        self.assertEqual(result["path"], Path("front.png"))
        self.assertEqual(result["detailerSkipped"], "no-face")
        self.assertEqual(calls, ["detect"])

    def test_back_skips_detection_and_generation(self):
        class Bridge(sheetv2.CharacterSheetV2BridgeMixin):
            def _prepare_v2_detail_context(self, panel, source):
                raise AssertionError("BACK must not run DWPose")

        result = Bridge()._refine_v2_panel({}, {}, self._panel("back"), {})
        self.assertEqual(result["path"], Path("back.png"))
        self.assertEqual(result["detailerSkipped"], "back-view")

    def test_detected_face_runs_one_dual_reference_detailer_and_releases_runtime(self):
        calls = []

        class Staged:
            def __init__(self, name):
                self.name = name
            def unlink(self, missing_ok=False):
                calls.append(("unlink", self.name, missing_ok))

        class Bridge(sheetv2.CharacterSheetV2BridgeMixin):
            def _prepare_v2_detail_context(self, panel, source):
                return {
                    "scene": Staged("generated-head.png"),
                    "identity": Staged("original-face.png"),
                    "cropBox": (64, 48, 256, 304),
                    "width": 768,
                    "height": 1024,
                }
            def _generate_krea_identity_edit(self, request, model, **context):
                calls.append(("generate", dict(context)))
                return {"ImagePath": "refined.png", "HistoryPath": "refined.json", "PromptId": "detail-1"}
            def _stitch_v2_detail_result(self, panel, refined_path, crop_box):
                calls.append(("stitch", refined_path, crop_box))
                return Path("stitched.png")
            def _release_character_sheet_runtime(self):
                calls.append(("free",))

        result = Bridge()._refine_v2_panel({"seed": 7}, {"id": "krea"}, self._panel("side"), {})
        generations = [item for item in calls if item[0] == "generate"]
        self.assertEqual(len(generations), 1)
        context = generations[0][1]
        self.assertEqual(context["image_name"], "generated-head.png")
        self.assertEqual(context["identity_image_name"], "original-face.png")
        self.assertIn("strict side profile", context["prompt"].lower())
        self.assertEqual(result["path"], Path("stitched.png"))
        self.assertEqual(result["detailerStatus"], "completed")
        self.assertIn(("free",), calls)
        self.assertTrue(any(item[0] == "unlink" for item in calls))

    def test_detailer_generation_failure_keeps_base_panel_and_continues(self):
        calls = []

        class Staged:
            name = "temp.png"
            def unlink(self, missing_ok=False):
                calls.append("unlink")

        class Bridge(sheetv2.CharacterSheetV2BridgeMixin):
            def _prepare_v2_detail_context(self, panel, source):
                return {"scene": Staged(), "identity": Staged(), "cropBox": (0, 0, 128, 128), "width": 512, "height": 512}
            def _generate_krea_identity_edit(self, *args, **kwargs):
                raise sheetv2.base.StableAmdBridgeError("GPU child failed")
            def _release_character_sheet_runtime(self):
                calls.append("free")

        result = Bridge()._refine_v2_panel({}, {}, self._panel(), {})
        self.assertEqual(result["path"], Path("front.png"))
        self.assertEqual(result["detailerSkipped"], "generation-failed")
        self.assertIn("free", calls)
        self.assertEqual(calls.count("unlink"), 2)


@unittest.skipIf(Image is None, "Pillow is supplied by the managed StableAMD runtime, not generic API CI.")
class CharacterSheetV2ImageTests(unittest.TestCase):
    def test_extract_and_reassemble_preserve_sheet_dimensions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            output = repo / ".runtime" / "stableamd" / "output"
            output.mkdir(parents=True)
            base_path = output / "base.png"
            image = Image.new("RGB", (1792, 1024), (20, 30, 40))
            image.save(base_path)

            class Bridge(sheetv2.CharacterSheetV2BridgeMixin):
                repo_root = repo

            bridge = Bridge()
            panels = bridge._extract_v2_panels(base_path)
            self.assertEqual(len(panels), 5)
            self.assertTrue(all(panel.path.is_file() for panel in panels))
            final_path = bridge._reassemble_v2_panels(base_path, panels)
            self.assertTrue(final_path.is_file())
            with Image.open(final_path) as final:
                self.assertEqual(final.size, (1792, 1024))

    def test_feather_stitch_never_resizes_full_panel(self):
        original = Image.new("RGB", (358, 1024), (40, 40, 40))
        refined = Image.new("RGB", (768, 768), (200, 200, 200))
        stitched = sheetv2.CharacterSheetV2BridgeMixin._feather_stitch(
            original, refined, (80, 96, 272, 336), feather=0.12
        )
        self.assertEqual(stitched.size, original.size)


if __name__ == "__main__":
    unittest.main()
