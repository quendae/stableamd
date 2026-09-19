import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_v03_server as v03


class LoraApiBridge:
    def __init__(self):
        self.generated = []

    def lora_catalog(self):
        return [
            {
                "name": "sdxl/style.safetensors",
                "path": "C:/loras/sdxl/style.safetensors",
                "family": "sdxl",
                "confidence": "folder",
                "reason": "family folder: sdxl",
            }
        ]

    def lora_compatibility_error(self, request):
        for entry in request.get("loraStack", []):
            if entry.get("enabled", True) and entry.get("name") == "sdxl/style.safetensors" and request.get("modelId") == "z-image":
                return "LoRA 'sdxl/style.safetensors' targets family 'sdxl' and is incompatible with selected model family 'z-image-turbo'."
        return None

    def generate(self, request):
        self.generated.append(request)
        return {"PromptId": "ok"}


class StableAmdV03LoraApiTests(unittest.TestCase):
    def setUp(self):
        self.bridge = LoraApiBridge()
        self.api = v03.StableAmdApi(self.bridge)

    def test_catalog_route_returns_family_metadata(self):
        status, payload = self.api.dispatch("GET", "/api/lora-catalog")
        self.assertEqual(status, 200)
        self.assertEqual(payload[0]["family"], "sdxl")
        self.assertEqual(payload[0]["confidence"], "folder")

    def test_known_incompatible_lora_is_rejected_before_generation(self):
        request = {
            "prompt": "cat",
            "modelId": "z-image",
            "loraStack": [{"name": "sdxl/style.safetensors", "enabled": True}],
        }
        status, payload = self.api.dispatch("POST", "/api/generate", json.dumps(request).encode("utf-8"))
        self.assertEqual(status, 400)
        self.assertIn("incompatible", payload["error"])
        self.assertEqual(self.bridge.generated, [])

    def test_unknown_or_compatible_request_still_reaches_generation(self):
        request = {
            "prompt": "cat",
            "modelId": "sdxl",
            "loraStack": [{"name": "unknown-style.safetensors", "enabled": True}],
        }
        status, payload = self.api.dispatch("POST", "/api/generate", json.dumps(request).encode("utf-8"))
        self.assertEqual(status, 200)
        self.assertEqual(payload["PromptId"], "ok")
        self.assertEqual(len(self.bridge.generated), 1)


if __name__ == "__main__":
    unittest.main()
