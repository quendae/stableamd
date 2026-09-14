import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_v03_lora_server as lora_server
import stableamd_v03_server as v03


ZIMAGE = {
    "id": "bnd_zimage",
    "name": "Z-Image Turbo",
    "family": "z-image-turbo",
    "provider": "z-image-turbo-bundle",
    "assetMode": "bundle",
}


class FakeBridge(lora_server.PowerShellBridge):
    def __init__(self):
        super().__init__(REPO_ROOT, powershell=sys.executable)

    def _comfy_json(self, relative_path):
        if relative_path == "object_info/LoraLoaderModelOnly":
            return {
                "LoraLoaderModelOnly": {
                    "input": {
                        "required": {
                            "lora_name": ["COMBO", {"options": ["z-image/style.safetensors", "z-image/detail.safetensors"]}]
                        }
                    }
                }
            }
        raise AssertionError(relative_path)

    def models(self):
        return [ZIMAGE]

    def lora_catalog(self):
        return [{"name": "z-image/style.safetensors", "family": "z-image"}]


class StableAmdV03ZImageLoraServerTests(unittest.TestCase):
    def setUp(self):
        self.bridge = FakeBridge()

    def test_wrapper_can_be_executed_directly_from_repo_root(self):
        completed = subprocess.run(
            [sys.executable, str(BACKEND_ROOT / "stableamd_v03_lora_server.py"), "--help"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("StableAMD v0.3", completed.stdout)

    def test_zimage_matching_lora_passes_product_capability_gate(self):
        request = {
            "modelId": "bnd_zimage",
            "loraStack": [{"name": "z-image/style.safetensors", "modelStrength": 0.75, "clipStrength": 1.0, "enabled": True}],
        }
        self.assertIsNone(self.bridge.lora_compatibility_error(request))

    def test_zimage_lora_resolution_uses_model_only_comfy_node_and_zeroes_clip_strength(self):
        resolved = self.bridge._resolve_zimage_loras(
            {
                "loraStack": [
                    {"name": "z-image/style.safetensors", "modelStrength": 0.75, "clipStrength": 0.4, "enabled": True}
                ]
            }
        )
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["name"], "z-image/style.safetensors")
        self.assertEqual(resolved[0]["modelStrength"], 0.75)
        self.assertEqual(resolved[0]["clipStrength"], 0.0)
        self.assertTrue(resolved[0]["enabled"])

    def test_workflow_builder_receives_resolved_zimage_lora_stack(self):
        stack = [{"name": "z-image/style.safetensors", "modelStrength": 0.8, "clipStrength": 0.0, "enabled": True}]
        self.bridge._zimage_lora_context.stack = stack
        try:
            with patch.object(v03.PowerShellBridge, "_run_script", return_value={"ok": True}) as delegated:
                result = self.bridge._run_script(
                    "Build-StableAmdWorkflow.ps1",
                    [("Family", "z-image-turbo"), ("Mode", "txt2img"), ("Prompt", "test")],
                )
        finally:
            self.bridge._zimage_lora_context.stack = []

        self.assertEqual(result, {"ok": True})
        params = delegated.call_args.args[1]
        payload = next(value for key, value in params if key == "LoraStackJson")
        self.assertEqual(json.loads(payload), stack)

    def test_history_record_keeps_zimage_lora_metadata(self):
        stack = [{"name": "z-image/style.safetensors", "modelStrength": 0.8, "clipStrength": 0.0, "enabled": True}]
        self.bridge._zimage_lora_context.stack = stack
        record = {"loraStack": []}
        try:
            with patch.object(v03.PowerShellBridge, "_save_zimage_history", return_value=REPO_ROOT / "z.json") as delegated:
                path = self.bridge._save_zimage_history(record)
        finally:
            self.bridge._zimage_lora_context.stack = []

        self.assertEqual(path, REPO_ROOT / "z.json")
        saved = delegated.call_args.args[0]
        self.assertEqual(saved["loraStack"], stack)
        self.assertEqual(saved["loraName"], "z-image/style.safetensors")
        self.assertEqual(saved["loraModelStrength"], 0.8)
        self.assertEqual(saved["loraClipStrength"], 0.0)

    def test_gallery_delete_accepts_legacy_pascal_case_history_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo_root = Path(temporary)
            history_root = repo_root / ".runtime" / "stableamd" / "history"
            output_root = repo_root / ".runtime" / "stableamd" / "output"
            history_root.mkdir(parents=True)
            output_root.mkdir(parents=True)

            image = output_root / "legacy.png"
            image.write_bytes(b"png")
            record_path = history_root / "legacy.json"
            record_path.write_text(
                json.dumps({"PromptId": "legacy-prompt", "ImagePath": str(image)}),
                encoding="utf-8",
            )

            bridge = lora_server.PowerShellBridge(repo_root, powershell=sys.executable)
            result = bridge.delete_history("legacy-prompt")

            self.assertTrue(result["deleted"])
            self.assertTrue(result["imageDeleted"])
            self.assertFalse(record_path.exists())
            self.assertFalse(image.exists())


if __name__ == "__main__":
    unittest.main()
