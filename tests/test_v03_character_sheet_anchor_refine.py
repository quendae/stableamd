from __future__ import annotations

import base64
import json
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
import stableamd_v03_character_sheet_anchor as anchor
import stableamd_v03_edit_server as server


class StableAmdCharacterSheetAnchorRefineTests(unittest.TestCase):
    def test_api_accepts_anchor_refinement_fields_only_for_character_sheet(self):
        class Bridge:
            pass

        api = server.StableAmdApi(Bridge())
        source = {
            "name": "source.png",
            "mimeType": "image/png",
            "dataBase64": base64.b64encode(b"\x89PNG\r\n\x1a\nsource").decode("ascii"),
        }
        request = {
            "prompt": "same subject",
            "mode": "img2img",
            "inputImage": source,
            "editTask": "character-sheet",
            "characterSheetView": "front",
            "characterSheetFraming": "auto",
            "characterSheetPhase": "identity-refine",
            "characterSheetAnchorImagePath": "C:/managed/face.png",
            "characterSheetBaseImagePath": "C:/managed/front.png",
            "characterSheetBaseHistoryPath": "C:/managed/front.json",
        }
        validated = api._validate_generation(request)
        self.assertEqual(validated["characterSheetPhase"], "identity-refine")
        self.assertEqual(validated["characterSheetAnchorImagePath"], "C:/managed/face.png")
        self.assertEqual(validated["characterSheetBaseImagePath"], "C:/managed/front.png")

        invalid = dict(request)
        invalid["editTask"] = "character-turnaround"
        with self.assertRaises(ValueError):
            api._validate_generation(invalid)

    def test_identity_refine_uses_generated_view_as_source_and_original_plus_anchor_references(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            output_root = repo / ".runtime" / "stableamd" / "output"
            history_root = repo / ".runtime" / "stableamd" / "history"
            output_root.mkdir(parents=True)
            history_root.mkdir(parents=True)
            base_image = output_root / "front-base.png"
            anchor_image = output_root / "face-anchor.png"
            base_image.write_bytes(b"base-view")
            anchor_image.write_bytes(b"face-anchor")
            base_history = history_root / "front-base.json"
            base_history.write_text(json.dumps({"promptId": "base", "galleryHidden": False}), encoding="utf-8")

            staged_payload_names: list[str] = []
            staged_paths: list[Path] = []

            def stage_input(_repo_root, payload):
                staged_payload_names.append(str(payload.get("name") or ""))
                path = repo / f"staged-{len(staged_paths)}.png"
                path.write_bytes(b"stage")
                staged_paths.append(path)
                return path

            class Parent:
                repo_root = repo

                def __init__(self):
                    self._stableamd_krea_edit_context = SimpleNamespace(value=None)
                    self.captured_context = None
                    self.captured_request = None

                def _selected_product_model(self, _request):
                    return {"id": "krea", "family": "krea2", "assetMode": "bundle"}

                def _krea_image_edit_ready(self):
                    return True

                def _control_request(self, _request):
                    return None

                def _generate_krea2_turbo(self, request, _selected):
                    self.captured_context = dict(self._stableamd_krea_edit_context.value or {})
                    self.captured_request = dict(request)
                    result_image = output_root / "front-refined.png"
                    result_image.write_bytes(b"refined")
                    return {
                        "PromptId": "refined",
                        "Prompt": request["prompt"],
                        "ModelId": "krea",
                        "ModelName": "Krea 2 Turbo",
                        "Width": request["width"],
                        "Height": request["height"],
                        "Seed": request.get("seed", 123),
                        "GenerationSeconds": 1.0,
                        "ImagePath": str(result_image),
                    }

                def _persist_krea_image_edit_metadata(self, *_args, **_kwargs):
                    return None

                def _post_comfy_no_content(self, *_args, **_kwargs):
                    return None

            class Bridge(anchor.CharacterSheetAnchorBridgeMixin, character_sheet.CharacterSheetBridgeMixin, Parent):
                def _prepare_character_sheet_reference(self, source, view, requested_framing):
                    return (
                        source,
                        "full-body",
                        {
                            "detected": True,
                            "faceBox": [100, 100, 220, 240],
                            "subjectBox": [80, 80, 500, 900],
                            "referenceCropped": True,
                        },
                        832,
                        1216,
                    )

                def _prepare_character_sheet_identity_reference(self, _source, _analysis):
                    return {
                        "name": "original-face.png",
                        "mimeType": "image/png",
                        "dataBase64": base64.b64encode(b"original-face").decode("ascii"),
                    }

            bridge = Bridge()
            request = {
                "modelId": "krea",
                "mode": "img2img",
                "prompt": "Preserve the exact same subject.",
                "inputImage": {
                    "name": "source.png",
                    "mimeType": "image/png",
                    "dataBase64": base64.b64encode(b"source").decode("ascii"),
                },
                "editTask": "character-sheet",
                "characterSheetView": "front",
                "characterSheetFraming": "auto",
                "characterSheetPhase": "identity-refine",
                "characterSheetAnchorImagePath": str(anchor_image),
                "characterSheetBaseImagePath": str(base_image),
                "characterSheetBaseHistoryPath": str(base_history),
                "seed": 424242,
            }

            with patch.object(character_sheet.base, "stage_input_image", side_effect=stage_input):
                result = bridge.generate(request)

            self.assertEqual(staged_payload_names[0], "front-base.png")
            self.assertIn("original-face.png", staged_payload_names)
            self.assertIn("face-anchor.png", staged_payload_names)
            self.assertEqual(len(bridge.captured_context.get("references") or []), 2)
            self.assertIn("identity refinement pass", bridge.captured_request["prompt"].lower())
            self.assertIn("preserve picture 1", bridge.captured_request["prompt"].lower())
            self.assertEqual(result.get("CharacterSheetPhase"), "identity-refined")
            hidden = json.loads(base_history.read_text(encoding="utf-8"))
            self.assertTrue(hidden.get("galleryHidden"))
            self.assertEqual(hidden.get("characterSheetRefinedByPromptId"), "refined")

    def test_frontend_uses_face_result_as_anchor_and_refines_visible_face_views(self):
        source = KREA_FRONTEND_PATH.read_text(encoding="utf-8")
        self.assertIn("CHARACTER_SHEET_IDENTITY_REFINE_VIEWS", source)
        self.assertIn('new Set(["front", "three-quarter", "side"])', source)
        self.assertIn("faceAnchorPath", source)
        self.assertIn('characterSheetPhase: "identity-refine"', source)
        self.assertIn("characterSheetAnchorImagePath: faceAnchorPath", source)
        self.assertIn("characterSheetBaseImagePath: imagePath", source)
        self.assertIn("characterSheetBaseHistoryPath", source)


if __name__ == "__main__":
    unittest.main()
