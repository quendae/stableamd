from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import stableamd_v03_character_sheet_v2 as sheetv2


BASE_REQUEST = {
    "prompt": "keep identity",
    "mode": "img2img",
    "modelId": "krea",
    "inputImage": {
        "name": "source-person.png",
        "mimeType": "image/png",
        "dataBase64": "stub",
    },
    "editTask": "character-sheet",
    "characterSheetVersion": "v2",
    "characterSheetDetailer": False,
}


class _Staged:
    def __init__(self, name: str, deleted: list[str]):
        self.name = name
        self._deleted = deleted

    def unlink(self, missing_ok=False):
        self._deleted.append(self.name)


class CharacterSheetV2IdentityTuningTests(unittest.TestCase):
    def _bridge(self, *, face_detected: bool):
        calls = []
        deleted = []

        class Parent:
            repo_root = Path(".")

            def _selected_product_model(self, request):
                return {
                    "id": "krea",
                    "family": "krea2",
                    "assetMode": "bundle",
                    "name": "Krea 2 Turbo",
                }

            def _krea_identity_edit_ready(self):
                return True

            def _stage_character_sheet_v2_source(self, source):
                name = str(source.get("name") or "source.png")
                staged_name = "identity-face.png" if "identity-face" in name else "source-v2.png"
                calls.append(("stage", staged_name))
                return _Staged(staged_name, deleted)

            def _generate_krea_identity_edit(self, request, model, **context):
                calls.append(("identity", dict(context)))
                return {
                    "PromptId": "base",
                    "ImagePath": "C:/output/base.png",
                    "HistoryPath": "C:/history/base.json",
                    "ModelId": "krea",
                    "ModelName": "Krea 2 Turbo",
                    "Seed": 123,
                    "GenerationSeconds": 1.0,
                }

            def _persist_character_sheet_v2_base_metadata(self, result, metadata):
                calls.append(("metadata", dict(metadata)))

            def _release_character_sheet_runtime(self):
                return True

        class Bridge(sheetv2.CharacterSheetV2BridgeMixin, Parent):
            def _analyze_character_source(self, source):
                if face_detected:
                    return {
                        "detected": True,
                        "faceBox": [100, 80, 220, 230],
                        "subjectBox": [60, 40, 300, 700],
                        "sourceSize": [400, 800],
                    }
                return {
                    "detected": True,
                    "faceBox": None,
                    "subjectBox": [60, 40, 300, 700],
                    "sourceSize": [400, 800],
                }

            def _prepare_v2_original_identity(self, source, analysis):
                if not face_detected:
                    return None
                return {
                    "name": "source-person-identity-face.png",
                    "mimeType": "image/png",
                    "dataBase64": "face",
                }

        return Bridge(), calls, deleted

    def test_base_pass_uses_full_source_plus_detected_face_as_second_identity_reference(self):
        bridge, calls, deleted = self._bridge(face_detected=True)
        result = bridge.generate_character_sheet_v2(dict(BASE_REQUEST))

        identity_call = next(item for item in calls if item[0] == "identity")
        context = identity_call[1]
        self.assertEqual(context["image_name"], "source-v2.png")
        self.assertEqual(context["identity_image_name"], "identity-face.png")
        self.assertEqual(deleted, ["source-v2.png", "identity-face.png"])
        self.assertTrue(result["CharacterSheetBaseIdentityReference"])

    def test_base_pass_does_not_guess_face_anchor_when_source_has_no_face_box(self):
        bridge, calls, deleted = self._bridge(face_detected=False)
        result = bridge.generate_character_sheet_v2(dict(BASE_REQUEST))

        identity_call = next(item for item in calls if item[0] == "identity")
        context = identity_call[1]
        self.assertIsNone(context.get("identity_image_name"))
        self.assertEqual(deleted, ["source-v2.png"])
        self.assertFalse(result["CharacterSheetBaseIdentityReference"])

    def test_identity_prompts_forbid_beautification_and_preserve_specific_face_geometry(self):
        base_prompt = sheetv2.CharacterSheetV2BridgeMixin._character_sheet_v2_prompt("").lower()
        detail_prompt = sheetv2.CharacterSheetV2BridgeMixin._character_sheet_v2_detail_prompt("front").lower()

        for phrase in (
            "do not beautify",
            "eye spacing",
            "nose",
            "mouth",
            "jaw",
            "hairline",
            "natural asymmetries",
        ):
            self.assertIn(phrase, base_prompt)
            self.assertIn(phrase, detail_prompt)
        self.assertIn("second reference", base_prompt)
        self.assertIn("authoritative", base_prompt)


if __name__ == "__main__":
    unittest.main()
