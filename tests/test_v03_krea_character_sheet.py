from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "app" / "backend"
FRONTEND = ROOT / "app" / "frontend"
KREA_FRONTEND_PATH = FRONTEND / "app-krea-edit.js"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import stableamd_v03_character_sheet as character_sheet
import stableamd_v03_edit_server as server


class StableAmdKreaCharacterSheetTests(unittest.TestCase):
    def test_krea_policy_advertises_sequential_character_sheet(self):
        module = character_sheet

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

        class Bridge(module.CharacterSheetBridgeMixin, Parent):
            pass

        policy = Bridge().model_support()["models"][0]["editPolicy"]
        tasks = {item["id"]: item for item in policy["tasks"]}
        task = tasks["character-sheet"]
        self.assertEqual(task["label"], "Character sheet")
        self.assertEqual(task["referenceImages"], 0)
        self.assertEqual(task["outputSize"], {"width": 1024, "height": 1024})
        self.assertEqual(
            task["views"],
            ["face-close-up", "front", "three-quarter", "side", "back"],
        )
        self.assertEqual(task["generationMode"], "sequential")
        self.assertFalse(task["sourceSizeOutput"])

    def test_api_accepts_character_sheet_view_and_rejects_unknown_view(self):
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
        }
        validated = api._validate_generation(request)
        self.assertEqual(validated["editTask"], "character-sheet")
        self.assertEqual(validated["characterSheetView"], "side")

        with self.assertRaisesRegex(ValueError, "characterSheetView"):
            api._validate_generation({**request, "characterSheetView": "diagonal"})

    def test_each_sheet_view_builds_a_single_view_instruction(self):
        builder = character_sheet.CharacterSheetBridgeMixin._build_character_sheet_instruction

        face = builder("face-close-up", "keep the red scarf")
        front = builder("front", "keep the red scarf")
        side = builder("side", "keep the red scarf")
        back = builder("back", "keep the red scarf")

        for instruction in (face, front, side, back):
            lowered = instruction.lower()
            self.assertIn("same character", lowered)
            self.assertIn("only one character", lowered)
            self.assertIn("neutral", lowered)
            self.assertIn("keep the red scarf", instruction)
            self.assertNotIn("show the same character four times", lowered)

        self.assertIn("close-up", face.lower())
        self.assertIn("front", front.lower())
        self.assertIn("side profile", side.lower())
        self.assertIn("back view", back.lower())

    def test_frontend_prefills_prompt_runs_five_sequential_views_and_returns_grid_payload(self):
        source = KREA_FRONTEND_PATH.read_text(encoding="utf-8")
        self.assertIn('value="character-sheet"', source)
        self.assertIn("Character sheet", source)
        self.assertIn("CHARACTER_SHEET_DEFAULT_PROMPT", source)
        self.assertIn("face-close-up", source)
        self.assertIn("three-quarter", source)
        self.assertIn("characterSheetView", source)
        self.assertIn("for (const view of CHARACTER_SHEET_VIEWS)", source)
        self.assertIn("CharacterSheetItems", source)
        self.assertNotIn('value="character-turnaround"', source)

    def test_generation_result_renders_character_sheet_as_grid(self):
        source = KREA_FRONTEND_PATH.read_text(encoding="utf-8")
        self.assertIn("CharacterSheetItems", source)
        self.assertIn("character-sheet-grid", source)
        self.assertIn("character-sheet-item", source)
        self.assertIn("Character sheet complete", source)


if __name__ == "__main__":
    unittest.main()
