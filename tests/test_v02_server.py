import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from stableamd_server import PowerShellBridge, StableAmdApi


class V02Bridge:
    def __init__(self):
        self.calls = []

    def generation_options(self):
        self.calls.append(("generation_options", None))
        return {
            "samplers": ["euler", "dpmpp_2m"],
            "schedulers": ["normal", "karras"],
            "loras": ["styles\\storybook.safetensors"],
        }

    def generate(self, request):
        self.calls.append(("generate", request))
        return {"PromptId": "v02", "LoraName": request.get("loraName", "")}


class StableAmdV02ApiTests(unittest.TestCase):
    def setUp(self):
        self.bridge = V02Bridge()
        self.api = StableAmdApi(self.bridge)

    def test_generation_options_are_exposed_as_product_metadata(self):
        status, payload = self.api.dispatch("GET", "/api/generation-options")
        self.assertEqual(status, 200)
        self.assertIn("euler", payload["samplers"])
        self.assertIn("karras", payload["schedulers"])
        self.assertEqual(payload["loras"], ["styles\\storybook.safetensors"])
        self.assertEqual(self.bridge.calls, [("generation_options", None)])

    def test_generation_accepts_one_lora_with_separate_strengths(self):
        request = {
            "prompt": "storybook cat",
            "modelId": "mdl_sdxl",
            "loraName": "styles\\storybook.safetensors",
            "loraModelStrength": 0.8,
            "loraClipStrength": 0.65,
        }
        status, payload = self.api.dispatch("POST", "/api/generate", json.dumps(request).encode("utf-8"))
        self.assertEqual(status, 200)
        self.assertEqual(payload["LoraName"], request["loraName"])
        self.assertEqual(self.bridge.calls[-1], ("generate", request))

    def test_generation_rejects_invalid_lora_strengths(self):
        for value in ("strong", True, 101, -101):
            request = {"prompt": "cat", "loraName": "style.safetensors", "loraModelStrength": value}
            before = len(self.bridge.calls)
            status, payload = self.api.dispatch("POST", "/api/generate", json.dumps(request).encode("utf-8"))
            self.assertEqual(status, 400)
            self.assertIn("loraModelStrength", payload["error"])
            self.assertEqual(len(self.bridge.calls), before)

    def test_comfy_choice_parser_reads_node_enum_contract(self):
        payload = {
            "KSampler": {
                "input": {
                    "required": {
                        "sampler_name": [["euler", "dpmpp_2m"]],
                    }
                }
            }
        }
        self.assertEqual(
            PowerShellBridge._comfy_choice_list(payload, "KSampler", "sampler_name"),
            ["euler", "dpmpp_2m"],
        )


if __name__ == "__main__":
    unittest.main()
