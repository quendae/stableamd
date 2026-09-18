from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "app" / "backend"
FRONTEND = ROOT / "app" / "frontend"
KREA_EDIT_PATH = BACKEND / "stableamd_v03_krea_edit.py"
FRONTEND_PATH = FRONTEND / "app-krea-edit.js"


class StableAmdKreaMaterialEditTests(unittest.TestCase):
    def _load_edit_module(self):
        if str(BACKEND) not in sys.path:
            sys.path.insert(0, str(BACKEND))
        spec = importlib.util.spec_from_file_location("stableamd_v03_krea_material_test", KREA_EDIT_PATH)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_krea_edit_policy_advertises_material_replacement_task(self):
        module = self._load_edit_module()

        class Parent:
            def model_support(self):
                return {
                    "models": [
                        {
                            "id": "krea",
                            "family": "krea2",
                            "capabilities": {"txt2img": "supported", "img2img": "planned"},
                        }
                    ]
                }

            def _node_available(self, _name):
                return True

        class Bridge(module.KreaImageEditBridgeMixin, Parent):
            pass

        policy = Bridge().model_support()["models"][0]["editPolicy"]
        tasks = {item["id"]: item for item in policy["tasks"]}
        self.assertEqual(tasks["general"]["label"], "General edit")
        self.assertEqual(tasks["material-replace"]["label"], "Material / texture")
        self.assertEqual(tasks["material-replace"]["referenceImages"], 1)
        self.assertFalse(tasks["material-replace"]["masked"])

    def test_frontend_material_task_exposes_target_presets_and_custom_material(self):
        source = FRONTEND_PATH.read_text(encoding="utf-8")
        self.assertIn('id="krea-edit-task"', source)
        self.assertIn('Material / texture', source)
        self.assertIn('id="krea-material-target"', source)
        self.assertIn('id="krea-material-preset"', source)
        for material in ("Leather", "Wood", "Marble", "Metal", "Concrete", "Fabric", "Glass", "Custom"):
            self.assertIn(material, source)
        self.assertIn('id="krea-material-custom"', source)

    def test_frontend_material_task_builds_deterministic_edit_instruction(self):
        source = FRONTEND_PATH.read_text(encoding="utf-8")
        self.assertIn("function buildMaterialInstruction", source)
        self.assertIn("Replace the material or texture of", source)
        self.assertIn("Preserve the object's shape, geometry, position", source)
        self.assertIn("payload.prompt = materialInstruction", source)
        self.assertIn("Additional instruction (optional)", source)


if __name__ == "__main__":
    unittest.main()
