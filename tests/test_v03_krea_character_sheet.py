from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "app" / "backend"
FRONTEND = ROOT / "app" / "frontend"
KREA_FRONTEND_PATH = FRONTEND / "app-krea-edit.js"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import stableamd_v03_character_sheet as character_sheet
import stableamd_v03_edit_server as server


class StableAmdKreaCharacterSheetTests(unittest.TestCase):
    def test_krea_policy_advertises_quality_character_sheet_contract(self):
        class Parent:
            def model_support(self):
                return {
                    "models": [{
                        "id": "krea",
                        "family": "krea2",
                        "capabilities": {"txt2img": "supported", "img2img": "planned"},
                        "editPolicy": {"tasks": []},
                    }]
                }

        class Bridge(character_sheet.CharacterSheetBridgeMixin, Parent):
            pass

        policy = Bridge().model_support()["models"][0]["editPolicy"]
        task = {item["id"]: item for item in policy["tasks"]}["character-sheet"]
        self.assertEqual(task["label"], "Character sheet")
        self.assertEqual(task["referenceImages"], 0)
        self.assertEqual(task["generationMode"], "sequential")
        self.assertEqual(task["framingModes"], ["auto", "portrait", "full-body"])
        self.assertEqual(task["defaultFraming"], "auto")
        self.assertEqual(task["compositeLayout"], "grid-3x2")
        self.assertEqual(task["views"], ["face-close-up", "front", "three-quarter", "side", "back"])
        self.assertEqual(task["viewSizes"]["face-close-up"], {"width": 1024, "height": 1024})
        self.assertEqual(task["viewSizes"]["portrait"], {"width": 896, "height": 1152})
        self.assertEqual(task["viewSizes"]["full-body"], {"width": 832, "height": 1216})

    def test_api_accepts_framing_mode_and_rejects_unknown_mode(self):
        api = server.StableAmdApi(object())
        request = {
            "prompt": "Preserve the exact same character.",
            "mode": "img2img",
            "inputImage": {
                "name": "character.png",
                "mimeType": "image/png",
                "dataBase64": "iVBORw0KGgo=",
            },
            "editTask": "character-sheet",
            "characterSheetView": "side",
            "characterSheetFraming": "auto",
        }
        validated = api._validate_generation(request)
        self.assertEqual(validated["characterSheetFraming"], "auto")

        for framing in ("portrait", "full-body"):
            validated = api._validate_generation({**request, "characterSheetFraming": framing})
            self.assertEqual(validated["characterSheetFraming"], framing)

        with self.assertRaisesRegex(ValueError, "characterSheetFraming"):
            api._validate_generation({**request, "characterSheetFraming": "cinematic"})

    def test_prompt_and_output_size_follow_resolved_framing(self):
        builder = character_sheet.CharacterSheetBridgeMixin._build_character_sheet_instruction
        size = character_sheet.CharacterSheetBridgeMixin._character_sheet_output_size

        portrait = builder("front", "keep the red scarf", "portrait")
        full_body = builder("front", "keep the red scarf", "full-body")
        face = builder("face-close-up", "keep the red scarf", "portrait")

        self.assertIn("upper body", portrait.lower())
        self.assertNotIn("head to toe", portrait.lower())
        self.assertIn("head to toe", full_body.lower())
        self.assertIn("close-up", face.lower())
        self.assertEqual(size("face-close-up", "portrait"), (1024, 1024))
        self.assertEqual(size("front", "portrait"), (896, 1152))
        self.assertEqual(size("front", "full-body"), (832, 1216))

    def test_auto_framing_uses_dwpose_visibility_for_portrait_vs_full_body(self):
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("NumPy is supplied by the managed DWPose runtime, not generic API CI.")

        analyzer = character_sheet.CharacterSheetBridgeMixin._analyze_dwpose_candidates
        points = [[[0.0, 0.0] for _ in range(134)]]
        scores = [[0.0 for _ in range(134)]]
        # Head/shoulders/hips on the right side of a landscape source; no knees/ankles.
        for index, xy in {0: (1180, 160), 1: (1180, 260), 2: (1260, 300), 5: (1100, 300), 8: (1240, 650), 11: (1120, 650)}.items():
            points[0][index] = list(xy)
            scores[0][index] = 0.95
        portrait = analyzer(points, scores, 1500, 1000)
        self.assertEqual(portrait["framing"], "portrait")
        self.assertGreater(portrait["subjectBox"][0], 900)

        for index, xy in {9: (1240, 790), 10: (1240, 950), 12: (1120, 790), 13: (1120, 950)}.items():
            points[0][index] = list(xy)
            scores[0][index] = 0.95
        full_body = analyzer(points, scores, 1500, 1000)
        self.assertEqual(full_body["framing"], "full-body")
        self.assertTrue(full_body["detected"])

    def test_subject_crop_matches_target_ratio_without_stretching(self):
        class FakeImage:
            def __init__(self, width: int, height: int):
                self.width = width
                self.height = height
                self.size = (width, height)

            def crop(self, box):
                left, top, right, bottom = box
                return FakeImage(int(right - left), int(bottom - top))

        source = FakeImage(1500, 1000)
        cropper = character_sheet.CharacterSheetBridgeMixin._crop_reference_to_subject
        cropped = cropper(source, (900, 100, 1450, 950), 896, 1152, margin=0.10)
        self.assertGreater(cropped.width, 0)
        self.assertGreater(cropped.height, 0)
        self.assertAlmostEqual(cropped.width / cropped.height, 896 / 1152, places=2)
        self.assertLess(cropped.width, source.width)

    def test_auto_unknown_source_preserves_source_ratio_for_nonhuman_fallback(self):
        resolver = character_sheet.CharacterSheetBridgeMixin._character_sheet_output_size
        width, height = resolver("front", "source", (1500, 1000))
        self.assertEqual(width % 16, 0)
        self.assertEqual(height % 16, 0)
        self.assertAlmostEqual(width / height, 1.5, delta=0.04)

    @unittest.skipIf(Image is None, "Pillow is supplied by the managed StableAMD runtime, not generic API CI.")
    def test_composite_creates_one_png_and_hides_child_history_after_success(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            output = repo / ".runtime" / "stableamd" / "output"
            history = repo / ".runtime" / "stableamd" / "history"
            output.mkdir(parents=True)
            history.mkdir(parents=True)

            items = []
            for index, view in enumerate(("face-close-up", "front", "three-quarter", "side", "back")):
                image_path = output / f"{index}.png"
                Image.new("RGB", (512 + index * 16, 640), (40 + index * 20, 80, 120)).save(image_path)
                history_path = history / f"{index}.json"
                history_path.write_text(json.dumps({"imagePath": str(image_path), "editOperation": "character-sheet-view"}), encoding="utf-8")
                items.append({
                    "CharacterSheetView": view,
                    "CharacterSheetLabel": view,
                    "ImagePath": str(image_path),
                    "HistoryPath": str(history_path),
                    "GenerationSeconds": 1.0,
                    "ModelId": "krea",
                    "ModelName": "Krea 2 Turbo",
                })

            class Parent:
                repo_root = repo

                def _save_bundle_history(self, record):
                    path = history / "composite.json"
                    path.write_text(json.dumps(record), encoding="utf-8")
                    return path

                def history(self, limit=0):
                    records = [json.loads(path.read_text(encoding="utf-8")) for path in history.glob("*.json")]
                    return records[:limit] if limit else records

            class Bridge(character_sheet.CharacterSheetBridgeMixin, Parent):
                pass

            result = Bridge().compose_character_sheet({
                "items": items,
                "prompt": "same character",
                "sourceFraming": "portrait",
                "requestedFraming": "auto",
            })
            composite_path = Path(result["ImagePath"])
            self.assertTrue(composite_path.is_file())
            self.assertEqual(result["EditOperation"], "character-sheet")
            self.assertEqual(result["CharacterSheetLayout"], "grid-3x2")
            self.assertEqual(len(result["CharacterSheetItems"]), 5)
            with Image.open(composite_path) as composite:
                self.assertGreater(composite.width, 2000)
                self.assertGreater(composite.height, 1800)
            for item in items:
                record = json.loads(Path(item["HistoryPath"]).read_text(encoding="utf-8"))
                self.assertTrue(record["galleryHidden"])
                self.assertEqual(record["characterSheetParentPromptId"], result["PromptId"])

            visible = Bridge().history()
            self.assertTrue(all(not record.get("galleryHidden") for record in visible))
            self.assertTrue(any(record.get("editOperation") == "character-sheet" for record in visible))

    def test_frontend_exposes_framing_and_requests_persisted_composite(self):
        source = KREA_FRONTEND_PATH.read_text(encoding="utf-8")
        self.assertIn('id="krea-character-sheet-framing"', source)
        self.assertIn('value="auto"', source)
        self.assertIn('value="portrait"', source)
        self.assertIn('value="full-body"', source)
        self.assertIn("characterSheetFraming", source)
        self.assertIn('/api/character-sheet/compose', source)
        self.assertIn("CharacterSheetComposite", source)
        self.assertIn("Character sheet complete", source)


if __name__ == "__main__":
    unittest.main()
