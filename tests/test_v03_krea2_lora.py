from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_v03_edit_server as server


class StableAmdV03Krea2LoraTests(unittest.TestCase):
    def test_official_model_only_chain_is_inserted_between_krea_unet_and_sampler(self):
        bridge = server.PowerShellBridge(REPO_ROOT, powershell=sys.executable)
        bridge._krea_lora_context.stack = [
            {"name": "krea2_darkbrush.safetensors", "modelStrength": 0.8, "clipStrength": 0.0, "enabled": True},
            {"name": "krea2_dotmatrix.safetensors", "modelStrength": 0.6, "clipStrength": 0.0, "enabled": True},
        ]
        workflow = {
            "10": {"class_type": "UNETLoader", "inputs": {"unet_name": "krea.safetensors"}},
            "3": {"class_type": "KSampler", "inputs": {"model": ["10", 0]}},
        }
        parameters = [("Family", "krea2"), ("Mode", "txt2img")]

        with patch.object(server.editing.PowerShellBridge, "_run_script", return_value=workflow):
            result = bridge._run_script("Build-StableAmdWorkflow.ps1", parameters)

        self.assertEqual(result["40"]["class_type"], "LoraLoaderModelOnly")
        self.assertEqual(result["40"]["inputs"]["model"], ["10", 0])
        self.assertEqual(result["40"]["inputs"]["lora_name"], "krea2_darkbrush.safetensors")
        self.assertEqual(result["41"]["inputs"]["model"], ["40", 0])
        self.assertEqual(result["3"]["inputs"]["model"], ["41", 0])
        self.assertNotIn("clip", result["40"]["inputs"])

    def test_krea_generation_passes_clean_request_to_proven_provider_and_persists_stack(self):
        stack = [
            {"name": "krea/krea2_darkbrush.safetensors", "modelStrength": 1.0, "clipStrength": 0.0, "enabled": True}
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            history_root = root / ".runtime" / "stableamd" / "history"
            history_root.mkdir(parents=True)
            history_path = history_root / "krea.json"
            history_path.write_text(json.dumps({"loraStack": []}), encoding="utf-8")
            bridge = server.PowerShellBridge(root, powershell=sys.executable)
            bridge._resolve_krea_loras = lambda request: stack
            captured = {}

            def inherited_generate(instance, request, model):
                captured["request"] = dict(request)
                return {"HistoryPath": str(history_path), "Family": "krea2", "Provider": "krea2-bundle"}

            request = {
                "prompt": "monochrome ink wash portrait",
                "mode": "txt2img",
                "loraStack": [{"name": "krea/krea2_darkbrush.safetensors", "modelStrength": 1.0}],
            }
            with patch.object(server.editing.PowerShellBridge, "_generate_krea2_turbo", new=inherited_generate):
                result = bridge._generate_krea2_turbo(request, {"id": "krea"})

            self.assertNotIn("loraStack", captured["request"])
            self.assertEqual(result["LoraStack"], stack)
            self.assertEqual(result["LoraName"], "krea/krea2_darkbrush.safetensors")
            self.assertEqual(result["LoraClipStrength"], 0.0)
            record = json.loads(history_path.read_text(encoding="utf-8"))
            self.assertEqual(record["loraStack"], stack)
            self.assertEqual(record["loraName"], "krea/krea2_darkbrush.safetensors")
            self.assertEqual(record["loraClipStrength"], 0.0)

    def test_krea_support_catalog_declares_model_only_ordered_lora_stack(self):
        catalog = json.loads((REPO_ROOT / "config" / "model-support.v0.3.json").read_text(encoding="utf-8"))
        krea = catalog["families"]["krea2"]
        self.assertEqual(krea["capabilities"]["lora"], "supported")
        self.assertTrue(krea["loraPolicy"]["orderedStack"])
        self.assertEqual(krea["loraPolicy"]["maxStack"], 8)
        self.assertTrue(krea["loraPolicy"]["perEntryModelStrength"])
        self.assertFalse(krea["loraPolicy"]["perEntryClipStrength"])


if __name__ == "__main__":
    unittest.main()
