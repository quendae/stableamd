from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "app" / "backend"
FRONTEND = ROOT / "app" / "frontend"
KREA_FRONTEND_PATH = FRONTEND / "app-krea-edit.js"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import stableamd_v03_character_sheet as character_sheet


class StableAmdCharacterSheetIdentityTests(unittest.TestCase):
    def test_identity_instruction_uses_face_reference_and_rejects_source_scene_props(self):
        instruction = character_sheet.CharacterSheetBridgeMixin._build_character_sheet_instruction(
            "side",
            "Preserve the blue coat and knitted hat.",
            "full-body",
        ).lower()

        self.assertIn("picture 2", instruction)
        self.assertIn("identity reference", instruction)
        self.assertIn("facial identity", instruction)
        self.assertIn("ignore background", instruction)
        self.assertIn("props", instruction)

    def test_model_policy_advertises_internal_face_identity_reference(self):
        class Parent:
            def model_support(self):
                return {
                    "models": [{
                        "id": "krea",
                        "family": "krea2",
                        "editPolicy": {"tasks": []},
                    }]
                }

        class Bridge(character_sheet.CharacterSheetBridgeMixin, Parent):
            pass

        task = {
            item["id"]: item
            for item in Bridge().model_support()["models"][0]["editPolicy"]["tasks"]
        }["character-sheet"]
        self.assertEqual(task.get("identityMode"), "face-plus-source")
        self.assertEqual(task.get("identityReference"), "auto-face-crop")

    def test_body_view_stages_internal_face_reference_as_picture_two(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            staged_paths: list[Path] = []

            def stage_input(_repo_root, _payload):
                path = repo / f"staged-{len(staged_paths)}.png"
                path.write_bytes(b"stage")
                staged_paths.append(path)
                return path

            class Parent:
                repo_root = repo

                def __init__(self):
                    self._stableamd_krea_edit_context = SimpleNamespace(value=None)
                    self.captured_context = None

                def _selected_product_model(self, _request):
                    return {"id": "krea", "family": "krea2", "assetMode": "bundle"}

                def _krea_image_edit_ready(self):
                    return True

                def _control_request(self, _request):
                    return None

                def _generate_krea2_turbo(self, request, _selected):
                    self.captured_context = dict(self._stableamd_krea_edit_context.value or {})
                    return {
                        "PromptId": "child",
                        "Prompt": request["prompt"],
                        "ModelId": "krea",
                        "ModelName": "Krea 2 Turbo",
                        "Width": request["width"],
                        "Height": request["height"],
                        "Seed": request.get("seed", 123),
                        "GenerationSeconds": 1.0,
                        "ImagePath": str(repo / "child.png"),
                    }

                def _persist_krea_image_edit_metadata(self, *_args, **_kwargs):
                    return None

            class Bridge(character_sheet.CharacterSheetBridgeMixin, Parent):
                def _prepare_character_sheet_reference(self, source, view, requested_framing):
                    return (
                        source,
                        "full-body",
                        {
                            "detected": True,
                            "faceBox": [400, 100, 620, 330],
                            "subjectBox": [250, 80, 800, 980],
                            "referenceCropped": True,
                        },
                        832,
                        1216,
                    )

                def _prepare_character_sheet_identity_reference(self, _source, _analysis):
                    return {
                        "name": "identity-face.png",
                        "mimeType": "image/png",
                        "dataBase64": "aWRlbnRpdHk=",
                    }

            bridge = Bridge()
            request = {
                "modelId": "krea",
                "mode": "img2img",
                "prompt": "Preserve the exact same subject.",
                "inputImage": {
                    "name": "source.png",
                    "mimeType": "image/png",
                    "dataBase64": "c291cmNl",
                },
                "editTask": "character-sheet",
                "characterSheetView": "side",
                "characterSheetFraming": "auto",
                "seed": 424242,
            }

            with patch.object(character_sheet.base, "stage_input_image", side_effect=stage_input):
                result = bridge.generate(request)

            self.assertEqual(len(staged_paths), 2)
            self.assertIsNotNone(bridge.captured_context)
            references = bridge.captured_context.get("references") or []
            self.assertEqual(len(references), 1)
            self.assertEqual(references[0].get("role"), "content")
            self.assertEqual(references[0].get("name"), "staged-1.png")
            self.assertTrue(result.get("CharacterSheetIdentityReference"))

    def test_frontend_reuses_one_random_seed_for_all_five_views(self):
        source = KREA_FRONTEND_PATH.read_text(encoding="utf-8")
        self.assertIn("characterSheetSharedSeed", source)
        self.assertIn("const sharedSeed = characterSheetSharedSeed(payload)", source)
        self.assertIn("seed: sharedSeed", source)


if __name__ == "__main__":
    unittest.main()
