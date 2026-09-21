from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import stableamd_v03_character_sheet_v2 as sheetv2

try:
    import stableamd_v03_character_sheet_face_refine as face_refine
except ModuleNotFoundError:
    face_refine = None


class _Staged:
    def __init__(self, name: str, calls: list[tuple]):
        self.name = name
        self._calls = calls

    def unlink(self, missing_ok=False):
        self._calls.append(("unlink", self.name, missing_ok))


@unittest.skipIf(face_refine is None, "RED: face-refine production module not implemented yet")
class CharacterSheetV2FaceRefineTests(unittest.TestCase):
    @staticmethod
    def _panel(role: str = "front") -> sheetv2.CharacterSheetV2Panel:
        return sheetv2.CharacterSheetV2Panel(
            role=role,
            index=1,
            path=Path(f"{role}.png"),
            box=(0, 0, 358, 1024),
            detail_box=(5, 15, 353, 1009),
        )

    def test_tight_face_pass_is_limited_to_face_front_and_three_quarter(self):
        mixin = face_refine.CharacterSheetV2FaceRefineBridgeMixin
        self.assertTrue(mixin._should_tight_face_refine("face"))
        self.assertTrue(mixin._should_tight_face_refine("front"))
        self.assertTrue(mixin._should_tight_face_refine("three-quarter"))
        self.assertFalse(mixin._should_tight_face_refine("side"))
        self.assertFalse(mixin._should_tight_face_refine("back"))

    def test_second_pass_uses_tight_original_face_and_preserves_first_pass_panel(self):
        calls: list[tuple] = []

        class Parent:
            def _refine_v2_panel(self, request, model, panel, source):
                calls.append(("first-pass", panel.role))
                return {
                    "role": panel.role,
                    "path": Path("first-pass.png"),
                    "detailerStatus": "completed",
                    "detailerGenerationSeconds": 2.5,
                }

        class Bridge(face_refine.CharacterSheetV2FaceRefineBridgeMixin, Parent):
            def _prepare_v2_tight_detail_context(self, panel, first_path, source):
                calls.append(("prepare-tight", panel.role, Path(first_path)))
                return {
                    "scene": _Staged("generated-tight-face.png", calls),
                    "identity": _Staged("original-tight-face.png", calls),
                    "cropBox": (96, 80, 240, 240),
                    "width": 512,
                    "height": 512,
                }

            def _generate_krea_identity_edit(self, request, model, **context):
                calls.append(("generate-tight", dict(context)))
                return {
                    "ImagePath": "tight-refined.png",
                    "HistoryPath": "tight-refined.json",
                    "PromptId": "tight-1",
                    "GenerationSeconds": 1.25,
                }

            def _stitch_v2_tight_detail_result(self, panel, first_path, refined_path, crop_box):
                calls.append(("stitch-tight", Path(first_path), refined_path, crop_box))
                return Path("second-pass.png")

            def _release_character_sheet_runtime(self):
                calls.append(("free",))

        result = Bridge()._refine_v2_panel({"seed": 1}, {"id": "krea"}, self._panel("front"), {})
        self.assertEqual(result["path"], Path("second-pass.png"))
        self.assertEqual(result["detailerStatus"], "completed")
        self.assertEqual(result["faceIdentityStatus"], "completed")
        self.assertEqual(result["faceIdentityPromptId"], "tight-1")
        self.assertEqual(result["faceIdentityCropBox"], [96, 80, 240, 240])
        self.assertAlmostEqual(result["detailerGenerationSeconds"], 3.75)

        tight = next(item for item in calls if item[0] == "generate-tight")[1]
        self.assertEqual(tight["image_name"], "generated-tight-face.png")
        self.assertEqual(tight["identity_image_name"], "original-tight-face.png")
        prompt = tight["prompt"].lower()
        self.assertIn("do not make the person older", prompt)
        self.assertIn("cheek fullness", prompt)
        self.assertIn("eye spacing", prompt)
        self.assertIn("nose", prompt)
        self.assertIn("mouth", prompt)
        self.assertIn("jaw", prompt)
        self.assertIn("hairline", prompt)
        self.assertIn("preserve image a's camera angle", prompt)
        self.assertIn(("free",), calls)
        self.assertIn(("unlink", "generated-tight-face.png", True), calls)
        self.assertIn(("unlink", "original-tight-face.png", True), calls)

    def test_side_keeps_first_pass_and_never_runs_tight_face_pass(self):
        calls: list[tuple] = []

        class Parent:
            def _refine_v2_panel(self, request, model, panel, source):
                return {"role": panel.role, "path": Path("side-first-pass.png"), "detailerStatus": "completed"}

        class Bridge(face_refine.CharacterSheetV2FaceRefineBridgeMixin, Parent):
            def _prepare_v2_tight_detail_context(self, *args, **kwargs):
                calls.append(("prepare",))
                raise AssertionError("SIDE must not run tight frontal identity refinement")

        result = Bridge()._refine_v2_panel({}, {}, self._panel("side"), {})
        self.assertEqual(result["path"], Path("side-first-pass.png"))
        self.assertEqual(result["faceIdentityStatus"], "skipped")
        self.assertEqual(result["faceIdentitySkipped"], "profile-view")
        self.assertEqual(calls, [])

    def test_second_pass_failure_keeps_successful_first_pass(self):
        calls: list[tuple] = []

        class Parent:
            def _refine_v2_panel(self, request, model, panel, source):
                return {
                    "role": panel.role,
                    "path": Path("first-pass.png"),
                    "detailerStatus": "completed",
                    "detailerGenerationSeconds": 2.0,
                }

        class Bridge(face_refine.CharacterSheetV2FaceRefineBridgeMixin, Parent):
            def _prepare_v2_tight_detail_context(self, panel, first_path, source):
                return {
                    "scene": _Staged("tight-a.png", calls),
                    "identity": _Staged("tight-b.png", calls),
                    "cropBox": (80, 64, 240, 224),
                    "width": 512,
                    "height": 512,
                }

            def _generate_krea_identity_edit(self, *args, **kwargs):
                raise sheetv2.base.StableAmdBridgeError("tight pass failed")

            def _release_character_sheet_runtime(self):
                calls.append(("free",))

        result = Bridge()._refine_v2_panel({}, {}, self._panel("three-quarter"), {})
        self.assertEqual(result["path"], Path("first-pass.png"))
        self.assertEqual(result["detailerStatus"], "completed")
        self.assertEqual(result["faceIdentityStatus"], "skipped")
        self.assertEqual(result["faceIdentitySkipped"], "generation-failed")
        self.assertIn("tight pass failed", result["faceIdentityError"])
        self.assertIn(("free",), calls)

    def test_tight_face_prompt_preserves_age_and_distinctive_geometry(self):
        prompt = face_refine.CharacterSheetV2FaceRefineBridgeMixin._tight_face_identity_prompt("front").lower()
        for phrase in (
            "do not make the person older",
            "cheek fullness",
            "eye spacing",
            "nose",
            "mouth",
            "jaw",
            "hairline",
            "natural asymmetries",
        ):
            self.assertIn(phrase, prompt)


if __name__ == "__main__":
    unittest.main()
