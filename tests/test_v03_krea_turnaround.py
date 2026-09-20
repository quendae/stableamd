from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "app" / "backend"
FRONTEND = ROOT / "app" / "frontend"
KREA_EDIT_PATH = BACKEND / "stableamd_v03_krea_edit.py"
FINAL_SERVER_PATH = BACKEND / "stableamd_v03_edit_server.py"
FRONTEND_PATH = FRONTEND / "app-krea-edit.js"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import stableamd_v03_edit_server as server


class StableAmdKreaTurnaroundTests(unittest.TestCase):
    def _load_edit_module(self):
        spec = importlib.util.spec_from_file_location("stableamd_v03_krea_turnaround_test", KREA_EDIT_PATH)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _workflow() -> dict:
        return {
            "10": {"class_type": "UNETLoader", "inputs": {}},
            "11": {"class_type": "CLIPLoader", "inputs": {"device": "cpu"}},
            "12": {"class_type": "VAELoader", "inputs": {}},
            "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["10", 0],
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "latent_image": ["5", 0],
                    "cfg": 1.0,
                },
            },
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "turnaround"}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["12", 0]}},
        }

    def test_krea_policy_advertises_character_turnaround_task(self):
        module = self._load_edit_module()

        class Parent:
            def model_support(self):
                return {
                    "models": [{
                        "id": "krea",
                        "family": "krea2",
                        "capabilities": {"txt2img": "supported", "img2img": "planned"},
                    }]
                }

            def _node_available(self, _name):
                return True

        class Bridge(module.KreaImageEditBridgeMixin, Parent):
            pass

        policy = Bridge().model_support()["models"][0]["editPolicy"]
        tasks = {item["id"]: item for item in policy["tasks"]}
        task = tasks["character-turnaround"]
        self.assertEqual(task["label"], "Character turnaround")
        self.assertEqual(task["referenceImages"], 0)
        self.assertEqual(task["outputSize"], {"width": 1536, "height": 768})
        self.assertEqual(task["views"], ["front", "three-quarter", "side", "back"])
        self.assertFalse(task["sourceSizeOutput"])

    def test_api_accepts_only_character_turnaround_edit_task_on_img2img(self):
        api = server.StableAmdApi(object())
        request = {
            "prompt": "optional notes",
            "mode": "img2img",
            "inputImage": {
                "name": "character.png",
                "mimeType": "image/png",
                "dataBase64": "iVBORw0KGgo=",
            },
            "editTask": "character-turnaround",
        }
        validated = api._validate_generation(request)
        self.assertEqual(validated["editTask"], "character-turnaround")

        with self.assertRaisesRegex(ValueError, "editTask"):
            api._validate_generation({**request, "editTask": "unknown-task"})
        with self.assertRaisesRegex(ValueError, "img2img"):
            api._validate_generation({**request, "mode": "txt2img"})

    def test_turnaround_instruction_demands_consistent_four_view_sheet_without_text(self):
        module = self._load_edit_module()
        instruction = module.KreaImageEditBridgeMixin._build_character_turnaround_instruction(
            "keep the red scarf"
        )
        lowered = instruction.lower()
        self.assertIn("same character", lowered)
        self.assertIn("front view", lowered)
        self.assertIn("three-quarter view", lowered)
        self.assertIn("side", lowered)
        self.assertIn("back view", lowered)
        self.assertIn("full body", lowered)
        self.assertIn("equal scale", lowered)
        self.assertIn("neutral", lowered)
        self.assertIn("do not add text", lowered)
        self.assertIn("keep the red scarf", instruction)

    def test_turnaround_graph_uses_fixed_1536_by_768_target_instead_of_source_dimensions(self):
        module = self._load_edit_module()

        class Parent:
            def _node_available(self, _name):
                return True

        class Bridge(module.KreaImageEditBridgeMixin, Parent):
            pass

        result = Bridge()._inject_krea_image_edit(
            self._workflow(),
            {
                "image_name": "character.png",
                "output_size": {"width": 1536, "height": 768},
            },
        )
        self.assertEqual(result["85"]["inputs"]["image1"], ["81", 0])
        self.assertEqual(result["5"]["inputs"]["width"], 1536)
        self.assertEqual(result["5"]["inputs"]["height"], 768)

    def test_turnaround_metadata_records_operation_layout_and_views(self):
        module = self._load_edit_module()

        class Parent:
            repo_root = ROOT

        class Bridge(module.KreaImageEditBridgeMixin, Parent):
            pass

        result = {}
        Bridge()._persist_krea_image_edit_metadata(
            result,
            "character.png",
            edit_operation="character-turnaround",
            turnaround={
                "layout": "four-view-horizontal",
                "views": ["front", "three-quarter", "side", "back"],
                "width": 1536,
                "height": 768,
            },
        )
        self.assertEqual(result["EditOperation"], "character-turnaround")
        self.assertEqual(result["TurnaroundLayout"], "four-view-horizontal")
        self.assertEqual(result["TurnaroundViews"], ["front", "three-quarter", "side", "back"])
        self.assertEqual(result["TurnaroundWidth"], 1536)
        self.assertEqual(result["TurnaroundHeight"], 768)

    def test_frontend_exposes_turnaround_task_and_suppresses_extra_references(self):
        source = FRONTEND_PATH.read_text(encoding="utf-8")
        self.assertIn('value="character-turnaround"', source)
        self.assertIn("Character turnaround", source)
        self.assertIn("function buildCharacterTurnaroundInstruction", source)
        self.assertIn('payload.editTask = "character-turnaround"', source)
        self.assertIn("payload.prompt = buildCharacterTurnaroundInstruction()", source)
        self.assertIn("delete payload.references", source)
        self.assertIn("1536 × 768", source)
        self.assertIn("front / 3/4 / side / back", source)


if __name__ == "__main__":
    unittest.main()
