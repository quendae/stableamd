from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import stableamd_v03_character_sheet_v2 as sheetv2
import stableamd_v03_edit_server as server


BASE_REQUEST = {
    "prompt": "keep the same identity",
    "mode": "img2img",
    "modelId": "krea",
    "inputImage": {
        "name": "character.png",
        "mimeType": "image/png",
        "dataBase64": "iVBORw0KGgo=",
    },
    "editTask": "character-sheet",
}


class CharacterSheetV2ApiTests(unittest.TestCase):
    def test_api_accepts_v2_description_and_detailer(self):
        api = server.StableAmdApi(object())
        validated = api._validate_generation({
            **BASE_REQUEST,
            "characterSheetVersion": "v2",
            "characterDescription": "young girl in a red dress and bow",
            "characterSheetDetailer": True,
        })
        self.assertEqual(validated["characterSheetVersion"], "v2")
        self.assertEqual(validated["characterDescription"], "young girl in a red dress and bow")
        self.assertTrue(validated["characterSheetDetailer"])
        self.assertNotIn("characterSheetView", validated)

    def test_v2_defaults_detailer_and_rejects_legacy_fields(self):
        api = server.StableAmdApi(object())
        validated = api._validate_generation(dict(BASE_REQUEST))
        self.assertEqual(validated["characterSheetVersion"], "v2")
        self.assertTrue(validated["characterSheetDetailer"])

        for field, value in (("characterSheetView", "front"), ("characterSheetPhase", "base")):
            with self.assertRaisesRegex(ValueError, field):
                api._validate_generation({**BASE_REQUEST, "characterSheetVersion": "v2", field: value})

    def test_v2_rejects_bad_version_description_and_detailer_types(self):
        api = server.StableAmdApi(object())
        with self.assertRaisesRegex(ValueError, "characterSheetVersion"):
            api._validate_generation({**BASE_REQUEST, "characterSheetVersion": "v3"})
        with self.assertRaisesRegex(ValueError, "characterDescription"):
            api._validate_generation({**BASE_REQUEST, "characterSheetVersion": "v2", "characterDescription": 42})
        with self.assertRaisesRegex(ValueError, "characterSheetDetailer"):
            api._validate_generation({**BASE_REQUEST, "characterSheetVersion": "v2", "characterSheetDetailer": "yes"})

    def test_explicit_legacy_sequential_keeps_old_wire_contract(self):
        api = server.StableAmdApi(object())
        validated = api._validate_generation({
            **BASE_REQUEST,
            "characterSheetVersion": "legacy-sequential",
            "characterSheetView": "front",
            "characterSheetFraming": "auto",
            "characterSheetPhase": "base",
        })
        self.assertEqual(validated["characterSheetVersion"], "legacy-sequential")
        self.assertEqual(validated["characterSheetView"], "front")


class CharacterSheetV2RoutingTests(unittest.TestCase):
    def test_prompt_appends_character_description_only_when_present(self):
        plain = sheetv2.CharacterSheetV2BridgeMixin._character_sheet_v2_prompt("")
        described = sheetv2.CharacterSheetV2BridgeMixin._character_sheet_v2_prompt("red dress, blue bow")
        self.assertIn("five clearly separated panels", plain.lower())
        self.assertIn("strict side profile", plain.lower())
        self.assertIn("exact same person", plain.lower())
        self.assertNotIn("Character description:", plain)
        self.assertTrue(described.endswith("Character description: red dress, blue bow"))

    def test_v2_routes_one_base_identity_job_with_owned_geometry(self):
        calls = []

        class Parent:
            repo_root = Path(".")

            def _selected_product_model(self, request):
                return {"id": "krea", "family": "krea2", "assetMode": "bundle", "name": "Krea 2 Turbo"}

            def _krea_identity_edit_ready(self):
                return True

            def _stage_character_sheet_v2_source(self, source):
                class Staged:
                    name = "source-v2.png"
                    def unlink(self, missing_ok=False):
                        calls.append(("unlink", missing_ok))
                return Staged()

            def _generate_krea_identity_edit(self, request, model, **context):
                calls.append(("identity", dict(context), dict(request)))
                return {
                    "PromptId": "base-prompt",
                    "ImagePath": "C:/output/base.png",
                    "HistoryPath": "C:/history/base.json",
                    "ModelId": "krea",
                    "ModelName": "Krea 2 Turbo",
                    "Seed": 123,
                    "GenerationSeconds": 7.5,
                }

            def _persist_character_sheet_v2_base_metadata(self, result, metadata):
                calls.append(("metadata", dict(metadata)))

            def _release_character_sheet_runtime(self):
                calls.append(("free",))
                return True

            def generate(self, request):
                calls.append(("legacy", dict(request)))
                return {"legacy": True}

        class Bridge(sheetv2.CharacterSheetV2BridgeMixin, Parent):
            pass

        result = Bridge().generate_character_sheet_v2({
            **BASE_REQUEST,
            "characterSheetVersion": "v2",
            "characterDescription": "red dress, blue bow",
            "characterSheetDetailer": False,
            "seed": 123,
        })
        identity_call = next(item for item in calls if item[0] == "identity")
        context = identity_call[1]
        clean_request = identity_call[2]
        self.assertEqual(context["image_name"], "source-v2.png")
        self.assertEqual(context["width"], 1792)
        self.assertEqual(context["height"], 1024)
        self.assertIn("Character description: red dress, blue bow", context["prompt"])
        self.assertEqual(clean_request["mode"], "img2img")
        self.assertEqual(len([item for item in calls if item[0] == "identity"]), 1)
        self.assertIn(("free",), calls)
        self.assertEqual(result["CharacterSheetVersion"], "v2-identity-edit")
        self.assertEqual(result["CharacterSheetIdentityLora"], "krea2_identity_edit_v1_2.safetensors")
        self.assertEqual(result["CharacterSheetIdentityLoraStrength"], 1.0)
        self.assertEqual(result["CharacterSheetRefBoost"], 4.0)
        self.assertEqual(result["CharacterSheetGroundingPx"], 1024)
        self.assertEqual(result["CharacterSheetBaseImagePath"], "C:/output/base.png")

    def test_generate_defaults_to_v2_but_explicit_legacy_delegates(self):
        calls = []

        class Parent:
            def _krea_identity_edit_ready(self):
                return True

            def generate(self, request):
                calls.append("legacy")
                return {"legacy": True}

        class Bridge(sheetv2.CharacterSheetV2BridgeMixin, Parent):
            def generate_character_sheet_v2(self, request):
                calls.append("v2")
                return {"v2": True}

        bridge = Bridge()
        self.assertTrue(bridge.generate(dict(BASE_REQUEST))["v2"])
        self.assertTrue(bridge.generate({
            **BASE_REQUEST,
            "characterSheetVersion": "legacy-sequential",
            "characterSheetView": "front",
        })["legacy"])
        self.assertEqual(calls, ["v2", "legacy"])

    def test_missing_dependency_never_silently_falls_back(self):
        class Parent:
            def _krea_identity_edit_ready(self):
                return False
            def generate(self, request):
                return {"legacy": True}

        class Bridge(sheetv2.CharacterSheetV2BridgeMixin, Parent):
            pass

        with self.assertRaisesRegex(sheetv2.base.StableAmdBridgeError, "Identity Edit"):
            Bridge().generate(dict(BASE_REQUEST))
        with self.assertRaisesRegex(sheetv2.base.StableAmdBridgeError, "Identity Edit"):
            Bridge().generate({**BASE_REQUEST, "characterSheetVersion": "v2"})


if __name__ == "__main__":
    unittest.main()
