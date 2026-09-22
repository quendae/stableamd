import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from stableamd_server import StableAmdApi


class V03Bridge:
    def __init__(self):
        self.calls = []

    def model_support(self):
        self.calls.append(("model_support", None))
        return {
            "catalogVersion": "0.3",
            "modes": ["txt2img", "img2img", "inpaint", "controlnet", "lora"],
            "models": [
                {
                    "id": "mdl_sdxl",
                    "family": "sdxl",
                    "provider": "sdxl-checkpoint",
                    "loraPolicy": {"orderedStack": True, "maxStack": 8},
                    "capabilities": {"txt2img": "supported", "lora": "supported"},
                }
            ],
        }

    def generate(self, request):
        self.calls.append(("generate", request))
        return {"PromptId": "p-v03", "LoraStack": request.get("loraStack", [])}


class StableAmdV03ApiTests(unittest.TestCase):
    def setUp(self):
        self.bridge = V03Bridge()
        self.api = StableAmdApi(self.bridge)

    def test_model_support_route_exposes_capabilities_and_lora_policy(self):
        status, payload = self.api.dispatch("GET", "/api/model-support")
        self.assertEqual(status, 200)
        self.assertEqual(payload["catalogVersion"], "0.3")
        self.assertEqual(payload["models"][0]["provider"], "sdxl-checkpoint")
        self.assertEqual(payload["models"][0]["loraPolicy"]["maxStack"], 8)
        self.assertEqual(self.bridge.calls, [("model_support", None)])

    def test_generate_accepts_ordered_multi_lora_stack(self):
        request = {
            "prompt": "storybook city",
            "modelId": "mdl_sdxl",
            "loraStack": [
                {"name": "style.safetensors", "modelStrength": 0.8, "clipStrength": 0.7, "enabled": True},
                {"name": "detail.safetensors", "modelStrength": 0.4, "clipStrength": 0.25, "enabled": True},
            ],
        }
        status, payload = self.api.dispatch("POST", "/api/generate", json.dumps(request).encode("utf-8"))
        self.assertEqual(status, 200)
        self.assertEqual([item["name"] for item in payload["LoraStack"]], ["style.safetensors", "detail.safetensors"])
        self.assertEqual(self.bridge.calls[-1], ("generate", request))

    def test_generate_rejects_invalid_or_ambiguous_lora_stacks(self):
        invalid = [
            {"prompt": "x", "loraStack": "not-a-list"},
            {"prompt": "x", "loraStack": [{}]},
            {"prompt": "x", "loraStack": [{"name": "a", "enabled": "yes"}]},
            {"prompt": "x", "loraStack": [{"name": "a", "modelStrength": True}]},
            {"prompt": "x", "loraStack": [{"name": "a", "clipStrength": 101}]},
            {"prompt": "x", "loraStack": [{"name": "a", "command": "whoami"}]},
            {"prompt": "x", "loraStack": [{"name": f"{i}.safetensors"} for i in range(9)]},
            {"prompt": "x", "loraName": "legacy.safetensors", "loraStack": [{"name": "new.safetensors"}]},
        ]
        for request in invalid:
            before = len(self.bridge.calls)
            status, payload = self.api.dispatch("POST", "/api/generate", json.dumps(request).encode("utf-8"))
            self.assertEqual(status, 400, request)
            self.assertIn("error", payload)
            self.assertEqual(len(self.bridge.calls), before)


if __name__ == "__main__":
    unittest.main()
